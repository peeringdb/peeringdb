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
from django.core.exceptions import ValidationError
from django.test import override_settings

from peeringdb_server import irr
from peeringdb_server.validators import validate_irr_as_set

pytestmark = pytest.mark.django_db


def _irr_reachable(host="rr.ntt.net", port=43, timeout=3):
    """True if the real IRR pool is reachable — gates the opt-in live test."""
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


# Two-server pool used across the tests.
TWO_SERVERS = [
    {"host": "ntt", "port": 43, "timeout": 5},
    {"host": "radb", "port": 43, "timeout": 5},
]

# Which sources each fake server mirrors (a trimmed, realistic split — NTT lacks
# REACH / BBOI / CANARIE; RADB carries them).
MIRROR = {
    "ntt": ["NTTCOM", "RADB", "RIPE", "ARIN", "APNIC", "AFRINIC", "LACNIC"],
    "radb": ["RADB", "RIPE", "ARIN", "REACH", "BBOI", "CANARIE"],
}


class FakeCache:
    """Minimal in-memory stand-in for caches['negative']."""

    def __init__(self):
        self.store = {}

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value, timeout=None):
        self.store[key] = value


def make_send(present, mirror=MIRROR, fail_hosts=()):
    """
    Build a _send side_effect.

    - present: set of (SOURCE, NAME) tuples that "exist".
    - mirror: host -> list of mirrored sources (for !s-lc).
    - fail_hosts: hosts whose every query raises a timeout (OSError).
    """

    def _send(server, payload):
        host = server["host"]
        if host in fail_hosts:
            raise TimeoutError("mocked timeout")
        if payload == "!s-lc":
            return "A20\n" + ",".join(mirror.get(host, [])) + "\nC\n"
        if payload.startswith("-s ") and "," in payload.split()[1]:
            # Multi-source exact-name completion query: return every matching
            # object carried by this mirror, each with its source attribute.
            parts = payload.split()
            object_class, name = parts[3], parts[-1]
            objects = [
                f"{object_class}: {name}\nsource: {source}\n"
                for source, present_name in sorted(present)
                if present_name == name and source in mirror.get(host, [])
            ]
            if objects:
                return "\n".join(objects)
            return "%  No entries found for the selected source(s).\n\n"
        # "-s <SOURCE> -T <class> <NAME>"
        parts = payload.split()
        source, name = parts[1], parts[-1]
        object_class = parts[3]
        if (source, name) in present:
            return f"{object_class}:         {name}\ndescr: mocked\nsource: {source}\n"
        return "%  No entries found for the selected source(s).\n\n"

    return _send


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

    def test_exists_in_unknown_on_unrecognized_response(self):
        # server mirrors the source and answers, but with a first line that is
        # neither an RPSL object nor "% No entries" (e.g. an IRRd "F ..." error)
        # -> treated as unknown (fail open), never a false True/False
        def send(server, payload):
            if payload == "!s-lc":
                return "A20\n" + ",".join(MIRROR[server["host"]]) + "\nC\n"
            return "F malformed query\n"

        with (
            patch("peeringdb_server.irr._send", side_effect=send),
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            assert irr.exists_in("ARIN", "AS-FOO") is None

    def test_exists_in_trusts_pinned_answer_when_mirror_list_unavailable(self):
        # !s-lc returns nothing parseable (mirror list unknown), but the pinned
        # query still answers definitively -> the server is tried, not skipped
        def send(server, payload):
            if payload == "!s-lc":
                return "C\n"  # no source list
            return "as-set: AS-FOO\nsource: ARIN\n"

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
        def send(server, payload):
            if payload == "!s-lc":
                return "C\n"  # no source list -> mirror list unknown
            return "%  No entries found for the selected source(s).\n\n"

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
                c for c in m_send.call_args_list if c.args[1].startswith("-s ARIN")
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

    def test_sources_for_uses_one_unpinned_query_per_mirror(self):
        send = make_send({("ARIN", "AS-FOO"), ("RIPE", "AS-FOO")})
        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-FOO")

        assert result.sources == frozenset({"ARIN", "RIPE"})
        completion_queries = [
            call
            for call in m_send.call_args_list
            if call.args[1].startswith("-s ") and "," in call.args[1].split()[1]
        ]
        pinned_queries = [
            call
            for call in m_send.call_args_list
            if call.args[1].startswith("-s ") and "," not in call.args[1].split()[1]
        ]
        assert len(completion_queries) == len(TWO_SERVERS)
        assert pinned_queries == []

    def test_sources_for_large_response_falls_back_to_pinned_checks(self):
        base_send = make_send({("ARIN", "AS-LARGE")})

        def send(server, payload):
            if payload.startswith("-s ") and "," in payload.split()[1]:
                return "as-set: AS-LARGE\nmembers: " + ("AS1," * 3000)
            return base_send(server, payload)

        with (
            patch("peeringdb_server.irr._send", side_effect=send) as m_send,
            patch("peeringdb_server.irr._cache", return_value=FakeCache()),
        ):
            result = irr.sources_for("AS-LARGE")

        assert result.sources == frozenset({"ARIN"})
        assert any(call.args[1].startswith("-s ARIN") for call in m_send.call_args_list)

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

        def only_slc_from_cache(server, payload):
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

        def send(server, payload):
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
