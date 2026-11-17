"""
Unit tests for the IRR lookup service (peeringdb_server/irr.py, #1973).

The outbound socket is mocked at peeringdb_server.irr._send — return_value / a
text-returning side_effect for the answer paths, and an exception side_effect for
the fail-open (timeout/outage) paths, mirroring the RDAP / IX-F mocking
convention in the repo. No real network calls.
"""

import socket
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import override_settings

from peeringdb_server import irr
from peeringdb_server.validators import validate_irr_as_set

from .irr_fakes import (
    MIRROR,
    TWO_SERVERS,
    FakeCache,
    irrd_list,
    irrd_object,
    make_send,
)

pytestmark = pytest.mark.django_db


def _irr_reachable(host="rr.ntt.net", port=43, timeout=3):
    """True if the real IRR pool is reachable — gates the opt-in live test."""
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


class TestIrrLookup:
    @pytest.fixture(autouse=True)
    def _settings(self, settings):
        settings.IRR_LOOKUP_SERVERS = TWO_SERVERS
        settings.IRR_LOOKUP_CACHE_TTL = 300
        settings.IRR_LOOKUP_DEFAULT_TIMEOUT = 5

    def _patches(self, send):
        # patch the socket layer + swap in a fresh in-memory cache
        return (
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        )

    # --- object class inference ---------------------------------------------

    def test_object_class_inference(self):
        assert irr._object_class("AS-FOO") == "as-set"
        assert irr._object_class("AS64496") == "aut-num"
        assert irr._object_class("RS-BAR") == "route-set"
        assert irr._object_class("AS-FOO:AS-BAR") == "as-set"

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("AS-FOO-CUSTOMERS-V4", "as-set"),
            ("AS-IX-RS-MEMBERS", "as-set"),
            ("AS1:AS-FOO-RS-BAR", "as-set"),
            ("RS-FOO", "route-set"),
            ("AS1:RS-FOO", "route-set"),
        ],
    )
    def test_object_class_rs_component(self, name, expected):
        # #499: RS- only marks a route-set at the start of a name component
        assert irr._object_class(name) == expected

    # --- exists_in -----------------------------------------------------------

    def test_exists_in_found(self):
        send = make_send({("ARIN", "AS-FOO")})
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            assert irr.exists_in("ARIN", "AS-FOO") is True

    def test_exists_in_absent(self):
        send = make_send(set())  # nothing exists anywhere
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            # ARIN is mirrored by both servers, so "no entries" is a real absent
            assert irr.exists_in("ARIN", "AS-NOPE") is False

    def test_exists_in_unknown_on_outage(self):
        send = make_send({("ARIN", "AS-FOO")}, fail_hosts=("ntt", "radb"))
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            # whole pool unreachable -> unknown (fail open), never False
            assert irr.exists_in("ARIN", "AS-FOO") is None

    def test_exists_in_skips_non_mirroring_server_no_false_absent(self):
        # REACH is only mirrored by radb. The object exists there. NTT (which does
        # not mirror REACH) must be skipped, not treated as a "no entries" absent.
        send = make_send({("REACH", "AS-ONLY-RADB")})
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            assert irr.exists_in("REACH", "AS-ONLY-RADB") is True

    @staticmethod
    def _reply_send(reply):
        # every server mirrors every source and answers the pinned query with `reply`
        def send(server, payload, deadline=None):
            if payload == "!s-lc":
                return irrd_list(MIRROR[server["host"]])
            return reply

        return send

    @pytest.mark.parametrize(
        "reply,expected",
        [
            ("C\nA40\nas-set: AS-FOO\nsource: ARIN\n\nC\n", True),
            ("C\nD\n", False),
            ("C\nC\n", False),
            # #499: an IRRd error is unknown, never a false absent
            ("C\nF Internal error\n", None),
            ("%% ERROR: internal error\n", None),
            # a rejected !s leaves IRRd on its default sources, so the object that
            # follows may come from any registry
            ("F One or more selected sources are unavailable.\nA40\nas-set:\n", None),
            ("C\n", None),
            ("", None),
        ],
    )
    def test_exists_in_reply(self, reply, expected):
        with (
            patch("peeringdb_server.irr._send", side_effect=self._reply_send(reply)),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            assert irr.exists_in("ARIN", "AS-FOO") is expected

    def test_exists_in_query_is_source_pinned(self):
        with (
            patch(
                "peeringdb_server.irr._send", side_effect=self._reply_send("C\nD\n")
            ) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            irr.exists_in("ARIN", "AS64496")
        assert m_send.call_args_list[-1].args[1] == (
            "!!\n!sARIN\n!maut-num,AS64496\n!q"
        )

    @pytest.mark.parametrize(
        "name,canonical",
        [
            ("AS0003333", "AS3333"),
            # as long as a name can be (255 characters)
            ("AS" + "0" * 249 + "3333", "AS3333"),
            ("AS000", "AS0"),
        ],
    )
    def test_exists_in_normalizes_zero_padded_asn(self, name, canonical):
        # whois answered AS0003333 with the AS3333 object; `!m` matches the key
        # exactly, so the query must carry the canonical form
        send = make_send({("RIPE", canonical)})
        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            assert irr.exists_in("RIPE", name) is True
        assert m_send.call_args_list[-1].args[1] == (
            f"!!\n!sRIPE\n!maut-num,{canonical}\n!q"
        )

    def test_exists_in_trusts_pinned_answer_when_mirror_list_unavailable(self):
        # !s-lc returns nothing parseable (mirror list unknown), but the pinned
        # query still answers definitively -> the server is tried, not skipped
        def send(server, payload, deadline=None):
            if payload == "!s-lc":
                return "C\n"  # no source list
            return "C\nA30\nas-set: AS-FOO\nsource: ARIN\n\nC\n"

        with (
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            assert irr.exists_in("ARIN", "AS-FOO") is True

    def test_exists_in_ignores_false_when_mirror_list_unavailable(self):
        # Opposite of the case above: !s-lc is unparseable and the pinned query says
        # "no entries". We cannot confirm the server carries the source, so that
        # False may be a false absent -- stay unknown (None), which the save path
        # tolerates where False would reject.
        def send(server, payload, deadline=None):
            if payload == "!s-lc":
                return "C\n"  # no source list -> mirror list unknown
            return "C\nD\n"

        with (
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            assert irr.exists_in("ARIN", "AS-FOO") is None

    def test_exists_in_rejects_unknown_source(self):
        send = make_send(set())
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            assert irr.exists_in("NOTAREGISTRY", "AS-FOO") is None

    def test_exists_in_rejects_unsafe_name(self):
        send = make_send(set())
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            # a name with a space could break out of the whois command line
            assert irr.exists_in("ARIN", "AS-FOO AS-BAR") is None

    def test_exists_in_caches_result(self):
        send = make_send({("ARIN", "AS-FOO")})
        cache = FakeCache()
        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=cache),
        ):
            assert irr.exists_in("ARIN", "AS-FOO") is True
            calls_after_first = m_send.call_count
            # second call must be served from cache (no new pinned query)
            assert irr.exists_in("ARIN", "AS-FOO") is True
            # only the cached exists-result matters; no extra pinned lookups
            pinned = [
                c for c in m_send.call_args_list if c.args[1].startswith("!!\n!sARIN")
            ]
            assert len(pinned) == 1
            assert m_send.call_count >= calls_after_first

    # --- sources_for ---------------------------------------------------------

    def test_sources_for_found_in_several(self):
        send = make_send({("ARIN", "AS-FOO"), ("RIPE", "AS-FOO")})
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            result = irr.sources_for("AS-FOO")
        assert result.ok is True
        assert result.sources == frozenset({"ARIN", "RIPE"})

    def test_sources_for_found_nowhere_is_ok_empty(self):
        send = make_send(set())
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            result = irr.sources_for("AS-GHOST")
        assert result.ok is True
        assert result.sources == frozenset()

    def test_sources_for_found_in_several_on_one_mirror(self):
        # #502: `!m` answers with the first match only, so each source needs its
        # own `!s` + `!m` pair or a second registry goes unreported
        send = make_send(
            {("ARIN", "AS-FOO"), ("RIPE", "AS-FOO")}, mirror={"ntt": MIRROR["ntt"]}
        )
        with (
            override_settings(IRR_LOOKUP_SERVERS=TWO_SERVERS[:1]),
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-FOO")

        assert result.ok is True
        assert result.sources == frozenset({"ARIN", "RIPE"})

    def test_sources_for_uses_one_connection_per_mirror(self):
        send = make_send({("ARIN", "AS-FOO"), ("RIPE", "AS-FOO")})
        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-FOO")

        assert result.sources == frozenset({"ARIN", "RIPE"})
        queries = {
            call.args[0]["host"]: call.args[1]
            for call in m_send.call_args_list
            if call.args[1] != "!s-lc"
        }
        assert len(queries) == len(TWO_SERVERS)
        assert len(m_send.call_args_list) == 2 * len(TWO_SERVERS)
        for host, query in queries.items():
            pairs = [f"!s{source}\n!mas-set,AS-FOO" for source in sorted(MIRROR[host])]
            assert query == "\n".join(["!!", *pairs, "!q"])

    def test_sources_for_large_response_falls_back_to_pinned_checks(self):
        # AFRINIC sorts first on ntt, so its large object cuts off every answer
        # after it; radb answers ARIN / RADB / RIPE itself
        send = make_send(
            {("AFRINIC", "AS-LARGE"), ("RIPE", "AS-LARGE")},
            large={("AFRINIC", "AS-LARGE")},
        )
        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-LARGE")

        assert result.ok is True
        assert result.sources == frozenset({"AFRINIC", "RIPE"})
        pinned = sorted(
            call.args[1].split("\n")[1]
            for call in m_send.call_args_list
            if call.args[1].count("\n!s") == 1
        )
        assert pinned == ["!sAFRINIC", "!sAPNIC", "!sLACNIC", "!sNTTCOM"]

    @pytest.mark.parametrize(
        "reply",
        [
            "%% ERROR: One or more selected sources are unavailable.\n",
            "%% ERROR: An internal error occurred.\n",
            "F An internal error occurred.\n",
            "C\nF An internal error occurred.\n",
            "",
        ],
    )
    def test_sources_for_error_reply_is_unknown(self, reply):
        # #502: an error is not "found nowhere", and must not be cached as one
        def send(server, payload, deadline=None):
            if payload == "!s-lc":
                return irrd_list(MIRROR[server["host"]])
            return reply

        cache = FakeCache()
        with (
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=cache),
        ):
            result = irr.sources_for("AS-FOO")

        assert result.ok is False
        assert result.sources == frozenset()
        assert "irr:sources:as-set:AS-FOO" not in cache.store

    def test_sources_for_source_dropped_by_mirror_is_unknown(self):
        # radb still advertises ARIN in its cached !s-lc list but no longer
        # serves it, and ntt is down: ARIN is unknown, the rest still answered
        send = make_send(
            {("RIPE", "AS-FOO")},
            fail_hosts=("ntt",),
            serving={"radb": ["RADB", "RIPE", "REACH", "BBOI", "CANARIE"]},
        )
        cache = FakeCache()
        cache.set("irr:srcs:ntt:43", MIRROR["ntt"])
        with (
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=cache),
        ):
            result = irr.sources_for("AS-FOO")

        assert result.ok is False
        assert result.sources == frozenset({"RIPE"})

    def test_sources_for_ignores_match_after_rejected_select(self):
        # a rejected !s leaves the previous selection, so the !m after it would
        # report RIPE's object as ARIN's
        def send(server, payload, deadline=None):
            if payload == "!s-lc":
                return irrd_list(["RIPE", "ARIN"])
            if payload.count("\n!s") > 1:
                return (
                    "C\n"
                    + irrd_object("as-set", "AS-FOO", "ARIN")
                    + "F One or more selected sources are unavailable.\n"
                    + irrd_object("as-set", "AS-FOO", "ARIN")
                )
            return "C\nD\n"

        with (
            override_settings(IRR_LOOKUP_SERVERS=TWO_SERVERS[:1]),
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-FOO")

        assert result.ok is True
        assert result.sources == frozenset({"ARIN"})

    def test_sources_for_counts_object_length_in_bytes(self):
        # A<len> counts UTF-8 bytes; read as characters, the APNIC object's
        # length would end inside it and lose ARIN behind it
        def send(server, payload, deadline=None):
            if payload == "!s-lc":
                return irrd_list(["RIPE", "APNIC", "ARIN"])
            return (
                "C\n"
                + irrd_object("as-set", "AS-FOO", "APNIC", descr="Société €")
                + "C\n"
                + irrd_object("as-set", "AS-FOO", "ARIN")
                + "C\nD\n"
            )

        with (
            override_settings(IRR_LOOKUP_SERVERS=TWO_SERVERS[:1]),
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-FOO")

        assert result == irr.LookupResult(frozenset({"APNIC", "ARIN"}), True)
        assert len(m_send.call_args_list) == 2  # !s-lc and the one batch

    def test_read_statuses_keeps_undecodable_bytes_in_step(self):
        # a raw Latin-1 byte must not shift the offsets of the replies after it;
        # found in APNIC, then absent from the next source
        body = b"as-set: AS-FOO\ndescr: caf\xe9\nsource: APNIC"
        raw = b"C\nA%d\n%s\nC\nC\nD\n" % (len(body) + 1, body)
        text = raw.decode("utf-8", "surrogateescape")  # as _send decodes it

        assert irr._read_statuses(text) == ["C", "A", "C", "D"]

    @pytest.mark.parametrize("skew", [-2, -1, 1])
    def test_read_statuses_stops_when_length_is_out_of_step(self, skew):
        # a wrong count must end the parse, not pair later replies with the
        # wrong sources (a body ending in "...C" could otherwise pass for C)
        body = "as-set: AS-FOO\nsource: APNIC"
        text = f"C\nA{len(body) + 1 + skew}\n{body}\nC\nC\nA5\nabcd\nC\n"

        assert irr._read_statuses(text) == ["C"]

    # --- !s-lc mirror list -------------------------------------------------

    @pytest.mark.parametrize(
        "sources",
        [
            # live orders seen on rr.ntt.net / whois.radb.net, which happen to
            # start with neither A, C nor D
            ["NTTCOM", "RADB", "ARIN"],
            # #543: a list starting with a status letter is still the list
            ["ARIN", "RIPE"],
            ["CANARIE", "RADB"],
            ["DEFAULT", "RIPE"],
            ["APNIC"],
        ],
    )
    def test_server_sources_reads_list_by_framing(self, sources):
        with (
            patch("peeringdb_server.irr._send", return_value=irrd_list(sources)),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            assert irr._server_sources(TWO_SERVERS[0]) == frozenset(sources)

    @pytest.mark.parametrize(
        "reply",
        [
            "C\n",
            "D\n",
            "F Unknown command\n",
            "%% ERROR: unknown command\n",
            "A10\nRIPE,RADB\n",  # cut off before C
            "A5\nRIPE,RADB\nC\n",  # count out of step with the list
            "A1\n\nC\n",  # empty list
            "",
        ],
    )
    def test_server_sources_unknown_on_other_replies(self, reply):
        cache = FakeCache()
        with (
            patch("peeringdb_server.irr._send", return_value=reply),
            patch("peeringdb_server.irr._cache", return_value=cache),
        ):
            assert irr._server_sources(TWO_SERVERS[0]) is None
        assert cache.store == {}

    def test_sources_for_uses_mirror_whose_list_starts_with_arin(self):
        # #543: the server used to read as mirroring nothing, so nothing was
        # definitive
        send = make_send({("RIPE", "AS-FOO")}, mirror={"ntt": ["ARIN", "RIPE", "RADB"]})
        with (
            override_settings(IRR_LOOKUP_SERVERS=TWO_SERVERS[:1]),
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-FOO")

        assert result == irr.LookupResult(frozenset({"RIPE"}), True)

    @pytest.mark.parametrize("digits", [10, 4301, 5000])
    def test_oversized_length_is_unknown(self, digits):
        # a count past what a reply under the read cap can hold reads as an
        # unrecognized reply, not as a ValueError out of int()
        header = "A" + "9" * digits
        assert irr._read_statuses(f"C\n{header}\nas-set: AS-FOO\nC\n") == ["C"]
        with (
            patch("peeringdb_server.irr._send", return_value=f"{header}\nRIPE\nC\n"),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            assert irr._server_sources(TWO_SERVERS[0]) is None

    def test_sources_for_falls_back_on_oversized_length(self):
        # the batch reply is unknown, so every source gets its pinned check
        def send(server, payload, deadline=None):
            if payload == "!s-lc":
                return irrd_list(MIRROR[server["host"]])
            if payload.count("\n!s") > 1:
                return "C\nA" + "9" * 5000 + "\nas-set: AS-FOO\nC\n"
            return "C\nD\n"

        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-FOO")

        assert result == irr.LookupResult(frozenset(), True)
        pinned = {
            call.args[1].split("\n")[1][2:]
            for call in m_send.call_args_list
            if call.args[1].count("\n!s") == 1
        }
        assert pinned == set(MIRROR["ntt"]) | set(MIRROR["radb"])

    @pytest.mark.parametrize(
        "name,sent",
        [
            ("AS-" + "X" * 252, True),
            ("AS-" + "X" * 253, False),
            # a zero-padded ASN past int()'s 4300-digit limit is refused too
            ("AS" + "0" * 4301 + "3333", False),
        ],
    )
    def test_name_length_is_capped_at_the_field_length(self, name, sent):
        send = make_send(set())
        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for(name)
            exists = irr.exists_in("RIPE", name)

        assert m_send.called is sent
        assert result.ok is sent
        assert exists is (False if sent else None)

    def test_sources_for_caches_complete_result(self):
        send = make_send({("ARIN", "AS-FOO")})
        cache = FakeCache()
        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=cache),
        ):
            assert irr.sources_for("AS-FOO").sources == frozenset({"ARIN"})
            calls_after_first = m_send.call_count
            assert irr.sources_for("AS-FOO").sources == frozenset({"ARIN"})

        assert m_send.call_count == calls_after_first

    def test_sources_for_pool_unreachable_not_ok(self):
        send = make_send(set(), fail_hosts=("ntt", "radb"))
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            result = irr.sources_for("AS-FOO")
        assert result.ok is False
        assert result.sources == frozenset()

    def test_sources_for_not_ok_when_mirror_list_cached_but_queries_fail(self):
        """
        The !s-lc mirror list is cached, so a pool outage that starts afterwards
        leaves `reachable` populated while no object query can answer. That must
        not report a definitive "found nowhere": _confirm_unresolved acts on it by
        telling operators their AS-SET does not exist.
        """
        cache = FakeCache()
        warm = make_send(set())
        with (
            patch("peeringdb_server.irr._send", side_effect=warm),
            patch("peeringdb_server.irr._cache", return_value=cache),
        ):
            # warm the per-server mirror lists into the cache
            irr._server_sources(TWO_SERVERS[0])
            irr._server_sources(TWO_SERVERS[1])

        def only_slc_from_cache(server, payload, deadline=None):
            # every object query now fails; !s-lc would too, but it is cached
            raise TimeoutError("mocked timeout")

        with (
            patch("peeringdb_server.irr._send", side_effect=only_slc_from_cache),
            patch("peeringdb_server.irr._cache", return_value=cache),
        ):
            result = irr.sources_for("AS-GHOST")

        assert result.ok is False
        assert result.sources == frozenset()
        # and the fail-open artifact must not be cached for the whole TTL
        assert "irr:sources:as-set:AS-GHOST" not in cache.store

    def test_sources_for_not_ok_when_one_mirrors_answer_is_unusable(self):
        """
        A partial answer is not a definitive one. Here radb reports its mirror
        list fine but every object query against it fails, so REACH / BBOI /
        CANARIE (which only radb carries) are neither confirmed nor ruled out.
        """
        base_send = make_send({("RIPE", "AS-FOO")})

        def send(server, payload, deadline=None):
            if server["host"] == "radb" and payload != "!s-lc":
                raise TimeoutError("mocked timeout")
            return base_send(server, payload)

        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            result = irr.sources_for("AS-FOO")

        assert result.ok is False
        # what was positively found is still reported, it is just not exhaustive
        assert "RIPE" in result.sources

    def test_sources_for_unsafe_name_not_ok(self):
        send = make_send(set())
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            result = irr.sources_for("AS-FOO;rm -rf")
        assert result.ok is False

    # --- coverage_report -----------------------------------------------------

    def test_coverage_report(self):
        send = make_send(set())
        p_send, p_cache = self._patches(send)
        with p_send, p_cache:
            report = irr.coverage_report()
        # REACH/BBOI/CANARIE covered by radb only in our fake mirror map
        assert report["covered"]["REACH"] == ["radb"]
        # a pruned source must not reappear: coverage_report iterates IRR_SOURCE,
        # so this is also the assertion that the prune actually took effect
        assert "NESTEGG" not in report["covered"]
        assert "NESTEGG" not in report["uncovered"]
        assert "ntt" in report["covered"]["ARIN"]
        assert "radb" in report["covered"]["ARIN"]
        # sources no fake server mirrors show up as uncovered (e.g. ALTDB, TC…)
        assert "ALTDB" in report["uncovered"]


# --- opt-in live integration test (real NTT + RADB) --------------------------
# Skipped automatically where the IRR pool isn't reachable (e.g. sandboxed CI).
# Exercises the save-path live existence check end-to-end against real servers,
# with the gate (off in the suite) explicitly turned on.
@pytest.mark.skipif(
    not _irr_reachable(), reason="IRR servers not reachable from this host"
)
@override_settings(
    IRR_AS_SET_VERIFY_EXISTENCE=True,
    IRR_AS_SET_REQUIRE_SOURCE=True,
    IRR_AS_SET_MAX_SETS=1,
)
def test_validate_irr_as_set_live_real_irr():
    # a real, existing object passes the strict live existence check
    assert (
        validate_irr_as_set("RADB::AS-HURRICANE", strict=True) == "RADB::AS-HURRICANE"
    )
    # a syntactically valid but non-existent object is rejected
    with pytest.raises(ValidationError):
        validate_irr_as_set("RIPE::AS-ZZ-ZZZZZZ", strict=True)
