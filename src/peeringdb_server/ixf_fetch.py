"""
Bounded retrieval of IX-F member exports.

The URL is supplied by exchange administrators, so it may only point at
public addresses: every host, redirects included, is resolved and checked,
and the connection goes to the checked address. The response is read with a
byte budget on the decoded body and an overall deadline, and only parsed once
it is complete.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import threading
import time
import zlib
from collections.abc import Callable
from typing import NamedTuple, NoReturn
from urllib.parse import urljoin, urlsplit

import idna
import structlog
import urllib3
import urllib3.connection
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from requests.certs import where as ca_bundle
from requests.utils import requote_uri

log = structlog.get_logger("django")

CHUNK_SIZE = 64 * 1024
MAX_REDIRECTS = 3

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# translation prefixes reach IPv4 space through a gateway, so whatever they
# embed cannot be checked here
BLOCKED_NETWORKS = (
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64, RFC 6052
    ipaddress.ip_network("64:ff9b:1::/48"),  # local-use NAT64, RFC 8215
    ipaddress.ip_network("2002::/16"),  # 6to4
    ipaddress.ip_network("2001::/32"),  # Teredo
    ipaddress.ip_network("fec0::/10"),  # deprecated site-local
)


class FetchError(Exception):
    """
    The IX-F export could not be retrieved.

    The message is shown to users and mailed to the exchange, so it never
    carries connection details; those are only logged.
    """


def _connect_error() -> FetchError:
    return FetchError(_("Could not connect to the IX-F member list URL"))


def address_allowed(address: IPAddress) -> bool:
    """
    Return whether an IX-F export may be fetched from this address.
    """

    if isinstance(address, ipaddress.IPv6Address):
        if any(address in network for network in BLOCKED_NETWORKS):
            return False
        if address.ipv4_mapped:
            address = address.ipv4_mapped

    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False

    return address.is_global


class _Target(NamedTuple):
    scheme: str
    host: str  # ascii, IDNA-encoded, without a trailing dot
    port: int
    host_header: str
    path: str  # path and query, percent-encoded


def _split(url: str) -> _Target:
    """
    Check the parts of the URL that need no lookup and return what the
    request is made of.
    """

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise FetchError(_("IX-F member list URL is not valid"))

    if parts.scheme not in ("http", "https"):
        raise FetchError(_("IX-F member list URL must use http or https"))

    if parts.username is not None or parts.password is not None:
        raise FetchError(
            _("IX-F member list URL must not contain a username or password")
        )

    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise FetchError(_("IX-F member list URL is not valid"))

    # the same encoding requests applies, so names in other scripts keep
    # working for the lookup, the Host header and the certificate check
    if not host.isascii():
        try:
            host = idna.encode(host, uts46=True).decode("ascii")
        except (idna.IDNAError, UnicodeError):
            raise FetchError(_("IX-F member list URL is not valid"))

    host_header = f"[{host}]" if ":" in host else host
    if port is not None:
        host_header = f"{host_header}:{port}"

    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    return _Target(
        scheme=parts.scheme,
        host=host,
        port=port or (443 if parts.scheme == "https" else 80),
        host_header=host_header,
        path=requote_uri(path),
    )


def _resolve(host: str, port: int) -> list[str]:
    """
    Resolve the host and return its addresses, all of them checked.

    Raises LookupError when the host does not resolve or any address is
    not allowed; the caller decides what the user sees.
    """

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise LookupError(f"{host}: {exc}")

    addresses: list[str] = []
    for info in infos:
        # strip an IPv6 zone id, link-local addresses are refused anyway
        address = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        # a host with one internal address could be steered to it
        if not address_allowed(address):
            raise LookupError(f"{host}: {address} is not allowed")
        if str(address) not in addresses:
            addresses.append(str(address))

    if not addresses:
        raise LookupError(f"{host}: no addresses")

    return addresses


def check_url(url: str) -> None:
    """
    Check an IX-F member list URL when it is saved.

    Raises FetchError with a message for the user. A host that does not
    resolve gets the same message as one that resolves to an address that
    is not allowed, so the check does not tell internal names apart.
    """

    target = _split(url)
    try:
        _resolve(target.host, target.port)
    except LookupError as exc:
        log.info("ixf_url_refused", url=url, error=str(exc))
        raise FetchError(
            _("IX-F member list URL must point to a host with public addresses")
        )


def fetch_json(
    url: str,
    timeout: float,
    max_bytes: int | None = None,
    read_timeout: float = 10,
) -> object:
    """
    Retrieve the IX-F export at `url` and return the parsed JSON.

    Arguments:
        - url: http(s) URL of the export
        - timeout: seconds the whole retrieval may take, redirects included
        - read_timeout: seconds a connect or a single read may wait for data
        - max_bytes: limit for the decoded body, defaults to IXF_FETCH_MAX_BYTES

    Raises FetchError.
    """

    if max_bytes is None:
        max_bytes = settings.IXF_FETCH_MAX_BYTES

    deadline = time.monotonic() + timeout
    try:
        body = _retrieve(url, deadline, max_bytes, read_timeout)
    except FetchError:
        raise
    except Exception as exc:
        # anything a hostile server can provoke beyond the cases mapped
        # below still ends in a fixed message
        log.warning("ixf_fetch_error", url=url, error=repr(exc))
        raise _invalid_response()

    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        raise FetchError(_("No JSON could be parsed"))


def _retrieve(url: str, deadline: float, max_bytes: int, read_timeout: float) -> bytes:
    # redirects are followed here, not by urllib3, so every hop is checked
    for _hop in range(MAX_REDIRECTS + 1):
        watchdog = _Watchdog(deadline)
        conn = response = None
        try:
            conn, response = _open(url, deadline, watchdog, read_timeout)

            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                try:
                    url = urljoin(url, location or "")
                except ValueError:
                    location = None
                if not location:
                    raise FetchError(_("IX-F member list URL returned a bad redirect"))
                continue

            if response.status != 200:
                raise FetchError(
                    _("IX-F member list URL returned HTTP status {}").format(
                        response.status
                    )
                )

            body = _read_body(response, watchdog, deadline, max_bytes, read_timeout)
            # a body cut short by the watchdog reads as a clean end
            if watchdog.fired:
                raise _timeout_error()
            return body
        except FetchError:
            if watchdog.fired:
                raise _timeout_error()
            raise
        finally:
            watchdog.cancel()
            # closed, not drained: the rest of an oversized body is never read
            if response is not None:
                response.close()
            if conn is not None:
                conn.close()

    raise FetchError(_("IX-F member list URL redirected too many times"))


class _Watchdog:
    """
    Shuts the connection's socket down when the deadline passes.

    Socket timeouts only bound a single receive, while http.client reads the
    status line, headers, chunk sizes and trailers in loops of its own (and
    skips any number of 100 Continue responses), so a server sending a byte
    at a time could otherwise hold a fetch open for good.

    The socket is kept from right after connecting: for a response that
    closes the connection, http.client hands the socket to the response and
    the connection no longer has it.
    """

    def __init__(self, deadline: float) -> None:
        self.fired = False
        self.sock: socket.socket | None = None
        self.timer = threading.Timer(max(0.0, deadline - time.monotonic()), self._fire)
        self.timer.daemon = True
        self.timer.start()

    def _fire(self) -> None:
        self.fired = True
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def cancel(self) -> None:
        self.timer.cancel()


def _timeout_error() -> FetchError:
    return FetchError(_("Request to the IX-F member list URL timed out"))


def _invalid_response() -> FetchError:
    return FetchError(_("IX-F member list URL returned an invalid response"))


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _timeout_error()
    return remaining


def _open(
    url: str, deadline: float, watchdog: _Watchdog, read_timeout: float
) -> tuple[urllib3.connection.HTTPConnection, urllib3.BaseHTTPResponse]:
    """
    Send the request to the first checked address of the URL's host that
    accepts a connection. The connection goes to that address, while the
    Host header, SNI and certificate check use the name from the URL, so the
    name is not resolved a second time.
    """

    target = _split(url)

    try:
        addresses = _resolve(target.host, target.port)
    except LookupError as exc:
        log.info("ixf_fetch_refused", url=url, error=str(exc))
        raise _connect_error()

    headers = {
        "Host": target.host_header,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": "PeeringDB IX-F Importer",
    }

    for address in addresses:
        timeout = min(read_timeout, _remaining(deadline))
        conn: urllib3.connection.HTTPConnection
        if target.scheme == "https":
            conn = urllib3.connection.HTTPSConnection(
                address,
                target.port,
                timeout=timeout,
                cert_reqs="CERT_REQUIRED",
                ca_certs=ca_bundle(),
                server_hostname=target.host,
                assert_hostname=target.host,
            )
        else:
            conn = urllib3.connection.HTTPConnection(
                address, target.port, timeout=timeout
            )

        try:
            conn.connect()
        except urllib3.exceptions.NewConnectionError as exc:
            # checked first: urllib3 derives it from ConnectTimeoutError.
            # The next address may still work (no IPv6 route, for one)
            conn.close()
            log.info("ixf_fetch_connect_error", url=url, error=str(exc))
            continue
        except Exception as exc:
            conn.close()
            _raise_open_error(url, exc, watchdog)

        # assigned before the check, so a watchdog firing in between still
        # finds the socket; one that fired during connect or the TLS
        # handshake had none to shut down
        watchdog.sock = conn.sock
        if watchdog.fired:
            conn.close()
            raise _timeout_error()

        try:
            conn.request(
                "GET",
                target.path,
                headers=headers,
                preload_content=False,
                decode_content=False,
            )
            return conn, conn.getresponse()
        except Exception as exc:
            conn.close()
            _raise_open_error(url, exc, watchdog)

    raise _connect_error()


def _raise_open_error(url: str, exc: Exception, watchdog: _Watchdog) -> NoReturn:
    if watchdog.fired or isinstance(
        exc, (urllib3.exceptions.TimeoutError, TimeoutError)
    ):
        log.info("ixf_fetch_timeout", url=url, error=str(exc))
        raise _timeout_error()
    if isinstance(exc, http.client.HTTPException):
        # not HTTP at all (a banner), a bad status line, too many headers
        log.info("ixf_fetch_invalid_response", url=url, error=repr(exc))
        raise _invalid_response()
    if isinstance(exc, (urllib3.exceptions.HTTPError, OSError, ValueError)):
        log.info("ixf_fetch_connect_error", url=url, error=str(exc))
        raise _connect_error()
    log.warning("ixf_fetch_error", url=url, error=repr(exc))
    raise _invalid_response()


def _too_large(max_bytes: int) -> FetchError:
    return FetchError(
        _("IX-F data exceeds the size limit of {} bytes").format(max_bytes)
    )


def _read_body(
    response: urllib3.BaseHTTPResponse,
    watchdog: _Watchdog,
    deadline: float,
    max_bytes: int,
    read_timeout: float,
) -> bytes:
    content_length = response.headers.get("Content-Length", "")
    # http.client ignores a length it can't parse, the budget still applies
    if re.fullmatch(r"[0-9]+", content_length) and (
        len(content_length) > 20 or int(content_length) > max_bytes
    ):
        raise _too_large(max_bytes)

    encoding = response.headers.get("Content-Encoding", "").strip().lower()
    if encoding in ("", "identity"):
        decoder = None
    elif encoding in ("gzip", "x-gzip", "deflate"):
        decoder = _Decoder()
    else:
        raise FetchError(_("IX-F member list URL used an unsupported encoding"))

    chunks: list[bytes] = []
    size = 0
    received = 0

    def append(data: bytes) -> None:
        nonlocal size
        size += len(data)
        if size > max_bytes:
            raise _too_large(max_bytes)
        chunks.append(data)

    try:
        while True:
            remaining = _remaining(deadline)
            if watchdog.sock is not None:
                try:
                    watchdog.sock.settimeout(min(read_timeout, remaining))
                except OSError:
                    # http.client closed it after the last byte of the body
                    pass

            # read1 returns what one receive gets, read() would block
            # until the whole chunk has arrived
            raw = response.read1(CHUNK_SIZE, decode_content=False)
            if not raw:
                break

            # compressed input is held to the same budget, it never needs more
            received += len(raw)
            if received > max_bytes:
                raise _too_large(max_bytes)

            if decoder is None:
                append(raw)
            elif not decoder.feed(raw, append, lambda: max_bytes - size + 1):
                break

        if decoder is not None:
            decoder.finish(append, lambda: max_bytes - size + 1)
    except FetchError:
        raise
    except zlib.error as exc:
        log.info("ixf_fetch_decode_error", error=str(exc))
        raise FetchError(_("IX-F member list URL sent invalid compressed data"))
    except urllib3.exceptions.TimeoutError as exc:
        log.info("ixf_fetch_timeout", error=str(exc))
        raise _timeout_error()
    except (urllib3.exceptions.HTTPError, OSError) as exc:
        log.info("ixf_fetch_read_error", error=str(exc))
        raise FetchError(_("Could not read from the IX-F member list URL"))
    except http.client.HTTPException as exc:
        log.info("ixf_fetch_invalid_response", error=repr(exc))
        raise _invalid_response()

    return b"".join(chunks)


class _Decoder:
    """
    gzip or deflate decoding with bounded output per call.

    Several gzip members follow each other the way urllib3 handles them:
    data after a complete member starts the next one, and data that is not
    a member after the first ends the body.
    """

    def __init__(self) -> None:
        # wbits 32 + MAX_WBITS detects the gzip or zlib header
        self.zobj = zlib.decompressobj(32 + zlib.MAX_WBITS)
        self.members = 1
        self.done = False

    def feed(
        self, data: bytes, append: Callable[[bytes], None], room: Callable[[], int]
    ) -> bool:
        """
        Decode `data`, passing output to `append`; `room` returns how much
        output may come next. Returns False once nothing more is wanted.
        """
        while data and not self.done:
            if self.zobj.eof:
                self.zobj = zlib.decompressobj(32 + zlib.MAX_WBITS)
                self.members += 1
            try:
                # bounded output per call, the rest stays in unconsumed_tail
                append(self.zobj.decompress(data, room()))
            except zlib.error:
                if self.members == 1:
                    raise
                self.done = True
                break
            data = self.zobj.unconsumed_tail or self.zobj.unused_data
        return not self.done

    def finish(self, append: Callable[[bytes], None], room: Callable[[], int]) -> None:
        # output zlib still holds back once all input is consumed
        while not self.done and (data := self.zobj.decompress(b"", room())):
            append(data)
        # only the first member has to be complete: like urllib3, whatever
        # follows it may be trailing garbage
        if not self.done and not self.zobj.eof and self.members == 1:
            raise zlib.error("truncated compressed stream")
