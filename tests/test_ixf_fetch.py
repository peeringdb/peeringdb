"""
Bounded retrieval of IX-F exports (ixf_fetch), against local stub servers.
"""

import datetime
import gzip
import ipaddress
import json
import socket
import socketserver
import ssl
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from django.test import override_settings

from peeringdb_server import ixf, ixf_fetch
from peeringdb_server.models import InternetExchange, Organization

FEED = {"version": "1.0", "member_list": [{"asnum": 2906}]}
FEED_BYTES = json.dumps(FEED).encode()
LIMIT = 1024 * 1024

pytestmark = pytest.mark.django_db

HOSTS = []
PATHS = []

ADDRESS_ALLOWED = ixf_fetch.address_allowed


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body=b"", headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if "Content-Length" not in (headers or {}):
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        HOSTS.append(self.headers.get("Host"))
        PATHS.append(self.path)
        path = self.path
        if path == "/feed.json":
            self.send(200, FEED_BYTES)
        elif path == "/gzip.json":
            self.send(200, gzip.compress(FEED_BYTES), {"Content-Encoding": "gzip"})
        elif path == "/deflate.json":
            self.send(200, zlib.compress(FEED_BYTES), {"Content-Encoding": "deflate"})
        elif path == "/gzip-bomb.json":
            body = gzip.compress(b"[" + b" " * (8 * LIMIT) + b"]")
            self.send(200, body, {"Content-Encoding": "gzip"})
        elif path == "/big.json":
            self.send(200, b"[" + b" " * LIMIT + b"]")
        elif path == "/big-header.json":
            self.send(200, FEED_BYTES, {"Content-Length": str(LIMIT + 1)})
        elif path == "/chunked-big.json":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = b" " * 65536
            for _ in range(LIMIT // len(chunk) + 2):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.write(b"0\r\n\r\n")
        elif path == "/trickle.json":
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            for _ in range(100):
                try:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.25)
        elif path == "/continue-forever":
            for _ in range(200):
                try:
                    self.wfile.write(b"HTTP/1.1 100 Continue\r\n\r\n")
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.05)
        elif path == "/slow-headers":
            self.wfile.write(b"HTTP/1.1 200 OK\r\n")
            for _ in range(200):
                try:
                    self.wfile.write(b"X-Slow: a\r\n")
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.05)
        elif path == "/gzip-trailing.json":
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            body = gzip.compress(FEED_BYTES) + b"\0" * (2 * LIMIT)
            for i in range(0, len(body), 65536):
                chunk = body[i : i + 65536]
                try:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                except OSError:
                    return
            self.wfile.write(b"0\r\n\r\n")
        elif path == "/nested.json":
            self.send(200, b"[" * 200000)
        elif path == "/gzip-members.json":
            half = len(FEED_BYTES) // 2
            body = gzip.compress(FEED_BYTES[:half]) + gzip.compress(FEED_BYTES[half:])
            self.send(200, body, {"Content-Encoding": "gzip"})
        elif path == "/slow-steady.json":
            # thinks before answering, then sends the body in pieces: slower
            # than any single read may wait in total, but never idle that long
            time.sleep(1.5)
            self.send_response(200)
            self.send_header("Content-Length", str(len(FEED_BYTES)))
            self.end_headers()
            step = len(FEED_BYTES) // 8 + 1
            for i in range(0, len(FEED_BYTES), step):
                self.wfile.write(FEED_BYTES[i : i + step])
                self.wfile.flush()
                time.sleep(0.4)
        elif path == "/gzip-stray-byte.json":
            self.send(
                200, gzip.compress(FEED_BYTES) + b"\n", {"Content-Encoding": "gzip"}
            )
        elif path == "/gzip-truncated.json":
            self.send(200, gzip.compress(FEED_BYTES)[:-8], {"Content-Encoding": "gzip"})
        elif path.startswith("/caf"):
            self.send(200, FEED_BYTES)
        elif path == "/br.json":
            self.send(200, FEED_BYTES, {"Content-Encoding": "br"})
        elif path == "/bad-gzip.json":
            self.send(200, b"not gzip at all", {"Content-Encoding": "gzip"})
        elif path == "/not-json":
            self.send(200, b"<html>hello</html>")
        elif path.startswith("/status/"):
            self.send(int(path.rsplit("/", 1)[1]), b"SECRET-BODY")
        elif path.startswith("/redirect/"):
            hops = int(path.rsplit("/", 1)[1])
            target = "/feed.json" if hops <= 1 else f"/redirect/{hops - 1}"
            self.send(302, b"", {"Location": target})
        elif path.startswith("/redirect-to/"):
            self.send(302, b"", {"Location": path[len("/redirect-to/") :]})
        elif path == "/redirect-ftp":
            self.send(302, b"", {"Location": "ftp://127.0.0.1/feed.json"})
        else:
            self.send(404)


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def allow_stub_address(monkeypatch):
    """
    The stub servers listen on 127.0.0.1, which the fetcher refuses; allow
    exactly that address, everything else keeps the real check.
    """
    check = ixf_fetch.address_allowed
    stub = ipaddress.ip_address("127.0.0.1")
    monkeypatch.setattr(
        ixf_fetch, "address_allowed", lambda address: address == stub or check(address)
    )


def fetch(url, timeout=5):
    return ixf_fetch.fetch_json(url, timeout=timeout, max_bytes=LIMIT)


@pytest.mark.parametrize("path", ["/feed.json", "/gzip.json", "/deflate.json"])
def test_fetch_feed(server, path):
    assert fetch(server + path) == FEED


@pytest.mark.parametrize(
    "path", ["/gzip-bomb.json", "/big.json", "/big-header.json", "/chunked-big.json"]
)
def test_fetch_size_limit(server, path):
    with pytest.raises(ixf_fetch.FetchError, match="exceeds the size limit"):
        fetch(server + path)


def test_fetch_deadline_covers_slow_body(server):
    start = time.monotonic()
    with pytest.raises(ixf_fetch.FetchError, match="timed out"):
        fetch(server + "/trickle.json", timeout=1.5)
    assert time.monotonic() - start < 3


@pytest.mark.parametrize("path", ["/continue-forever", "/slow-headers"])
def test_fetch_deadline_covers_headers(server, path):
    start = time.monotonic()
    with pytest.raises(ixf_fetch.FetchError, match="timed out"):
        fetch(server + path, timeout=1.5)
    assert time.monotonic() - start < 3


def test_fetch_stops_at_end_of_compressed_stream(server):
    assert fetch(server + "/gzip-trailing.json") == FEED


def test_fetch_deeply_nested_json(server):
    with pytest.raises(ixf_fetch.FetchError, match="No JSON could be parsed"):
        fetch(server + "/nested.json")


def test_fetch_follows_redirects(server):
    assert fetch(server + "/redirect/3") == FEED


def test_fetch_redirect_limit(server):
    with pytest.raises(ixf_fetch.FetchError, match="redirected too many times"):
        fetch(server + "/redirect/5")


def test_fetch_redirect_scheme(server):
    with pytest.raises(ixf_fetch.FetchError, match="must use http or https"):
        fetch(server + "/redirect-ftp")


@pytest.mark.parametrize(
    "path,message",
    [
        ("/status/401", "returned HTTP status 401"),
        ("/br.json", "unsupported encoding"),
        ("/bad-gzip.json", "invalid compressed data"),
        ("/not-json", "No JSON could be parsed"),
    ],
)
def test_fetch_errors(server, path, message):
    with pytest.raises(ixf_fetch.FetchError, match=message) as exc:
        fetch(server + path)
    assert "SECRET-BODY" not in str(exc.value)
    assert "127.0.0.1" not in str(exc.value)


def test_fetch_connection_error_has_no_details(server):
    closed = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = closed.server_address[1]
    closed.server_close()

    with pytest.raises(ixf_fetch.FetchError) as exc:
        fetch(f"http://127.0.0.1:{port}/")

    assert str(exc.value) == "Could not connect to the IX-F member list URL"


def test_importer_fetch_reports_fixed_message(server):
    data = ixf.Importer().fetch(server + "/status/503")
    assert data == {"pdb_error": "IX-F member list URL returned HTTP status 503"}


def test_importer_fetch_rejects_non_object(server, monkeypatch):
    monkeypatch.setattr(ixf.ixf_fetch, "fetch_json", lambda url, **kwargs: [1, 2])
    data = ixf.Importer().fetch(server + "/feed.json")
    assert data == {"pdb_error": "IX-F data is not a JSON object"}


@pytest.fixture
def ixlan():
    org = Organization.objects.create(name="F3 Org", status="ok")
    ix = InternetExchange.objects.create(name="F3 Exchange", org=org, status="ok")
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://ixf.example/feed.json"
    ixlan.save()
    return ixlan


@pytest.fixture
def fetched(monkeypatch):
    monkeypatch.setattr(
        ixf.ixf_fetch, "fetch_json", lambda url, **kwargs: json.loads(FEED_BYTES)
    )


def test_cache_keyed_by_ixlan_with_ttl(ixlan, fetched, mocker):
    cache_set = mocker.spy(ixf.cache, "set")
    importer = ixf.Importer()
    importer.skip_import = True

    importer.update(ixlan, save=True)

    cache_set.assert_called_once()
    key, value = cache_set.call_args.args
    assert key == f"IXF-CACHE-ixlan-{ixlan.id}"
    assert value["url"] == "https://ixf.example/feed.json"
    assert value["data"]["member_list"] == FEED["member_list"]
    assert cache_set.call_args.kwargs["timeout"] == 3 * 24 * 3600
    assert ixlan.ixf_cached_data["member_list"] == FEED["member_list"]


def test_cache_not_written_by_preview(ixlan, fetched, mocker):
    cache_set = mocker.spy(ixf.cache, "set")

    ixf.Importer().update(ixlan, save=False)

    cache_set.assert_not_called()
    assert ixlan.ixf_cached_data is None


def test_cache_entry_ignored_after_url_change(ixlan, fetched):
    importer = ixf.Importer()
    importer.skip_import = True
    importer.update(ixlan, save=True)

    ixlan.ixf_ixp_member_list_url = "https://other.example/feed.json"
    assert ixlan.ixf_cached_data is None
    assert importer.fetch_cached(ixlan) == {
        "pdb_error": "IX-F data not locally cached for this resource yet."
    }


def test_cache_skips_oversized_data(ixlan, mocker):
    cache_set = mocker.spy(ixf.cache, "set")
    big = {"member_list": [], "pad": " " * 2048, "pdb_error": None}

    with override_settings(IXF_FETCH_MAX_BYTES=1024):
        ixf.Importer().cache_store(ixlan, ixlan.ixf_ixp_member_list_url, big)

    cache_set.assert_not_called()


@pytest.fixture(scope="module")
def internal_server():
    """
    Stands in for an internal host: allowed by nothing.
    """
    httpd = ThreadingHTTPServer(("127.0.0.2", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.2:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.mark.parametrize(
    "address,allowed",
    [
        ("8.8.8.8", True),
        ("2001:4860:4860::8888", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("100.64.0.1", False),
        ("169.254.169.254", False),
        ("0.0.0.0", False),
        ("224.0.1.1", False),
        ("240.0.0.1", False),
        ("255.255.255.255", False),
        ("::1", False),
        ("::", False),
        ("fe80::1", False),
        ("fd00:ec2::254", False),
        ("ff02::1", False),
        ("::ffff:127.0.0.1", False),
        ("::ffff:169.254.169.254", False),
        ("::ffff:8.8.8.8", True),
        ("64:ff9b::a9fe:a9fe", False),
        ("64:ff9b:1::a00:1", False),
        ("2002:7f00:1::", False),
        ("2001:0:4136:e378:8000:63bf:3fff:fdd2", False),
        ("2001:db8::1", False),
        ("fec0::1", False),
    ],
)
def test_address_allowed(address, allowed):
    # the real check, not the stub allowance
    assert ADDRESS_ALLOWED(ipaddress.ip_address(address)) is allowed


@pytest.mark.parametrize(
    "path",
    [
        "/redirect-to/http://127.0.0.2:{port}/feed.json",
        "/redirect-to/http://169.254.169.254/latest/meta-data/",
    ],
)
def test_redirect_to_internal_address_refused(server, internal_server, path):
    port = internal_server.rsplit(":", 1)[1]
    with pytest.raises(ixf_fetch.FetchError) as exc:
        fetch(server + path.format(port=port))
    assert str(exc.value) == "Could not connect to the IX-F member list URL"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.2:{port}/feed.json",
        "http://localhost:{port}/feed.json",
        "http://[::ffff:127.0.0.2]:{port}/feed.json",
        "http://[::1]:{port}/feed.json",
    ],
)
def test_internal_address_refused(internal_server, url):
    port = internal_server.rsplit(":", 1)[1]
    with pytest.raises(ixf_fetch.FetchError) as exc:
        fetch(url.format(port=port))
    assert str(exc.value) == "Could not connect to the IX-F member list URL"


def test_userinfo_refused(server):
    host = server.split("//", 1)[1]
    with pytest.raises(ixf_fetch.FetchError, match="username or password"):
        fetch(f"http://user:pw@{host}/feed.json")


def test_name_is_resolved_once_and_connection_pinned(server, monkeypatch):
    """
    The name resolves to the vetted address once; the connection goes to
    that address with the name in the Host header, so a second lookup
    (DNS rebinding) never happens.
    """
    port = server.rsplit(":", 1)[1]
    lookups = []
    real = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        lookups.append(host)
        if host == "feed.ixf.test":
            return real("127.0.0.1", *args, **kwargs)
        return real(host, *args, **kwargs)

    monkeypatch.setattr(ixf_fetch.socket, "getaddrinfo", getaddrinfo)
    HOSTS.clear()

    assert fetch(f"http://feed.ixf.test:{port}/feed.json") == FEED
    # urllib3 passes the pinned address through getaddrinfo too, which
    # is not a DNS lookup
    assert [host for host in lookups if host != "127.0.0.1"] == ["feed.ixf.test"]
    assert HOSTS == [f"feed.ixf.test:{port}"]


def test_any_internal_address_refuses_the_host(monkeypatch):
    def getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port)),
        ]

    monkeypatch.setattr(ixf_fetch.socket, "getaddrinfo", getaddrinfo)

    with pytest.raises(ixf_fetch.FetchError, match="Could not connect"):
        fetch("http://mixed.ixf.test/feed.json")


@pytest.mark.parametrize(
    "url,message",
    [
        ("ftp://ixf.example/feed.json", "must use http or https"),
        ("https://user:pw@ixf.example/feed.json", "username or password"),
        ("http://127.0.0.2/feed.json", "public addresses"),
        ("http://169.254.169.254/latest/meta-data/", "public addresses"),
        ("http://[fd00:ec2::254]/", "public addresses"),
        ("http://does-not-resolve.invalid/feed.json", "public addresses"),
        ("http://:80/feed.json", "not valid"),
    ],
)
def test_check_url(url, message):
    with pytest.raises(ixf_fetch.FetchError, match=message):
        ixf_fetch.check_url(url)


def test_check_url_public_host(monkeypatch):
    monkeypatch.setattr(
        ixf_fetch.socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.43.10", port))
        ],
    )
    ixf_fetch.check_url("https://ixf.example/feed.json")


RAW_RESPONSES = {
    "/banner": b"SSH-2.0-fake-banner\r\n",
    "/bad-status": b"HTTP/1.1 abc OK\r\n\r\n",
    "/many-headers": b"HTTP/1.1 200 OK\r\n"
    + b"".join(b"X-H%d: a\r\n" % i for i in range(150))
    + b"\r\n{}",
    "/bad-location": b"HTTP/1.1 302 Found\r\nLocation: http://[\r\n"
    b"Content-Length: 0\r\n\r\n",
    "/odd-length": "HTTP/1.1 200 OK\r\nContent-Length: \u00b2\r\n"
    "Connection: close\r\n\r\n{}".encode(),
    "/huge-length": b"HTTP/1.1 200 OK\r\nContent-Length: "
    + b"9" * 5000
    + b"\r\n\r\n{}",
}


class RawHandler(socketserver.BaseRequestHandler):
    """
    Answers with exact bytes, for responses http.server can't produce.
    """

    def handle(self):
        request = b""
        while b"\r\n\r\n" not in request:
            data = self.request.recv(4096)
            if not data:
                return
            request += data
        path = request.split(b" ")[1].decode()
        try:
            if path == "/header-trickle":
                self.request.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                for _ in range(100):
                    self.request.sendall(b"a")
                    time.sleep(0.5)
            elif path in RAW_RESPONSES:
                self.request.sendall(RAW_RESPONSES[path])
            elif path in ("/close-trailers", "/keepalive-trailers"):
                close = b"Connection: close\r\n" if path == "/close-trailers" else b""
                self.request.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    + close
                    + b"Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n"
                )
                for _ in range(100):
                    self.request.sendall(b"X-Trailer: a\r\n")
                    time.sleep(0.2)
        except OSError:
            pass


@pytest.fixture(scope="module")
def raw_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), RawHandler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.mark.parametrize(
    "path,message",
    [
        ("/banner", "returned an invalid response"),
        ("/bad-status", "returned an invalid response"),
        ("/many-headers", "returned an invalid response"),
        ("/bad-location", "returned a bad redirect"),
        ("/huge-length", "exceeds the size limit"),
    ],
)
def test_malformed_response_fixed_message(raw_server, path, message):
    with pytest.raises(ixf_fetch.FetchError, match=message) as exc:
        fetch(raw_server + path)
    assert "SSH" not in str(exc.value)
    assert "127.0.0.1" not in str(exc.value)


def test_unparseable_content_length_is_ignored(raw_server):
    assert fetch(raw_server + "/odd-length") == {}


def test_importer_records_banner_as_fixed_error(raw_server):
    data = ixf.Importer().fetch(raw_server + "/banner")
    assert data == {"pdb_error": "IX-F member list URL returned an invalid response"}


@pytest.mark.parametrize("path", ["/close-trailers", "/keepalive-trailers"])
def test_deadline_holds_for_endless_trailers(raw_server, path):
    start = time.monotonic()
    with pytest.raises(ixf_fetch.FetchError, match="timed out"):
        fetch(raw_server + path, timeout=1.5)
    assert time.monotonic() - start < 3


def test_refused_fetch_leaves_no_watchdog_running(server, internal_server, monkeypatch):
    timers = []
    timer = ixf_fetch.threading.Timer

    def record(*args, **kwargs):
        timers.append(timer(*args, **kwargs))
        return timers[-1]

    monkeypatch.setattr(ixf_fetch.threading, "Timer", record)
    port = internal_server.rsplit(":", 1)[1]

    for url in (
        server + "/redirect-ftp",
        f"http://127.0.0.2:{port}/feed.json",
        "http://user:pw@127.0.0.1/feed.json",
    ):
        with pytest.raises(ixf_fetch.FetchError):
            fetch(url, timeout=30)

    assert timers
    assert all(t.finished.is_set() for t in timers)


def test_multi_member_gzip(server):
    assert fetch(server + "/gzip-members.json") == FEED


def test_truncated_gzip_refused(server):
    with pytest.raises(ixf_fetch.FetchError, match="invalid compressed data"):
        fetch(server + "/gzip-truncated.json")


@pytest.fixture
def stub_names(monkeypatch):
    """
    Names ending in .ixf.test resolve to the stub server's address.
    """
    real = socket.getaddrinfo
    lookups = []

    def getaddrinfo(host, *args, **kwargs):
        lookups.append(host)
        if host.endswith(".ixf.test") or host.endswith(".xn--zckzah"):
            return real("127.0.0.1", *args, **kwargs)
        return real(host, *args, **kwargs)

    monkeypatch.setattr(ixf_fetch.socket, "getaddrinfo", getaddrinfo)
    return lookups


def test_idn_host_is_encoded(server, stub_names):
    port = server.rsplit(":", 1)[1]
    HOSTS.clear()

    assert fetch(f"http://\u4f8b\u3048.\u30c6\u30b9\u30c8:{port}/feed.json") == FEED
    assert HOSTS == [f"xn--r8jz45g.xn--zckzah:{port}"]
    assert "xn--r8jz45g.xn--zckzah" in stub_names


def test_trailing_dot_host(server, stub_names):
    port = server.rsplit(":", 1)[1]
    HOSTS.clear()

    assert fetch(f"http://feed.ixf.test.:{port}/feed.json") == FEED
    assert HOSTS == [f"feed.ixf.test:{port}"]


def test_non_ascii_path_is_percent_encoded(server):
    PATHS.clear()

    assert fetch(server + "/caf\u00e9.json?a=%20b") == FEED
    assert PATHS == ["/caf%C3%A9.json?a=%20b"]


def test_invalid_idn_host_refused():
    with pytest.raises(ixf_fetch.FetchError, match="not valid"):
        fetch("http://xn--\u00e9\u00e9.example/feed.json")


@pytest.fixture(scope="module")
def tls_server(tmp_path_factory):
    """
    An https stub with a certificate for feed.ixf.test, signed by a CA made
    for the test.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    path = tmp_path_factory.mktemp("tls")
    now = datetime.datetime.now(datetime.UTC)

    def name(common_name):
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name("ixf test ca"))
        .issuer_name(name("ixf test ca"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(name("feed.ixf.test"))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("feed.ixf.test")]), False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_file = path / "ca.pem"
    ca_file.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_file = path / "cert.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file = path / "key.pem"
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    server_names = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    context.sni_callback = lambda sock, server_name, ctx: server_names.append(
        server_name
    )

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield {
        "port": httpd.server_address[1],
        "ca": str(ca_file),
        "server_names": server_names,
    }
    httpd.shutdown()


def test_https_pinned_with_name_for_sni_host_and_certificate(
    tls_server, stub_names, monkeypatch
):
    monkeypatch.setattr(ixf_fetch, "ca_bundle", lambda: tls_server["ca"])
    port = tls_server["port"]
    HOSTS.clear()
    tls_server["server_names"].clear()

    assert fetch(f"https://feed.ixf.test:{port}/feed.json") == FEED
    assert tls_server["server_names"] == ["feed.ixf.test"]
    assert HOSTS == [f"feed.ixf.test:{port}"]


def test_https_name_mismatch_refused(tls_server, stub_names, monkeypatch):
    monkeypatch.setattr(ixf_fetch, "ca_bundle", lambda: tls_server["ca"])
    port = tls_server["port"]

    with pytest.raises(ixf_fetch.FetchError, match="Could not connect"):
        fetch(f"https://other.ixf.test:{port}/feed.json")


def test_gzip_member_with_one_stray_byte(server):
    assert fetch(server + "/gzip-stray-byte.json") == FEED


def test_slow_but_steady_feed_within_deadline(server):
    start = time.monotonic()
    assert (
        ixf_fetch.fetch_json(
            server + "/slow-steady.json", timeout=10, read_timeout=2, max_bytes=LIMIT
        )
        == FEED
    )
    # longer in total than any one read may wait
    assert time.monotonic() - start > 3


def test_slow_but_steady_feed_past_deadline(server):
    with pytest.raises(ixf_fetch.FetchError, match="timed out"):
        ixf_fetch.fetch_json(
            server + "/slow-steady.json", timeout=2.5, read_timeout=2, max_bytes=LIMIT
        )


def test_importer_uses_deadline_setting_for_slow_feed(server, settings):
    settings.IXF_FETCH_TIMEOUT = 2
    settings.IXF_FETCH_DEADLINE = 10

    data = ixf.Importer().fetch(server + "/slow-steady.json")

    assert data["member_list"] == FEED["member_list"]
    assert not data.get("pdb_error")


def test_importer_deadline_argument(server, settings):
    settings.IXF_FETCH_DEADLINE = 60

    data = ixf.Importer().fetch(server + "/slow-steady.json", deadline=1)

    assert data == {"pdb_error": "Request to the IX-F member list URL timed out"}


def test_deadline_passed_during_connect_is_enforced(raw_server, monkeypatch):
    """
    Connect (and for https the TLS handshake) can use up the deadline before
    the watchdog has a socket; the header phase must not run on after it.
    """
    connect = ixf_fetch.urllib3.connection.HTTPConnection.connect

    def slow_connect(self):
        time.sleep(1.3)
        connect(self)

    monkeypatch.setattr(
        ixf_fetch.urllib3.connection.HTTPConnection, "connect", slow_connect
    )
    start = time.monotonic()
    with pytest.raises(ixf_fetch.FetchError, match="timed out"):
        ixf_fetch.fetch_json(
            raw_server + "/header-trickle", timeout=1, read_timeout=1, max_bytes=LIMIT
        )
    # deadline plus at most one idle period
    assert time.monotonic() - start < 2.5
