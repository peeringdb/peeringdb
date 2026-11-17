"""
Time limits of live IRR lookups (peeringdb_server/irr.py).

The exchange tests talk to a listener on 127.0.0.1 inside the test process;
no registry is contacted.
"""

import errno
import socket
import threading
import time
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from peeringdb_server import irr
from peeringdb_server.validators import validate_irr_as_set

from .irr_fakes import MIRROR, TWO_SERVERS, FakeCache, irrd_list, make_send

pytestmark = pytest.mark.django_db


class Listener:
    """
    Accepts connections on 127.0.0.1 and runs `behaviour(conn)` for each one.
    """

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.accepted = 0
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.accepted += 1
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        try:
            self.behaviour(conn, self.stop)
        except OSError:
            pass
        finally:
            conn.close()

    def server(self, timeout):
        return {"host": "127.0.0.1", "port": self.port, "timeout": timeout}

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(1)
        self.sock.close()


def silent(conn, stop):
    stop.wait(10)


def trickle(conn, stop):
    # one byte at a time, each just inside a 0.5 s socket timeout
    for byte in b"A20\nRIPE,ARIN,RADB,APNIC\nC\n":
        if stop.wait(0.3):
            return
        conn.sendall(bytes([byte]))


@pytest.fixture
def cache():
    cache = FakeCache()
    with patch("peeringdb_server.irr._cache", return_value=cache):
        yield cache


def test_send_stops_a_trickling_reply_at_the_server_timeout(cache):
    with Listener(trickle) as listener:
        server = listener.server(timeout=0.5)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            irr._send(server, "!s-lc")
        assert time.monotonic() - started < 1.5
    assert cache.get(irr._down_key(server)) is True


class UnansweredSocket:
    """A socket whose connect waits out its timeout, as for an unanswered SYN."""

    def __init__(self, family=-1, kind=-1, proto=-1):
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, address):
        time.sleep(self.timeout)
        raise TimeoutError("timed out")

    def close(self):
        pass


def test_send_connects_within_the_timeout_for_several_addresses(cache):
    server = {"host": "mirror.example", "port": 43, "timeout": 0.4}
    addresses = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 43, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 43)),
    ]
    started = time.monotonic()
    with (
        patch("socket.getaddrinfo", return_value=addresses),
        patch("socket.socket", UnansweredSocket),
        pytest.raises(TimeoutError),
    ):
        irr._send(server, "!s-lc")
    # one timeout in total, not one per address
    assert time.monotonic() - started < 0.6
    assert cache.get(irr._down_key(server)) is True


def test_send_resolves_no_name_once_the_time_is_up(cache):
    server = {"host": "mirror.example", "port": 43, "timeout": 5}
    with (
        patch("socket.getaddrinfo") as m_getaddrinfo,
        pytest.raises(TimeoutError),
    ):
        irr._send(server, "!s-lc", deadline=time.monotonic() - 1)
    m_getaddrinfo.assert_not_called()


REAL_SOCKET = socket.socket


def no_ipv6_socket(family=-1, kind=-1, proto=-1, fileno=None):
    if family == socket.AF_INET6 and fileno is None:
        raise OSError(errno.EAFNOSUPPORT, "Address family not supported")
    return REAL_SOCKET(family, kind, proto, fileno)


def test_send_moves_on_when_an_address_family_is_unusable(cache):
    def answer(conn, stop):
        conn.recv(4096)
        conn.sendall(irrd_list(["RIPE"]).encode())

    with Listener(answer) as listener:
        addresses = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", listener.port, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", listener.port)),
        ]
        server = {"host": "mirror.example", "port": listener.port, "timeout": 2}
        with (
            patch("socket.getaddrinfo", return_value=addresses),
            patch("socket.socket", no_ipv6_socket),
        ):
            assert irr._server_sources(server) == frozenset({"RIPE"})


def test_send_reads_no_more_than_the_cap(cache, settings):
    settings.IRR_LOOKUP_MAX_RESPONSE_BYTES = 1000

    def flood(conn, stop):
        conn.recv(4096)
        conn.sendall(b"x" * 5000)

    with Listener(flood) as listener:
        assert len(irr._send(listener.server(timeout=2), "!s-lc")) == 1000


def test_send_marks_a_silent_mirror_and_skips_it_next_time(cache):
    with Listener(silent) as listener:
        server = listener.server(timeout=0.5)
        with pytest.raises(TimeoutError):
            irr._send(server, "!s-lc")
        assert listener.accepted == 1

        started = time.monotonic()
        with pytest.raises(TimeoutError):
            irr._send(server, "!s-lc")
        assert time.monotonic() - started < 0.2
        assert listener.accepted == 1


def test_send_does_not_mark_a_mirror_when_the_lookup_budget_ran_out(cache):
    with Listener(silent) as listener:
        server = listener.server(timeout=5)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            irr._send(server, "!s-lc", deadline=time.monotonic() + 0.3)
        assert time.monotonic() - started < 1
        assert cache.get(irr._down_key(server)) is None

        # a spent budget opens no connection at all
        with pytest.raises(TimeoutError):
            irr._send(server, "!s-lc", deadline=time.monotonic() - 1)
        time.sleep(0.2)
        assert listener.accepted == 1


def test_send_does_not_mark_a_refused_mirror(cache):
    with Listener(silent) as listener:
        server = listener.server(timeout=0.5)
    # the listener is closed now, so the port refuses
    with pytest.raises(OSError) as error:
        irr._send(server, "!s-lc")
    assert not isinstance(error.value, TimeoutError)
    assert cache.get(irr._down_key(server)) is None


def test_send_still_answers_within_the_deadline(cache):
    def answer(conn, stop):
        conn.recv(4096)
        conn.sendall(irrd_list(["RIPE", "ARIN"]).encode())

    with Listener(answer) as listener:
        server = listener.server(timeout=2)
        assert irr._server_sources(server) == frozenset({"RIPE", "ARIN"})
    assert cache.get(irr._down_key(server)) is None


def test_sources_for_with_a_silent_mirror_is_bounded_and_not_ok(cache, settings):
    with Listener(silent) as listener:
        server = listener.server(timeout=0.5)
        settings.IRR_LOOKUP_SERVERS = [server]
        # the mirror list was cached before the mirror went silent
        cache.set(
            f"irr:srcs:127.0.0.1:{listener.port}", ["RIPE", "ARIN", "RADB", "APNIC"]
        )
        started = time.monotonic()
        result = irr.sources_for("AS-SILENT")
        elapsed = time.monotonic() - started
        assert listener.accepted == 1

    # one exchange ran out; every other query skipped the marked mirror
    assert elapsed < 1.5
    assert result.ok is False
    assert result.sources == frozenset()
    assert "irr:sources:as-set:AS-SILENT" not in cache.store


def test_sources_for_reads_as_unknown_once_its_budget_is_spent(cache, settings):
    settings.IRR_LOOKUP_SERVERS = TWO_SERVERS
    settings.IRR_LOOKUP_BUDGET = 0.2
    for host, sources in MIRROR.items():
        cache.set(f"irr:srcs:{host}:43", sources)
    answer = make_send(set())

    def send(server, payload, deadline=None):
        if time.monotonic() >= deadline:
            raise TimeoutError("budget")
        # the first mirror answers definitively, but only after the budget
        time.sleep(0.3)
        return answer(server, payload)

    with patch("peeringdb_server.irr._send", side_effect=send):
        result = irr.sources_for("AS-LATE")

    assert result.ok is False
    assert "irr:sources:as-set:AS-LATE" not in cache.store


def test_sources_for_not_ok_when_a_mirror_list_is_unavailable(cache, settings):
    # ntt's list is not cached and ntt does not answer; radb alone answers
    # every source it carries, but ntt may carry a source radb does not
    settings.IRR_LOOKUP_SERVERS = TWO_SERVERS
    send = make_send({("RIPE", "AS-FOO")}, fail_hosts=("ntt",))
    with patch("peeringdb_server.irr._send", side_effect=send):
        result = irr.sources_for("AS-FOO")

    assert result.ok is False
    assert result.sources == frozenset({"RIPE"})
    assert "irr:sources:as-set:AS-FOO" not in cache.store


def test_exists_in_reads_as_unknown_once_its_budget_is_spent(cache, settings):
    settings.IRR_LOOKUP_SERVERS = TWO_SERVERS
    answer = make_send(set())

    def send(server, payload, deadline=None):
        # as the real _send does with a spent deadline
        if time.monotonic() >= deadline:
            raise TimeoutError("budget")
        return answer(server, payload)

    with patch("peeringdb_server.irr._send", side_effect=send) as m_send:
        assert irr.exists_in("RIPE", "AS-FOO", deadline=time.monotonic() - 1) is None
    assert m_send.call_count
    assert "irr:exists:RIPE:as-set:AS-FOO" not in cache.store


@pytest.mark.parametrize("name", ["AS-SECTEST-X\n", "AS-SECTEST-X\r\n"])
def test_trailing_newline_is_refused_before_any_connection(cache, name):
    with patch("peeringdb_server.irr._send") as m_send:
        assert irr.sources_for(name) == irr.LookupResult(frozenset(), False)
        assert irr.exists_in("RIPE", name) is None
    m_send.assert_not_called()


@pytest.fixture
def verify_existence(settings):
    settings.IRR_AS_SET_VERIFY_EXISTENCE = True
    settings.IRR_AS_SET_MAX_SETS = 0


def test_save_path_shares_one_budget_across_tokens(cache, settings, verify_existence):
    settings.IRR_LOOKUP_SERVERS = TWO_SERVERS
    settings.IRR_LOOKUP_SAVE_BUDGET = 12
    calls = []

    def exists(source, name, object_class=None, deadline=None):
        calls.append(deadline)
        # every token's lookup is slow and never answers
        time.sleep(0.2)
        return None

    tokens = " ".join(f"RIPE::AS-TOKEN{index}" for index in range(5))
    started = time.monotonic()
    with patch("peeringdb_server.irr.exists_in", side_effect=exists):
        # unknown everywhere: accepted, as before
        assert validate_irr_as_set(tokens, strict=True)
    assert len(calls) == 5
    assert len(set(calls)) == 1
    assert calls[0] == pytest.approx(started + 12, abs=0.5)


def test_save_path_tokens_past_the_budget_read_as_unknown(
    cache, settings, verify_existence
):
    settings.IRR_LOOKUP_SERVERS = TWO_SERVERS
    settings.IRR_LOOKUP_SAVE_BUDGET = 0.4
    for host, sources in MIRROR.items():
        cache.set(f"irr:srcs:{host}:43", sources)
    answer = make_send(set())

    def send(server, payload, deadline=None):
        if time.monotonic() >= deadline:
            raise TimeoutError("budget")
        time.sleep(0.15)
        return answer(server, payload)

    tokens = " ".join(f"RIPE::AS-ABSENT{index}" for index in range(10))
    started = time.monotonic()
    with patch("peeringdb_server.irr._send", side_effect=send):
        # the first tokens are provably absent and reject the value
        with pytest.raises(ValidationError) as error:
            validate_irr_as_set(tokens, strict=True)
    elapsed = time.monotonic() - started
    assert "AS-ABSENT0" in str(error.value)
    assert "AS-ABSENT9" not in str(error.value)
    assert elapsed < 1.5
