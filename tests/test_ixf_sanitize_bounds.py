"""
IX-F data processing stays linear and within the fetch deadline, and
hostile data ends in fixed error messages.
"""

import copy
import json
import random
import time
from unittest import mock

import pytest
import reversion
from django.db import connection
from django.test.utils import CaptureQueriesContext

from peeringdb_server import ixf
from peeringdb_server.auto_approval import _validate_ixf_feed
from peeringdb_server.models import InternetExchange, IXLanPrefix, Organization, User

pytestmark = pytest.mark.django_db


class QuadraticMatcher:
    """
    The pairwise vlan matching the importer used before it was indexed,
    kept as the reference the indexed version must agree with.
    """

    importer = ixf.Importer()

    def match(self, connection_list):
        modified = []
        for i, connection in enumerate(connection_list):
            if len(connection.get("vlan_list", [])) == 0:
                continue
            remaining = connection_list[i + 1 :]
            lone = self.importer.find_vlan_needing_pair(connection)
            if lone is None:
                modified.append(connection)
                continue
            matching = [
                other
                for other in remaining
                if self.importer.connections_match(connection, other)
            ]
            if not matching:
                modified.append(connection)
                continue
            for lone_vlan in lone:
                found = self.find(lone_vlan, matching)
                if found is not None:
                    connection["vlan_list"].append(found)
            modified.append(connection)
        return modified

    def find(self, lone_vlan, matching):
        for connection in matching:
            for j, vlan in enumerate(connection["vlan_list"]):
                if self.importer.vlan_matches(lone_vlan, vlan):
                    return connection["vlan_list"].pop(j)
        return None


def random_connections(rng):
    connections = []
    for _ in range(rng.randint(0, 8)):
        vlans = []
        for _ in range(rng.randint(0, 4)):
            vlan = {"vlan_id": rng.choice([0, 1, 2])}
            kind = rng.choice(["4", "6", "46", "none", "null4"])
            if "4" in kind:
                vlan["ipv4"] = {"address": f"10.0.0.{rng.randint(1, 250)}"}
            if "6" in kind:
                vlan["ipv6"] = {"address": f"2001:db8::{rng.randint(1, 250):x}"}
            if kind == "null4":
                vlan["ipv4"] = None
            if rng.random() < 0.2:
                vlan.pop("vlan_id")
            vlans.append(vlan)
        connection = {
            "state": rng.choice(["active", "inactive"]),
            "if_list": [{"if_speed": rng.choice([1000, 10000])}],
        }
        # always present: the pairwise version raised KeyError on a later
        # connection without vlan_list
        connection["vlan_list"] = vlans
        if rng.random() < 0.2:
            connection.pop("state")
        connections.append(connection)
    return connections


def test_indexed_matching_agrees_with_pairwise():
    rng = random.Random(520)
    importer = ixf.Importer()
    for _ in range(3000):
        connections = random_connections(rng)
        expected = QuadraticMatcher().match(copy.deepcopy(connections))
        actual = importer.match_vlans_across_connections(copy.deepcopy(connections))
        assert actual == expected, json.dumps(connections)


def test_many_connections_stay_fast():
    connections = [
        {
            "state": "active",
            "if_list": [{"if_speed": 10000}],
            "vlan_list": [
                {
                    "vlan_id": 0,
                    "ipv4": {"address": f"10.{i // 65536}.{i // 256 % 256}.{i % 256}"},
                }
            ],
        }
        for i in range(50000)
    ]

    start = time.monotonic()
    ixf.Importer().match_vlans_across_connections(connections)
    assert time.monotonic() - start < 5


def test_processing_stops_at_deadline():
    member = {
        "asnum": 2906,
        "connection_list": [
            {
                "state": "active",
                "vlan_list": [{"vlan_id": 0, "ipv4": {"address": "10.0.0.1"}}],
            }
        ],
    }
    with pytest.raises(ixf.ixf_fetch.FetchError, match="took too long"):
        ixf.Importer().sanitize(
            {"member_list": [member]}, deadline=time.monotonic() - 1
        )


@pytest.mark.parametrize(
    "data,message",
    [
        ({"member_list": 5}, "IX-F data could not be processed"),
        (
            {"member_list": [{"connection_list": [5]}]},
            "IX-F data could not be processed",
        ),
        ([1, 2], "IX-F data is not a JSON object"),
    ],
)
def test_hostile_data_gets_fixed_message(monkeypatch, data, message):
    monkeypatch.setattr(ixf.ixf_fetch, "fetch_json", lambda url, **kwargs: data)
    assert ixf.Importer().fetch("https://ixf.example/feed.json") == {
        "pdb_error": message
    }


def test_slow_processing_gets_fixed_message(monkeypatch):
    monkeypatch.setattr(
        ixf.ixf_fetch,
        "fetch_json",
        lambda url, **kwargs: {
            "member_list": [{"asnum": 1, "connection_list": [{"vlan_list": []}]}]
        },
    )
    with mock.patch.object(ixf.time, "monotonic", side_effect=[0, 100, 100, 100]):
        data = ixf.Importer().fetch("https://ixf.example/feed.json", deadline=5)
    assert data == {"pdb_error": "Processing the IX-F data took too long"}


def test_auto_approval_survives_unexpected_fetch_failure(monkeypatch):
    monkeypatch.setattr(
        ixf.Importer, "fetch", mock.Mock(side_effect=RuntimeError("banner"))
    )
    assert _validate_ixf_feed("https://ixf.example/feed.json", None) == (
        False,
        "IX-F feed error: IX-F data could not be processed",
    )


def test_auto_approval_hostile_feed(monkeypatch):
    monkeypatch.setattr(
        ixf.ixf_fetch, "fetch_json", lambda url, **kwargs: {"member_list": 5}
    )
    assert _validate_ixf_feed("https://ixf.example/feed.json", None) == (
        False,
        "IX-F feed error: IX-F data could not be processed",
    )


@pytest.fixture
def ixlan():
    User.objects.get_or_create(
        username="ixf_importer", defaults={"email": "ixf_importer@localhost"}
    )
    with reversion.create_revision():
        org = Organization.objects.create(name="Bounds Org", status="ok")
        ix = InternetExchange.objects.create(
            name="Bounds Exchange", org=org, status="ok"
        )
        ixlan = ix.ixlan
        ixlan.ixf_ixp_member_list_url = "https://ixf.example/feed.json"
        ixlan.save()
        IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="195.69.144.0/22", protocol="IPv4"
        )
    return ixlan


@pytest.mark.parametrize("save", [True, False])
def test_internal_error_recorded_on_ixlan(ixlan, monkeypatch, save):
    monkeypatch.setattr(
        ixf.Importer, "parse", mock.Mock(side_effect=RuntimeError("boom"))
    )
    data = {"member_list": []}

    assert ixf.Importer().update(ixlan, save=save, data=data) is False

    ixlan.refresh_from_db()
    if save:
        assert ixlan.ixf_ixp_import_error == ixf.INTERNAL_ERROR
    else:
        assert not ixlan.ixf_ixp_import_error


@pytest.mark.parametrize(
    "members,count",
    [
        ([{"asnum": [1]}, {"asnum": 2}, {"asnum": 3}], 2),
        ([{"asnum": "a"}, {"asnum": "b"}, {"asnum": "c"}], 0),
        ([{"asnum": True}, {"asnum": 2**40}, {"asnum": -1}, {"asnum": 2.5}], 0),
        ([{"asnum": {"a": 1}}, {"asnum": None}, {"asnum": 64500}], 1),
    ],
)
def test_auto_approval_counts_only_integer_asns(monkeypatch, members, count):
    # through the real fetch and sanitize, only the transport is replaced
    monkeypatch.setattr(
        ixf.ixf_fetch, "fetch_json", lambda url, **kwargs: {"member_list": members}
    )
    org = Organization.objects.create(name="ASN Type Org", status="ok")

    valid, reason = _validate_ixf_feed("https://ixf.example/feed.json", org)

    assert valid is False
    assert reason == (
        f"IX-F feed contains {count} unique ASN(s); at least 3 are required"
    )


def test_auto_approval_survives_any_validation_error(monkeypatch, rf):
    from peeringdb_server import auto_approval

    user = User.objects.create_user("aa-user", "aa@ixf.example", "pw")
    user.emailaddress_set.create(email="aa@ixf.example", verified=True, primary=True)
    request = rf.post("/api/ix")
    request.user = user
    rdap = mock.Mock()
    rdap.return_value.get_ip.return_value.emails = ["aa@ixf.example"]
    monkeypatch.setattr(auto_approval, "RdapLookup", rdap)
    monkeypatch.setattr(
        auto_approval, "_validate_ixf_feed", mock.Mock(side_effect=ValueError("x"))
    )
    monkeypatch.setattr(
        auto_approval.EnvironmentSetting, "get_setting_value", lambda name: True
    )

    assert auto_approval.auto_approve_ix(
        request, "195.69.144.0/22", "https://ixf.example/feed.json"
    ) == (False, "pending", "IX-F feed error: IX-F data could not be processed")


def wide_connection(n):
    return [
        {
            "state": "active",
            "if_list": [{"if_speed": 10000}] * n,
            "vlan_list": [
                {"vlan_id": 0, "ipv4": {"address": f"10.0.{i // 256}.{i % 256}"}}
                for i in range(n)
            ],
        }
    ]


def test_wide_connection_stays_fast():
    start = time.monotonic()
    ixf.Importer().match_vlans_across_connections(wide_connection(20000))
    assert time.monotonic() - start < 2


def test_wide_connection_stops_at_deadline():
    with pytest.raises(ixf.ixf_fetch.FetchError, match="took too long"):
        ixf.Importer().match_vlans_across_connections(
            wide_connection(20000), deadline=time.monotonic()
        )


def test_unsortable_speeds_never_pair():
    connections = [
        {
            "state": "active",
            "if_list": [{"if_speed": 10000}, {"if_speed": "10000"}],
            "vlan_list": [{"vlan_id": 0, "ipv4": {"address": "10.0.0.1"}}],
        },
        {
            "state": "active",
            "if_list": [{"if_speed": 10000}, {"if_speed": "10000"}],
            "vlan_list": [{"vlan_id": 0, "ipv6": {"address": "2001:db8::1"}}],
        },
    ]
    result = ixf.Importer().match_vlans_across_connections(connections)
    assert [len(c["vlan_list"]) for c in result] == [1, 1]


def test_unhashable_vlan_id_is_skipped():
    connections = [
        {
            "state": "active",
            "vlan_list": [{"vlan_id": [1], "ipv4": {"address": "10.0.0.1"}}],
        },
        {
            "state": "active",
            "vlan_list": [{"vlan_id": [1], "ipv6": {"address": "2001:db8::1"}}],
        },
    ]
    result = ixf.Importer().match_vlans_across_connections(connections)
    assert [len(c["vlan_list"]) for c in result] == [1, 1]


def test_auto_approval_slow_feed_falls_back_to_manual(monkeypatch, settings):
    settings.IXF_PREFIXAUTO_FETCH_TIMEOUT = 10
    fetch = mock.Mock(
        return_value={"pdb_error": "Request to the IX-F member list URL timed out"}
    )
    monkeypatch.setattr(ixf.Importer, "fetch", fetch)

    valid, reason = _validate_ixf_feed("https://ixf.example/feed.json", None)

    assert fetch.call_args.kwargs == {"deadline": 10}
    assert (valid, reason) == (
        False,
        "IX-F feed error: Request to the IX-F member list URL timed out",
    )


COLLIDING = 2**61 - 1  # CPython hashes every multiple of this to 0


def test_colliding_vlan_ids_stay_fast():
    member = {
        "asnum": 2906,
        "connection_list": [
            {
                "state": "active",
                "vlan_list": [
                    {
                        "vlan_id": k * COLLIDING,
                        "ipv4": {"address": f"10.0.{k // 256}.{k % 256}"},
                    }
                    for k in range(1, 20001)
                ],
            }
        ],
    }
    start = time.monotonic()
    ixf.Importer().sanitize({"member_list": [member]}, deadline=time.monotonic() + 30)
    assert time.monotonic() - start < 2


def test_colliding_states_and_addresses_stay_fast():
    member = {
        "asnum": 2906,
        "connection_list": [
            {
                "state": k * COLLIDING,
                "if_list": [{"if_speed": k * COLLIDING}],
                "vlan_list": [{"vlan_id": 0, "ipv4": {"address": k * COLLIDING}}],
            }
            for k in range(1, 20001)
        ],
    }
    start = time.monotonic()
    ixf.Importer().sanitize({"member_list": [member]}, deadline=time.monotonic() + 30)
    assert time.monotonic() - start < 2


@pytest.mark.parametrize("vlan_id", [-1, 4096, 2**61 - 1, "10", 10.0, True, [1]])
def test_out_of_range_vlan_ids_never_group(vlan_id):
    importer = ixf.Importer()
    connections = [
        {
            "state": "active",
            "vlan_list": [{"vlan_id": vlan_id, "ipv4": {"address": "10.0.0.1"}}],
        },
        {
            "state": "active",
            "vlan_list": [{"vlan_id": vlan_id, "ipv6": {"address": "2001:db8::1"}}],
        },
    ]
    result = importer.match_vlans_across_connections(connections)
    assert [len(c["vlan_list"]) for c in result] == [1, 1]

    vlans = [
        {"vlan_id": vlan_id, "ipv4": {"address": "10.0.0.1"}},
        {"vlan_id": vlan_id, "ipv6": {"address": "2001:db8::1"}},
    ]
    assert len(importer.sanitize_vlans(vlans)) == 2


@pytest.mark.parametrize("vlan_id", [0, 4095, None, "missing"])
def test_in_range_vlan_ids_still_group(vlan_id):
    def vlan(protocol, address):
        entry = {protocol: {"address": address}}
        if vlan_id != "missing":
            entry["vlan_id"] = vlan_id
        return entry

    importer = ixf.Importer()
    connections = [
        {"state": "active", "vlan_list": [vlan("ipv4", "10.0.0.1")]},
        {"state": "active", "vlan_list": [vlan("ipv6", "2001:db8::1")]},
    ]
    result = importer.match_vlans_across_connections(connections)
    assert [len(c["vlan_list"]) for c in result] == [2]

    merged = importer.sanitize_vlans(
        [vlan("ipv4", "10.0.0.1"), vlan("ipv6", "2001:db8::1")]
    )
    assert len(merged) == 1


@pytest.mark.parametrize("if_list", [["10G"], "10G", [{"if_speed": 1.5}]])
def test_odd_if_list_never_pairs(if_list):
    connections = [
        {
            "state": "active",
            "if_list": if_list,
            "vlan_list": [{"vlan_id": 0, "ipv4": {"address": "10.0.0.1"}}],
        },
        {
            "state": "active",
            "if_list": if_list,
            "vlan_list": [{"vlan_id": 0, "ipv6": {"address": "2001:db8::1"}}],
        },
    ]
    result = ixf.Importer().match_vlans_across_connections(connections)
    assert [len(c["vlan_list"]) for c in result] == [1, 1]


def test_many_members_stop_at_deadline():
    data = {"member_list": [{"asnum": n} for n in range(500000)]}
    start = time.monotonic()
    with pytest.raises(ixf.ixf_fetch.FetchError, match="took too long"):
        ixf.Importer().sanitize(data, deadline=time.monotonic() + 1)
    assert time.monotonic() - start < 2


def test_deadline_checked_after_matching(monkeypatch):
    importer = ixf.Importer()
    match = importer.match_vlans_across_connections

    def slow_match(connections, deadline=None):
        result = match(connections, deadline=deadline)
        time.sleep(0.3)
        return result

    monkeypatch.setattr(importer, "match_vlans_across_connections", slow_match)
    member = {
        "asnum": 1,
        "connection_list": [
            {
                "state": "active",
                "vlan_list": [{"vlan_id": 0, "ipv4": {"address": "10.0.0.1"}}],
            }
        ],
    }
    with pytest.raises(ixf.ixf_fetch.FetchError, match="took too long"):
        importer.sanitize({"member_list": [member]}, deadline=time.monotonic() + 0.1)


def test_member_dedupe_keeps_feed_order():
    members = [{"asnum": n} for n in (3, 1, 3, 2, 1)]
    data = ixf.Importer().sanitize({"member_list": members})
    assert [m["asnum"] for m in data["member_list"]] == [3, 1, 2]


def test_count_entries():
    data = {
        "member_list": [
            {
                "asnum": 1,
                "connection_list": [
                    {"if_list": [{}, {}], "vlan_list": [{}, {}, {}]},
                    {"vlan_list": "odd"},
                ],
            },
            {"asnum": 2, "connection_list": None},
            "not a member",
        ]
    }
    # 3 members, 2 connections, 3 vlans, 2 interfaces
    assert ixf.count_entries(data, 100) == 10
    assert ixf.count_entries({"member_list": 5}, 100) == 0


def test_count_entries_stops_past_limit():
    data = {"member_list": [{"asnum": n} for n in range(100000)]}
    assert ixf.count_entries(data, 10) == 11


def test_entry_limit_refuses_import_before_parse(ixlan, settings, monkeypatch):
    settings.IXF_MAX_ENTRIES = 5
    parse = mock.Mock()
    monkeypatch.setattr(ixf.Importer, "parse", parse)
    data = {"member_list": [{"asnum": n} for n in range(1, 7)]}

    assert ixf.Importer().update(ixlan, save=True, data=data) is False

    parse.assert_not_called()
    ixlan.refresh_from_db()
    assert ixlan.ixf_ixp_import_error == "Error: IX-F data has more than 5 entries"


def test_entry_limit_allows_feed_at_limit(ixlan, settings, monkeypatch):
    settings.IXF_MAX_ENTRIES = 6
    parse = mock.Mock()
    monkeypatch.setattr(ixf.Importer, "parse", parse)
    data = {"member_list": [{"asnum": n} for n in range(1, 7)]}

    ixf.Importer().update(ixlan, save=False, data=data)

    parse.assert_called_once()


def test_defaults(settings):
    from django.conf import settings as dj_settings

    assert dj_settings.IXF_FETCH_MAX_BYTES == 10 * 1024 * 1024
    assert dj_settings.IXF_MAX_ENTRIES == 50000
    assert dj_settings.IXF_MAX_SNAPSHOT_BYTES == 64 * 1024 * 1024


def snapshot_member(asn, vlans, size):
    return {
        "asnum": asn,
        "name": "x" * size,
        "connection_list": [
            {
                "state": "active",
                "vlan_list": [
                    {"vlan_id": 0, "ipv4": {"address": f"195.69.144.{i + 1}"}}
                    for i in range(vlans)
                ],
            }
        ],
    }


def test_snapshot_bytes():
    one = snapshot_member(1, 3, 100)
    two = snapshot_member(2, 1, 50)
    data = {"member_list": [one, two, {"asnum": 3}, "not a member"]}
    expected = 3 * len(ixf.encode_member_data(one))
    expected += len(ixf.encode_member_data(two))
    assert ixf.snapshot_bytes(data, 10**9) == expected
    assert ixf.snapshot_bytes({"member_list": 5}, 100) == 0


def test_snapshot_bytes_stops_past_limit():
    data = {"member_list": [snapshot_member(n, 1, 10) for n in range(1, 100000)]}
    size = len(ixf.encode_member_data(data["member_list"][0]))
    with mock.patch.object(ixf, "encode_member_data", wraps=ixf.encode_member_data):
        assert ixf.snapshot_bytes(data, size * 2) == size * 3
        assert ixf.encode_member_data.call_count == 3


def test_snapshot_budget_refuses_import_before_parse(ixlan, settings, monkeypatch):
    settings.IXF_MAX_SNAPSHOT_BYTES = 1024 * 1024
    parse = mock.Mock()
    monkeypatch.setattr(ixf.Importer, "parse", parse)
    # small export, but every vlan row would store the whole member
    data = {"member_list": [snapshot_member(64511, 3, 400000)]}

    assert ixf.Importer().update(ixlan, save=True, data=data) is False

    parse.assert_not_called()
    ixlan.refresh_from_db()
    assert ixlan.ixf_ixp_import_error == (
        "Error: IX-F member data repeated across its vlan entries is larger than "
        "1048576 bytes"
    )


def test_snapshot_budget_error_names_limits_under_one_mib(ixlan, settings, monkeypatch):
    settings.IXF_MAX_SNAPSHOT_BYTES = 1000
    monkeypatch.setattr(ixf.Importer, "parse", mock.Mock())
    data = {"member_list": [snapshot_member(64511, 3, 1000)]}

    assert ixf.Importer().update(ixlan, save=True, data=data) is False

    ixlan.refresh_from_db()
    assert ixlan.ixf_ixp_import_error.endswith("larger than 1000 bytes")


def test_snapshot_budget_allows_feed_at_limit(ixlan, settings, monkeypatch):
    parse = mock.Mock()
    monkeypatch.setattr(ixf.Importer, "parse", parse)
    data = {"member_list": [snapshot_member(64511, 3, 400000)]}
    settings.IXF_MAX_SNAPSHOT_BYTES = ixf.snapshot_bytes(data, 10**9)

    ixf.Importer().update(ixlan, save=False, data=data)

    parse.assert_called_once()


def test_asns_tracked_in_a_set_of_safe_values(ixlan):
    importer = ixf.Importer()
    importer.reset(ixlan=ixlan)
    importer.parse_members([{"asnum": 64500}, {"asnum": 64500}])
    assert importer.asns == {64500}


def test_member_data_matches_set_data_format():
    from peeringdb_server.models import IXFMemberData

    importer = ixf.Importer()
    importer._member_json = None
    member = {"asnum": 1, "name": "Example \u00e9", "connection_list": []}
    reference = IXFMemberData()
    reference.set_data(json.dumps(member))

    with mock.patch.object(ixf.json, "dumps", wraps=json.dumps) as dumps:
        first = importer.member_data(member)
        second = importer.member_data(member)

    assert first == reference.data
    assert first is second
    assert dumps.call_count == 2  # the row, then the stored string, once


@pytest.fixture
def wide_member(ixlan):
    from peeringdb_server.models import Network

    with reversion.create_revision():
        Network.objects.create(
            name="Wide Net",
            org=ixlan.ix.org,
            asn=64511,
            status="ok",
            allow_ixp_update=False,
            info_unicast=True,
            info_ipv6=False,
        )
    vlans = [
        {"vlan_id": 0, "ipv4": {"address": f"195.69.{144 + i // 250}.{i % 250 + 1}"}}
        for i in range(300)
    ]
    return {
        "asnum": 64511,
        "name": "x" * 20000,
        "connection_list": [
            {
                "state": "active",
                "if_list": [{"if_speed": "bad"}] * 50,
                "vlan_list": vlans,
            }
        ],
    }


def test_vlans_share_member_data_and_connection_errors(ixlan, wide_member):
    importer = ixf.Importer()
    importer.reset(ixlan=ixlan, save=False)
    importer.switch_map = {}

    with mock.patch.object(ixf.json, "dumps", wraps=json.dumps) as dumps:
        importer.parse_members([wide_member])

    datas = {id(m.data) for m in importer.pending_save}
    errors = {id(m.error) for m in importer.pending_save}
    assert len(importer.pending_save) == 300
    # one stored member string and one error string, shared by all vlans
    assert len(datas) == 1
    assert len(errors) == 1
    big = [c for c in dumps.call_args_list if c.args and c.args[0] is wide_member]
    assert len(big) == 1
    # stored format unchanged
    reference = ixf.IXFMemberData()
    reference.set_data(json.dumps(wide_member))
    assert importer.pending_save[0].data == reference.data
    assert json.loads(importer.pending_save[0].error)["speed"][0].startswith(
        "Invalid speed value"
    )


@pytest.mark.parametrize(
    "member,name",
    [
        ({"asnum": 1, "connection_list": "x" * 1000}, "connection_list"),
        ({"asnum": 1, "connection_list": [{"if_list": "x" * 300000}]}, "if_list"),
        ({"asnum": 1, "connection_list": [{"vlan_list": {"a": 1}}]}, "vlan_list"),
    ],
)
def test_non_list_containers_refused(monkeypatch, member, name):
    monkeypatch.setattr(
        ixf.ixf_fetch, "fetch_json", lambda url, **kwargs: {"member_list": [member]}
    )
    assert ixf.Importer().fetch("https://ixf.example/feed.json") == {
        "pdb_error": f"IX-F data has a non-list {name}"
    }


def test_null_containers_still_mean_not_set():
    member = {
        "asnum": 1,
        "connection_list": [{"vlan_list": None, "if_list": None}],
    }
    data = ixf.Importer().sanitize(
        {"member_list": [member, {"asnum": 2, "connection_list": None}]}
    )
    assert data["member_list"][0]["connection_list"] == [{}]
    assert "connection_list" not in data["member_list"][1]


def test_colliding_switch_and_facility_ids_stay_fast():
    importer = ixf.Importer()
    data = {
        "ixp_list": [
            {
                "switch": [
                    {"id": k * COLLIDING, "pdb_facility_id": 1} for k in range(1, 40001)
                ]
            }
        ]
    }
    start = time.monotonic()
    switch_map = importer.build_switch_map(data)
    importer.reset()
    importer.parse_facility_id(
        [{"pdb_facility_id": k * COLLIDING} for k in range(1, 40001)], switch_map
    )
    assert time.monotonic() - start < 1
    assert switch_map == {}


def test_switch_map_keeps_valid_ids():
    importer = ixf.Importer()
    data = {"ixp_list": [{"switch": [{"id": 3, "pdb_facility_id": 7}, {"id": "s1"}]}]}
    switch_map = importer.build_switch_map(data)
    assert sorted(map(str, switch_map)) == ["3", "s1"]
    importer.reset()
    assert importer.parse_facility_id([{"switch_id": 3}], switch_map) == 7


def ixf_member_updates(queries):
    return [
        q["sql"]
        for q in queries
        if q["sql"].startswith("UPDATE") and "peeringdb_ixf_member_data" in q["sql"]
    ]


def test_import_stores_snapshots_and_reimport_only_touches_fetched(ixlan, wide_member):
    member = snapshot_member(64511, 3, 1000)
    reference = ixf.IXFMemberData()
    reference.set_data(json.dumps(member))

    assert ixf.Importer().update(ixlan, save=True, data={"member_list": [member]})

    rows = list(ixf.IXFMemberData.objects.filter(asn=64511).order_by("ipaddr4"))
    assert len(rows) == 3
    assert all(row.data == reference.data for row in rows)
    stamps = {row.id: (row.fetched, row.updated) for row in rows}

    # a preview of changed data and a saved re-import of the same data
    changed = snapshot_member(64511, 3, 2000)
    for save, data in ((False, changed), (True, member)):
        with CaptureQueriesContext(connection) as ctx:
            ixf.Importer().update(ixlan, save=save, data={"member_list": [data]})

        updates = ixf_member_updates(ctx.captured_queries)
        assert len(updates) == 3
        assert all("`fetched`" in sql and "`data`" not in sql for sql in updates)

        for row in ixf.IXFMemberData.objects.filter(asn=64511):
            assert row.data == reference.data
            assert row.fetched > stamps[row.id][0]
            assert row.updated == stamps[row.id][1]
            stamps[row.id] = (row.fetched, row.updated)
