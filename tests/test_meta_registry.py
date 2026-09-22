"""
Tests for the object metadata key registry (#1751) and the netixlan
status/operational model (#1742).
"""

import datetime

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.test import override_settings
from rest_framework.exceptions import ValidationError as RestValidationError
from rest_framework.test import APIClient

from peeringdb_server import meta_registry
from peeringdb_server.models import (
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
)
from peeringdb_server.serializers import NetworkIXLanSerializer, NetworkSerializer
from peeringdb_server.validators import validate_status

# even pure-function tests need db access here: the autouse cleanup
# fixture clears the geo DatabaseCache, which hits the database
pytestmark = pytest.mark.django_db


def tomorrow():
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


# --- registry: key catalog ---------------------------------------------------


def test_launch_key_catalog():
    assert set(meta_registry.keys_for_tag("netixlan")) == {
        "planned_status_change",
        "rfc8950",
    }
    assert set(meta_registry.keys_for_tag("net")) == {
        "preferred_ip_mtu",
        "rtbh_community",
    }


def test_filterable_keys_declare_columns():
    assert meta_registry.filter_column_map("netixlan") == {
        "meta__planned_status_change__status": "meta_planned_status_change_status",
        "meta__planned_status_change__date": "meta_planned_status_change_date",
        "meta__rfc8950": "meta_rfc8950",
    }
    # launch net keys are not filterable
    assert meta_registry.filter_column_map("net") == {}


def test_generated_columns_injected():
    netixlan_fields = {f.name for f in NetworkIXLan._meta.get_fields()}
    assert "meta_planned_status_change_status" in netixlan_fields
    assert "meta_planned_status_change_date" in netixlan_fields
    assert "meta_rfc8950" in netixlan_fields

    net_fields = {f.name for f in Network._meta.get_fields()}
    assert not any(f.startswith("meta_") for f in net_fields if f != "meta")


def test_drift_check_clean():
    assert meta_registry.check_meta_registry(None) == []


# --- registry: validation ----------------------------------------------------


def test_validate_meta_unregistered_key_rejected():
    with pytest.raises(RestValidationError) as exc:
        meta_registry.validate_meta("netixlan", {"free_form": 1})
    assert "unregistered" in str(exc.value.detail["meta"]["free_form"])


def test_validate_meta_wrong_object_type_rejected():
    # rtbh_community is registered on net, not netixlan
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta("netixlan", {"rtbh_community": "65000:666"})


def test_validate_meta_none_and_empty():
    assert meta_registry.validate_meta("netixlan", None) == {}
    assert meta_registry.validate_meta("netixlan", {}) == {}
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta("netixlan", "not-a-dict")


def test_planned_status_change_valid():
    normalized = meta_registry.validate_meta(
        "netixlan",
        {"planned_status_change": {"status": "deleted", "date": tomorrow()}},
    )
    assert normalized == {
        "planned_status_change": {"status": "deleted", "date": tomorrow()}
    }


@pytest.mark.parametrize(
    "value",
    [
        # not a target status value
        {"status": "pending", "date": "2030-01-01"},
        # past date
        {"status": "deleted", "date": "2020-01-01"},
        # missing parts
        {"status": "deleted"},
        {"date": "2030-01-01"},
        # extra keys are forbidden (nothing may be smuggled in)
        {"status": "deleted", "date": "2030-01-01", "note": "bye"},
    ],
)
def test_planned_status_change_invalid(value):
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta("netixlan", {"planned_status_change": value})


@override_settings(META_PLANNED_STATUS_CHANGE_WINDOW_DAYS=30)
def test_planned_status_change_window_is_a_deployment_setting():
    too_far = (datetime.date.today() + datetime.timedelta(days=31)).isoformat()
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta(
            "netixlan",
            {"planned_status_change": {"status": "deleted", "date": too_far}},
        )


def test_rfc8950_strict_boolean():
    assert meta_registry.validate_meta("netixlan", {"rfc8950": True}) == {
        "rfc8950": True
    }
    for bad in ("true", 1, "yes", None):
        with pytest.raises(RestValidationError):
            meta_registry.validate_meta("netixlan", {"rfc8950": bad})


def test_preferred_ip_mtu_bounds():
    assert meta_registry.validate_meta("net", {"preferred_ip_mtu": 9000}) == {
        "preferred_ip_mtu": 9000
    }
    for bad in (100, 100000, "9000", 1500.5):
        with pytest.raises(RestValidationError):
            meta_registry.validate_meta("net", {"preferred_ip_mtu": bad})


@override_settings(META_PREFERRED_IP_MTU_MAX=9216)
def test_preferred_ip_mtu_bounds_are_deployment_settings():
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta("net", {"preferred_ip_mtu": 9217})


@pytest.mark.parametrize("value", ["65000:666", "4200000000:1:2", " 65000:666 "])
def test_rtbh_community_valid(value):
    normalized = meta_registry.validate_meta("net", {"rtbh_community": value})
    assert normalized["rtbh_community"] == value.strip()


@pytest.mark.parametrize(
    "value",
    [
        "65000",  # no separator
        "65000:70000",  # part exceeds 16 bit in standard form
        "1:2:3:4",  # too many parts
        "4294967296:1:2",  # part exceeds 32 bit in large form
        "asn:666",  # not numeric
        65000,  # not a string
    ],
)
def test_rtbh_community_invalid(value):
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta("net", {"rtbh_community": value})


# --- #1742: status vocabulary ------------------------------------------------


def test_validate_status_not_operational_netixlan_only():
    assert validate_status("not-operational", tag="netixlan") == "not-operational"
    for tag in ("net", "ix", "fac", None):
        with pytest.raises(RestValidationError):
            validate_status("not-operational", tag=tag)
    # lifecycle values remain valid everywhere
    for value in ("ok", "pending", "deleted"):
        assert validate_status(value, tag="netixlan") == value


@pytest.mark.django_db
def test_operational_write_maps_to_status_on_full_put():
    # #1742 deprecation window: an old client doing a full-object PUT echoes
    # the current status back unchanged -- that echo must not suppress the
    # operational -> status mapping, or the client's operational write is
    # silently lost. An explicitly *changed* status wins over operational.
    org = Organization.objects.create(name="Echo Test Org", status="ok")
    net = Network.objects.create(name="Echo Test Net", asn=63312, org=org, status="ok")
    # a netixlan write requires a contactable poc on the network (#826)
    NetworkContact.objects.create(
        network=net,
        role="Technical",
        visible="Public",
        email="echo@localhost",
        status="ok",
    )
    ix = InternetExchange.objects.create(name="Echo Test IX", org=org, status="ok")
    IXLanPrefix.objects.create(
        ixlan=ix.ixlan, protocol="IPv4", prefix="195.69.144.0/22", status="ok"
    )
    netixlan = NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="ok",
        ipaddr4="195.69.147.251",
    )

    def run(data):
        serializer = NetworkIXLanSerializer(instance=netixlan, data=data)
        serializer.is_valid()
        return serializer

    base = {
        "net_id": net.id,
        "ixlan_id": ix.ixlan.id,
        "asn": net.asn,
        "speed": 1000,
        "ipaddr4": "195.69.147.251",
        "ipaddr6": "",
    }

    # echoed unchanged status + operational=False -> mapped to not-operational
    serializer = run(dict(base, status="ok", operational=False))
    assert serializer.validated_data["status"] == "not-operational"

    # operational alone -> mapped
    serializer = run(dict(base, operational=False))
    assert serializer.validated_data["status"] == "not-operational"

    # explicitly changed status wins over a conflicting operational
    netixlan.status = "not-operational"
    netixlan.save()
    serializer = run(dict(base, status="ok", operational=False))
    assert serializer.validated_data["status"] == "ok"


@pytest.mark.django_db
def test_netixlan_operational_derived_from_status():
    # operational is recomputed from status on every save
    org = Organization.objects.create(name="Meta Test Org", status="ok")
    net = Network.objects.create(name="Meta Test Net", asn=63311, org=org, status="ok")
    ix = InternetExchange.objects.create(name="Meta Test IX", org=org, status="ok")

    netixlan = NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="not-operational",
        operational=True,  # writer-supplied value is overridden by derivation
        ipaddr4="195.69.147.250",
    )
    netixlan.refresh_from_db()
    assert netixlan.operational is False

    netixlan.status = "ok"
    netixlan.save()
    netixlan.refresh_from_db()
    assert netixlan.operational is True


# --- validation boundaries -----------------------------------------------------


def test_planned_status_change_window_boundaries():
    # today is rejected ("future" is strict); the exact window edge is accepted
    today = datetime.date.today().isoformat()
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta(
            "netixlan", {"planned_status_change": {"status": "deleted", "date": today}}
        )

    edge = (
        datetime.date.today()
        + datetime.timedelta(days=settings.META_PLANNED_STATUS_CHANGE_WINDOW_DAYS)
    ).isoformat()
    normalized = meta_registry.validate_meta(
        "netixlan", {"planned_status_change": {"status": "deleted", "date": edge}}
    )
    assert normalized["planned_status_change"]["date"] == edge


def test_preferred_ip_mtu_exact_bounds_accepted():
    for value in (
        settings.META_PREFERRED_IP_MTU_MIN,
        settings.META_PREFERRED_IP_MTU_MAX,
    ):
        assert meta_registry.validate_meta("net", {"preferred_ip_mtu": value}) == {
            "preferred_ip_mtu": value
        }


def test_rtbh_community_exact_bounds():
    # largest representable values in each form are accepted
    assert meta_registry.validate_meta("net", {"rtbh_community": "65535:65535"})
    assert meta_registry.validate_meta("net", {"rtbh_community": "4294967295:0:0"})
    # one past the boundary is rejected
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta("net", {"rtbh_community": "65536:0"})


def test_validate_meta_multiple_keys_and_error_aggregation():
    # a valid and an invalid key in one document: the whole write is rejected
    # and the error names the failing key
    with pytest.raises(RestValidationError) as exc:
        meta_registry.validate_meta(
            "netixlan",
            {"rfc8950": True, "planned_status_change": {"status": "bogus"}},
        )
    assert "planned_status_change" in exc.value.detail["meta"]
    assert "rfc8950" not in exc.value.detail["meta"]


# --- drift check negative paths ------------------------------------------------


def test_drift_check_detects_missing_column():
    # a registered filterable key whose column is absent from the model -> E101
    meta_registry.REGISTRY["bogus_key"] = meta_registry.MetaKey(
        name="bogus_key",
        tags=("netixlan",),
        adapter=meta_registry._FunctionAdapter(bool),
        columns=(
            meta_registry.GeneratedColumn(
                name="meta_bogus_key",
                json_path=("bogus_key",),
                output_field=models.BooleanField,
                output_field_kwargs={"null": True},
            ),
        ),
    )
    try:
        errors = meta_registry.check_meta_registry(None)
        assert any(e.id == "peeringdb_server.E101" for e in errors)
    finally:
        del meta_registry.REGISTRY["bogus_key"]


def test_drift_check_detects_undeclared_column():
    # a model column no registered key declares (a retired key whose column
    # migration was forgotten) -> E102
    key = meta_registry.REGISTRY.pop("rfc8950")
    try:
        errors = meta_registry.check_meta_registry(None)
        assert any(
            e.id == "peeringdb_server.E102" and "meta_rfc8950" in e.msg for e in errors
        )
    finally:
        meta_registry.REGISTRY["rfc8950"] = key


# --- serializer round-trips ------------------------------------------------------


def test_network_serializer_meta_roundtrip():
    org = Organization.objects.create(name="Meta RT Org", status="ok")
    serializer = NetworkSerializer()
    # the shared validate() also enforces website presence -- satisfy it so
    # only the meta behavior is under test
    base = {"org": org, "website": "https://example.com"}

    # valid document is normalized and passed through
    data = serializer.validate(
        dict(base, meta={"preferred_ip_mtu": 9000, "rtbh_community": " 65000:666 "})
    )
    assert data["meta"] == {
        "preferred_ip_mtu": 9000,
        "rtbh_community": "65000:666",
    }

    # unregistered key rejected
    with pytest.raises(RestValidationError):
        serializer.validate(dict(base, meta={"free_form": 1}))

    # a netixlan-only key is unregistered on net
    with pytest.raises(RestValidationError):
        serializer.validate(dict(base, meta={"rfc8950": True}))

    # absent meta passes through untouched
    assert "meta" not in serializer.validate(dict(base))


@pytest.mark.django_db
def test_netixlan_serializer_meta_replace_semantics(netixlan_write_fixture):
    # meta is a whole-document field: a write replaces the document, it does
    # not merge -- a key omitted from the payload is cleared
    net, ix, netixlan = netixlan_write_fixture
    netixlan.meta = {"rfc8950": True}
    netixlan.save()

    base = {
        "net_id": net.id,
        "ixlan_id": ix.ixlan.id,
        "asn": net.asn,
        "speed": 1000,
        "ipaddr4": str(netixlan.ipaddr4),
        "ipaddr6": "",
    }
    plan = {"status": "deleted", "date": tomorrow()}

    serializer = NetworkIXLanSerializer(
        instance=netixlan, data=dict(base, meta={"planned_status_change": plan})
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"] == {"planned_status_change": plan}
    assert "rfc8950" not in serializer.validated_data["meta"]

    # unregistered key rejected at the netixlan endpoint too
    serializer = NetworkIXLanSerializer(
        instance=netixlan, data=dict(base, meta={"nonsense": 1})
    )
    assert not serializer.is_valid()
    assert "meta" in serializer.errors


@pytest.fixture
def netixlan_write_fixture(db):
    org = Organization.objects.create(name="Meta W Org", status="ok")
    net = Network.objects.create(name="Meta W Net", asn=63313, org=org, status="ok")
    NetworkContact.objects.create(
        network=net,
        role="Technical",
        visible="Public",
        email="metaw@localhost",
        status="ok",
    )
    ix = InternetExchange.objects.create(name="Meta W IX", org=org, status="ok")
    IXLanPrefix.objects.create(
        ixlan=ix.ixlan, protocol="IPv4", prefix="195.69.144.0/22", status="ok"
    )
    netixlan = NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="ok",
        ipaddr4="195.69.147.240",
    )
    return net, ix, netixlan


# --- generated columns: database behavior ----------------------------------------


@pytest.mark.django_db
def test_generated_columns_track_meta_document(netixlan_write_fixture):
    # the typed columns are derived by the database and follow every write to
    # the document; an absent key yields NULL, a cleared document clears them
    _, _, netixlan = netixlan_write_fixture

    plan_date = datetime.date.today() + datetime.timedelta(days=30)
    netixlan.meta = {
        "planned_status_change": {
            "status": "deleted",
            "date": plan_date.isoformat(),
        },
        "rfc8950": True,
    }
    netixlan.save()
    netixlan.refresh_from_db()
    assert netixlan.meta_planned_status_change_status == "deleted"
    # typed as a real date, not a string
    assert netixlan.meta_planned_status_change_date == plan_date
    assert netixlan.meta_rfc8950 is True

    # rfc8950 false is FALSE, not NULL (present-but-false is distinguishable
    # from absent)
    netixlan.meta = {"rfc8950": False}
    netixlan.save()
    netixlan.refresh_from_db()
    assert netixlan.meta_rfc8950 is False
    assert netixlan.meta_planned_status_change_status is None
    assert netixlan.meta_planned_status_change_date is None

    # empty document -> all NULL
    netixlan.meta = {}
    netixlan.save()
    netixlan.refresh_from_db()
    assert netixlan.meta_rfc8950 is None


# --- meta__ filtering end to end ---------------------------------------------------


@pytest.fixture
def meta_filter_setup(db):

    # a bare test db has no guest permission groups seeded -- authenticate as
    # superuser (bypasses grainy) so the filter behavior itself is what's tested
    superuser = get_user_model().objects.create_user(
        "meta_filter_admin", "meta_filter_admin@localhost", "admin"
    )
    superuser.is_superuser = True
    superuser.save()
    client = APIClient()
    client.force_authenticate(superuser)

    org = Organization.objects.create(name="Meta F Org", status="ok")
    ix = InternetExchange.objects.create(name="Meta F IX", org=org, status="ok")
    IXLanPrefix.objects.create(
        ixlan=ix.ixlan, protocol="IPv4", prefix="195.69.144.0/22", status="ok"
    )

    def make(asn, ip, status="ok", meta=None):
        net = Network.objects.create(
            name=f"Meta F Net {asn}", asn=asn, org=org, status="ok"
        )
        return NetworkIXLan.objects.create(
            network=net,
            ixlan=ix.ixlan,
            asn=asn,
            speed=1000,
            status=status,
            ipaddr4=ip,
            meta=meta or {},
        )

    today = datetime.date.today()
    leaving = make(
        63401,
        "195.69.147.1",
        meta={
            "planned_status_change": {
                "status": "deleted",
                "date": (today + datetime.timedelta(days=30)).isoformat(),
            },
            "rfc8950": True,
        },
    )
    arriving = make(
        63402,
        "195.69.147.2",
        status="not-operational",
        meta={
            "planned_status_change": {
                "status": "ok",
                "date": (today + datetime.timedelta(days=10)).isoformat(),
            }
        },
    )
    plain = make(63403, "195.69.147.3")
    # explicitly declared NOT supporting rfc8950 -- distinct from `plain`,
    # which never declared
    declined = make(63404, "195.69.147.4", meta={"rfc8950": False})

    return client, ix, leaving, arriving, plain, declined


def _ids(response):
    assert response.status_code == 200, response.content
    return {row["id"] for row in response.json()["data"]}


@pytest.mark.django_db
def test_meta_filter_by_planned_status(meta_filter_setup):
    client, ix, leaving, arriving, plain, declined = meta_filter_setup

    ids = _ids(client.get("/api/netixlan?meta__planned_status_change__status=deleted"))
    assert leaving.id in ids
    assert arriving.id not in ids
    assert plain.id not in ids


@pytest.mark.django_db
def test_meta_filter_date_comparison_is_typed(meta_filter_setup):
    # date operators compare as dates through the typed generated column --
    # rows without the key (NULL) never match
    client, ix, leaving, arriving, plain, declined = meta_filter_setup
    cutoff = (datetime.date.today() + datetime.timedelta(days=20)).isoformat()

    ids = _ids(
        client.get(f"/api/netixlan?meta__planned_status_change__date__lt={cutoff}")
    )
    assert arriving.id in ids  # +10d < +20d
    assert leaving.id not in ids  # +30d
    assert plain.id not in ids  # no plan -> NULL

    ids = _ids(
        client.get(f"/api/netixlan?meta__planned_status_change__date__gt={cutoff}")
    )
    assert leaving.id in ids
    assert arriving.id not in ids


@pytest.mark.django_db
def test_meta_filter_rfc8950(meta_filter_setup):
    client, ix, leaving, arriving, plain, declined = meta_filter_setup

    ids = _ids(client.get("/api/netixlan?meta__rfc8950=true"))
    assert leaving.id in ids
    assert arriving.id not in ids
    assert plain.id not in ids
    assert declined.id not in ids


@pytest.mark.django_db
def test_meta_filter_rfc8950_false_excludes_never_declared(meta_filter_setup):
    """
    `?meta__rfc8950=false` must return only connections explicitly marked as
    not supporting it -- the promise object_metadata.md makes, and the whole
    reason the key gets a boolean generated column rather than being derived
    in Python.

    This rests entirely on MySQL propagating NULL through
    `JSON_EXTRACT(meta,'$."rfc8950"') = JSON_EXTRACT('true','$')` for an
    absent key. Nothing in Python would catch a change to that expression
    that made an absent key compare as 0.
    """
    client, ix, leaving, arriving, plain, declined = meta_filter_setup

    ids = _ids(client.get("/api/netixlan?meta__rfc8950=false"))
    assert declined.id in ids
    assert plain.id not in ids  # never declared -> NULL, not false
    assert arriving.id not in ids
    assert leaving.id not in ids


@pytest.mark.django_db
def test_meta_filter_headline_query(meta_filter_setup):
    # the spec's headline query: "who is leaving IX <id> in the next 90 days?"
    client, ix, leaving, arriving, plain, declined = meta_filter_setup
    horizon = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()

    ids = _ids(
        client.get(
            f"/api/netixlan?ix_id={ix.id}"
            f"&meta__planned_status_change__status=deleted"
            f"&meta__planned_status_change__date__lt={horizon}"
        )
    )
    assert ids == {leaving.id}


@pytest.mark.django_db
def test_meta_appears_in_api_output(meta_filter_setup):
    client, ix, leaving, arriving, plain, declined = meta_filter_setup

    response = client.get(f"/api/netixlan/{leaving.id}")
    assert response.status_code == 200
    row = response.json()["data"][0]
    assert row["meta"]["rfc8950"] is True
    assert row["meta"]["planned_status_change"]["status"] == "deleted"
    # not-operational rows are publicly visible with derived operational=False
    response = client.get(f"/api/netixlan/{arriving.id}")
    row = response.json()["data"][0]
    assert row["status"] == "not-operational"
    assert row["operational"] is False


# --- #1978: rtbh_community value rules ---------------------------------------


@pytest.mark.parametrize("value", ["٦٥:٦", "６５:６"])
def test_rtbh_community_rejects_non_ascii_digits(value):
    # `\d` matches non-ASCII decimal digits and int() parses them, so a
    # Unicode-digit community would otherwise validate, pass the numeric
    # bounds check, and be stored verbatim -- unusable to the router config
    # generators this key exists to feed
    with pytest.raises(RestValidationError):
        meta_registry.validate_meta("net", {"rtbh_community": value})


@pytest.mark.parametrize(
    "value,expected",
    [
        ("065000:0666", "65000:666"),
        ("00065000:666", "65000:666"),
        ("0065000:0001:0002", "65000:1:2"),
        ("65000:666", "65000:666"),
        ("0:0", "0:0"),
    ],
)
def test_rtbh_community_is_stored_canonically(value, expected):
    # the key is not filterable, so consumers compare these strings
    # client-side -- two spellings of one community must not survive
    normalized = meta_registry.validate_meta("net", {"rtbh_community": value})
    assert normalized["rtbh_community"] == expected


# --- #1742: live-status coverage for netixlan consumers ----------------------


def test_ix_net_count_includes_not_operational(netixlan_write_fixture):
    # net_count on the ix and ix_count on the net are maintained by the same
    # function; both have to agree with what the API actually returns
    from peeringdb_server.signals import update_counts_for_netixlan

    net, ix, netixlan = netixlan_write_fixture
    netixlan.status = "not-operational"
    netixlan.save()

    update_counts_for_netixlan(netixlan)

    ix.refresh_from_db()
    net.refresh_from_db()
    assert ix.net_count == 1
    assert net.ix_count == 1


def test_cross_lan_duplicate_ip_guard_sees_not_operational(netixlan_write_fixture):
    # a not-operational netixlan still holds its addresses, so claiming one
    # of them from another lan has to be refused
    net, ix, netixlan = netixlan_write_fixture
    netixlan.status = "not-operational"
    netixlan.save()

    other_ix = InternetExchange.objects.create(
        name="Meta W IX 2", org=net.org, status="ok"
    )
    # a distinct prefix string (unique key) that still covers the address,
    # created via objects.create so prefix-overlap validation -- which is a
    # full_clean() check -- does not reject the overlap this test needs
    IXLanPrefix.objects.create(
        ixlan=other_ix.ixlan, protocol="IPv4", prefix="195.69.144.0/21", status="ok"
    )

    claim = NetworkIXLan(
        network=net,
        ixlan=other_ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="ok",
        ipaddr4=netixlan.ipaddr4,
    )

    with pytest.raises(DjangoValidationError) as excinfo:
        other_ix.ixlan.add_netixlan(claim)

    assert "ipaddr4" in excinfo.value.message_dict


def test_put_echoing_current_status_is_accepted(netixlan_write_fixture):
    # status was read-only before #1742, so a full-object PUT that
    # round-trips a netixlan's own status must not start failing on a value
    # the client never asked to change
    net, ix, netixlan = netixlan_write_fixture
    NetworkIXLan.objects.filter(id=netixlan.id).update(status="pending")
    netixlan.refresh_from_db()

    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data={
            "net_id": net.id,
            "ixlan_id": ix.ixlan.id,
            "asn": net.asn,
            "speed": 1000,
            "ipaddr4": str(netixlan.ipaddr4),
            "ipaddr6": "",
            "status": "pending",
        },
    )
    assert serializer.is_valid(), serializer.errors

    # a lifecycle status the client actually tries to change is still refused
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data={
            "net_id": net.id,
            "ixlan_id": ix.ixlan.id,
            "asn": net.asn,
            "speed": 1000,
            "ipaddr4": str(netixlan.ipaddr4),
            "ipaddr6": "",
            "status": "deleted",
        },
    )
    assert not serializer.is_valid()
    assert "status" in serializer.errors


# --- writer_check: per-key write gate --------------------------------------


@pytest.fixture
def gated_key():
    """
    Register a temporary key with a writer_check, and remove it again --
    REGISTRY is module state shared by every test in the session.
    """
    from pydantic import StrictStr

    def staff_only(request):
        return bool(request and getattr(request.user, "is_staff", False))

    key = meta_registry.MetaKey(
        name="test_gated_key",
        tags=("net",),
        adapter=meta_registry._FunctionAdapter(StrictStr),
        writer_check=staff_only,
    )
    meta_registry.register(key)
    try:
        yield key
    finally:
        del meta_registry.REGISTRY[key.name]


class _FakeRequest:
    def __init__(self, is_staff):
        self.user = type("U", (), {"is_staff": is_staff})()


def test_writer_check_allows_permitted_request(gated_key):
    normalized = meta_registry.validate_meta(
        "net", {"test_gated_key": "x"}, request=_FakeRequest(is_staff=True)
    )
    assert normalized == {"test_gated_key": "x"}


def test_writer_check_denies_rejected_request(gated_key):
    with pytest.raises(RestValidationError) as excinfo:
        meta_registry.validate_meta(
            "net", {"test_gated_key": "x"}, request=_FakeRequest(is_staff=False)
        )
    assert "test_gated_key" in excinfo.value.detail["meta"]


def test_writer_check_denies_when_there_is_no_request(gated_key):
    # a permission gate with no identifiable actor denies -- a missing
    # request is not an internal-write escape hatch. Code that must set a
    # gated key outside a request writes the model field directly.
    with pytest.raises(RestValidationError) as excinfo:
        meta_registry.validate_meta("net", {"test_gated_key": "x"}, request=None)
    assert "test_gated_key" in excinfo.value.detail["meta"]


def test_writer_check_exempts_a_value_the_caller_only_round_tripped(gated_key):
    # every write path re-submits the whole document, so a gated key whose
    # value is unchanged is not being set. Gating it would make an object
    # carrying an already-set gated key uneditable by anyone who fails the
    # gate -- not merely unwritable for that one key.
    normalized = meta_registry.validate_meta(
        "net",
        {"test_gated_key": "x"},
        request=_FakeRequest(is_staff=False),
        current={"test_gated_key": "x"},
    )
    assert normalized == {"test_gated_key": "x"}


def test_writer_check_still_denies_a_changed_value(gated_key):
    with pytest.raises(RestValidationError) as excinfo:
        meta_registry.validate_meta(
            "net",
            {"test_gated_key": "y"},
            request=_FakeRequest(is_staff=False),
            current={"test_gated_key": "x"},
        )
    assert "test_gated_key" in excinfo.value.detail["meta"]


def test_writer_check_absent_leaves_key_ungated():
    # the launch keys declare no writer_check, so a no-request write is fine
    assert meta_registry.REGISTRY["rtbh_community"].writer_check is None
    normalized = meta_registry.validate_meta(
        "net", {"rtbh_community": "65000:666"}, request=None
    )
    assert normalized == {"rtbh_community": "65000:666"}


# --- write-time bounds vs. structural validity -------------------------------


@pytest.mark.django_db
def test_expired_plan_does_not_block_unrelated_edits(netixlan_write_fixture):
    """
    A plan whose date has passed must not lock the object.

    The future-date bound is a write-time bound. Every write path resubmits
    the whole document -- the dashboard exports every field in a netixlan row
    once any one of them changes, and a full-object PUT round-trips `meta`
    because `meta` is the read surface -- so re-applying the bound to an
    unchanged value would refuse every later edit of the row. The window is
    finite, so every plan eventually reaches that state.
    """
    net, ix, netixlan = netixlan_write_fixture
    past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    plan = {"status": "deleted", "date": past}
    # written directly: setting this through the API is what the bound stops
    NetworkIXLan.objects.filter(id=netixlan.id).update(
        meta={"planned_status_change": plan}
    )
    netixlan.refresh_from_db()

    base = {
        "net_id": net.id,
        "ixlan_id": ix.ixlan.id,
        "asn": net.asn,
        "ipaddr4": str(netixlan.ipaddr4),
        "ipaddr6": "",
    }

    # editing an unrelated field, resubmitting the plan as every client does
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=dict(base, speed=10000, meta={"planned_status_change": plan}),
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"] == {"planned_status_change": plan}

    # ... and the same through the flat fields the dashboard submits
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=dict(
            base,
            speed=10000,
            planned_status_change_status="deleted",
            planned_status_change_date=past,
        ),
    )
    assert serializer.is_valid(), serializer.errors

    # but actually setting a past date is still refused
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=dict(
            base,
            speed=10000,
            meta={"planned_status_change": {"status": "ok", "date": past}},
        ),
    )
    assert not serializer.is_valid()
    assert "meta" in serializer.errors

    # and the plan can always be cleared
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=dict(
            base,
            speed=10000,
            planned_status_change_status="",
            planned_status_change_date="",
        ),
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"] == {}


@pytest.mark.django_db
def test_full_clean_validates_the_registry(netixlan_write_fixture):
    """
    `meta` is an editable JSONField, so the Django admin renders it as a
    free-text JSON textarea -- a write path with no serializer on it. Without
    a model-level hook "registered keys only" would not hold there, and a
    malformed planned-change date would reach MySQL as a STORED generated
    column expression and surface as OperationalError (1292) -- a 500, not a
    form error.
    """
    _, _, netixlan = netixlan_write_fixture

    netixlan.meta = {"something_i_invented": True}
    with pytest.raises(DjangoValidationError) as excinfo:
        netixlan.full_clean()
    assert "meta" in excinfo.value.message_dict

    for bad_date in ("not-a-date", "2026-02-31"):
        netixlan.meta = {"planned_status_change": {"status": "ok", "date": bad_date}}
        with pytest.raises(DjangoValidationError) as excinfo:
            netixlan.full_clean()
        assert "meta" in excinfo.value.message_dict, bad_date

    # a netixlan-only key is unregistered on net
    netixlan.network.meta = {"rfc8950": True}
    with pytest.raises(DjangoValidationError) as excinfo:
        netixlan.network.full_clean()
    assert "meta" in excinfo.value.message_dict

    # values are normalized on the way through, as irr_as_set already is
    netixlan.network.meta = {"rtbh_community": " 065000:0666 "}
    netixlan.network.full_clean()
    assert netixlan.network.meta == {"rtbh_community": "65000:666"}


@pytest.mark.django_db
def test_full_clean_does_not_apply_write_time_bounds(netixlan_write_fixture):
    # the importer calls full_clean() on every netixlan it saves; a stored
    # plan whose date has passed must not make those saves fail
    _, _, netixlan = netixlan_write_fixture
    past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    netixlan.meta = {"planned_status_change": {"status": "deleted", "date": past}}
    netixlan.full_clean()
    netixlan.save()


@pytest.mark.django_db
def test_operational_write_cannot_publish_a_pending_netixlan(netixlan_write_fixture):
    """
    The `operational` -> `status` deprecation shim must not reopen what
    #1562 closed by making `status` read-only: a user with write permission
    moving their own pending connection into a publicly visible status.

    Pending netixlans are reachable on this endpoint -- rest.py's
    single-object queryset is the live statuses plus "pending".
    """
    net, ix, netixlan = netixlan_write_fixture
    NetworkIXLan.objects.filter(id=netixlan.id).update(status="pending")
    netixlan.refresh_from_db()

    base = {
        "net_id": net.id,
        "ixlan_id": ix.ixlan.id,
        "asn": net.asn,
        "speed": 1000,
        "ipaddr4": str(netixlan.ipaddr4),
        "ipaddr6": "",
    }

    # the standard full-object PUT round-trip: status echoed back unchanged
    serializer = NetworkIXLanSerializer(
        instance=netixlan, data=dict(base, status="pending", operational=True)
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["status"] == "pending"

    # and a PATCH-shaped payload that names only the deprecated boolean
    serializer = NetworkIXLanSerializer(
        instance=netixlan, data=dict(base, operational=False)
    )
    assert serializer.is_valid(), serializer.errors
    assert "status" not in serializer.validated_data

    # a live netixlan is still mapped, which is the point of the shim
    NetworkIXLan.objects.filter(id=netixlan.id).update(status="ok")
    netixlan.refresh_from_db()
    serializer = NetworkIXLanSerializer(
        instance=netixlan, data=dict(base, status="ok", operational=False)
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["status"] == "not-operational"
