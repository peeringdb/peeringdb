"""
IRR lookup service (#1973).

The format-only `validate_irr_as_set` (validators.py) cannot answer the two
questions the unambiguous-as-set work needs:

- sources_for(name)      — which registries hold object X? (editor completions
                           and the cleanup's found-in-one / many / nowhere split)
- exists_in(source, name) — does object X exist in registry S? (the save-path
                           live check and the periodic re-verification)

Both are answered against a configurable pool of full-mirror IRRd servers
(settings.IRR_LOOKUP_SERVERS), queried over port 43 with IRRd's `!` protocol.
Existence checks pin one source; source completion sends one source-pinned check
per mirrored source over a single connection to each mirror, and falls back to
separate pinned checks for any source whose answer is cut off or unrecognized.
Results are cached in the "negative" (Redis) cache for
settings.IRR_LOOKUP_CACHE_TTL seconds.

Every outbound path fails open: a query that errors, times out, or returns an
unrecognized response yields an "unknown" result — exists_in returns None and
sources_for returns ok=False — and never raises. A third-party IRR outage must
not block a save or the editor. Callers decide policy: the save path rejects only
a definitive False (provably absent), accepting None.

Correctness note: a query naming a source the server does not mirror fails as a
whole, with "%% ERROR" over whois and F for `!s`. So sources_for asks a server
only for the sources it actually carries, per the server's !s-lc mirror list
(also the basis of coverage_report()), and reads every error reply as unknown,
never as absent (#502).
"""

import re
import socket
import time
from collections import namedtuple

from django.conf import settings
from django.core.cache import caches

from peeringdb_server.inet import IRR_SOURCE

# Result of a sources_for() lookup. `sources` is the frozenset of IRR_SOURCE
# registries found to hold the object; `ok` is False when the pool could not be
# reached at all (so an empty `sources` means "unknown", not "found nowhere").
LookupResult = namedtuple("LookupResult", ["sources", "ok"])

# A safe object key: the tokens we look up are already format-validated upstream,
# but irr.py is a library — reject anything that could break out of the whois
# command line (whitespace / control chars) before it hits a socket. The length is
# capped at what Network.irr_as_set can hold, since a lookup now sends the name
# once per mirrored source.
_SAFE_KEY = re.compile(r"[A-Z0-9_:.-]{1,255}")


def _object_class(name):
    """Infer the RPSL object class to query for a single as-set token."""
    if re.fullmatch(r"AS[0-9]+", name):
        return "aut-num"
    # A route-set name starts with RS-, alone or as a component of a hierarchical
    # name; as-sets such as AS-FOO-CUSTOMERS-V4 merely contain it (#499).
    if any(part.startswith("RS-") for part in name.split(":")):
        return "route-set"
    return "as-set"


def _cache():
    return caches["negative"]


def _timeout(server):
    return server.get("timeout", settings.IRR_LOOKUP_DEFAULT_TIMEOUT)


def _deadline(deadline=None):
    """The end of a lookup's budget, and no later than a caller's deadline."""
    end = time.monotonic() + settings.IRR_LOOKUP_BUDGET
    return end if deadline is None else min(end, deadline)


def _down_key(server):
    return f"irr:down:{server['host']}:{server.get('port', 43)}"


def _send(server, payload, deadline=None):
    """
    Send one query (whois or `!` protocol) to an IRRd server on port 43 and
    return the decoded response text. Raises OSError (incl. TimeoutError) on
    any network failure — callers translate that into a fail-open "unknown".

    The whole exchange, name resolution excepted, has to finish within the
    server's timeout, and before `deadline` (a time.monotonic() value) when
    given. A mirror whose exchange ran out of its own time is skipped for
    IRR_LOOKUP_MIRROR_DOWN_TTL seconds.
    """
    if _cache().get(_down_key(server)):
        raise TimeoutError("mirror recently timed out")
    end = time.monotonic() + _timeout(server)
    own_time = deadline is None or end <= deadline
    if not own_time:
        end = deadline

    def time_left():
        left = end - time.monotonic()
        if left <= 0:
            raise TimeoutError("lookup ran out of time")
        return left

    try:
        return _exchange(server, payload, time_left)
    except TimeoutError:
        if own_time:
            _cache().set(
                _down_key(server), True, timeout=settings.IRR_LOOKUP_MIRROR_DOWN_TTL
            )
        raise


def _connect(host, port, time_left):
    """
    Connect to the first address of `host` that answers, every attempt within
    the time left: create_connection would give each address the whole
    timeout. Name resolution itself is not bounded.
    """
    # no name lookup once the time is up
    time_left()
    error = None
    for family, kind, proto, _, address in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    ):
        timeout = time_left()
        sock = None
        try:
            # an address family the host can't use moves on to the next address
            sock = socket.socket(family, kind, proto)
            sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError as exc:
            if sock is not None:
                sock.close()
            error = exc
    if error is None:
        raise OSError(f"no address for {host}")
    raise error


def _exchange(server, payload, time_left):
    host = server["host"]
    port = server.get("port", 43)
    sock = _connect(host, port, time_left)
    try:
        sock.settimeout(time_left())
        sock.sendall((payload + "\r\n").encode("ascii", "ignore"))
        chunks = []
        total = 0
        cap = settings.IRR_LOOKUP_MAX_RESPONSE_BYTES
        while True:
            sock.settimeout(time_left())
            data = sock.recv(min(4096, cap - total))
            if not data:
                break
            chunks.append(data)
            total += len(data)
            # We only ever need the leading bytes (status lines, the first RPSL
            # lines, or the short `!s-lc` listing). Cap the read so a huge as-set object with tens of
            # thousands of `members:` lines can't blow up memory or wall-time.
            if total >= cap:
                break
        # surrogateescape keeps undecodable bytes recoverable, so A<len> byte
        # counts still line up when _read_statuses re-encodes the reply
        return b"".join(chunks).decode("utf-8", "surrogateescape")
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _server_sources(server, deadline=None):
    """
    The set of IRR sources a server mirrors, via IRRd's !s-lc command (response
    shape "A<len>\\n<comma,list>\\nC"). Cached; None on failure.
    """
    cache_key = f"irr:srcs:{server['host']}:{server.get('port', 43)}"
    cached = _cache().get(cache_key)
    if cached is not None:
        return frozenset(cached)
    try:
        text = _send(server, "!s-lc", deadline)
    except OSError:
        return None
    # read by its framing: the list is data, and a source name such as ARIN or
    # CANARIE starts with a status letter (#543)
    body = _block_body(text)
    if body is None:
        return None
    sources = frozenset(s.strip().upper() for s in body.split(",") if s.strip())
    if not sources:
        return None
    _cache().set(cache_key, list(sources), timeout=settings.IRR_LOOKUP_CACHE_TTL)
    return sources


def _block_body(text):
    """
    The data of a reply that is exactly one A<len> block closed by C, or None.

    A<len> counts the data and the newline after it.
    """
    raw = text.encode("utf-8", "surrogateescape")
    header, _, rest = raw.partition(b"\n")
    length = re.fullmatch(rb"A([0-9]{1,9})", header.strip())
    if not length:
        return None
    size = int(length.group(1))
    body, trailer = rest[:size], rest[size:]
    if len(body) < size or not body.endswith(b"\n") or trailer.strip() != b"C":
        return None
    return body.decode("utf-8", "replace")


def _exact_key(object_class, name):
    """The key `!m` matches exactly: whois normalized AS0003333 to AS3333."""
    if object_class == "aut-num" and re.fullmatch(r"AS[0-9]+", name):
        return "AS" + (name[2:].lstrip("0") or "0")
    return name


def _read_statuses(text):
    """
    Split a pipelined `!` protocol reply into one status per command.

    A<len> (found; its object follows and is skipped by its byte length), C, D
    and F. Reading stops at the first incomplete or unrecognized reply, since
    nothing after it can be matched to its command anymore.
    """
    raw = text.encode("utf-8", "surrogateescape")
    statuses = []
    position = 0
    while True:
        end = raw.find(b"\n", position)
        if end < 0:
            return statuses
        line = raw[position:end].strip()
        position = end + 1
        if not line:
            continue
        # a count no reply under the read cap can have; int() also refuses one
        # past 4300 digits
        length = re.fullmatch(rb"A([0-9]{1,9})", line)
        if length:
            # A<len> counts the object and the newline after it, so a count that
            # does not land on a line start is out of step with the reply
            position += int(length.group(1))
            end = raw.find(b"\n", position)
            if (
                end < 0
                or raw[position - 1 : position] != b"\n"
                or raw[position:end].rstrip(b"\r") != b"C"
            ):
                return statuses
            position = end + 1
            statuses.append("A")
        elif line in (b"C", b"D"):
            statuses.append(line.decode())
        elif line[:1] == b"F":
            statuses.append("F")
        else:
            return statuses


def _pinned_exists(server, source, object_class, name, deadline=None):
    """
    Does `name` exist in `source` per this server? True/False when the server
    answers definitively, None on error or an unrecognized response.

    Asked over IRRd's `!` protocol rather than whois (#499): there an error reply
    ("%% ERROR: ...") starts with "%" just like "no entries", while here they are
    distinct status lines -- A<len> found, C/D no data, F error. Reads only the
    status lines, never the (potentially huge) object.
    """
    name = _exact_key(object_class, name)
    query = "\n".join(["!!", f"!s{source}", f"!m{object_class},{name}", "!q"])
    try:
        text = _send(server, query, deadline)
    except OSError:
        return None
    statuses = [line.strip() for line in text.splitlines() if line.strip()][:2]
    # `!s` must succeed: when it fails IRRd keeps its default sources and `!m`
    # answers from any registry
    if len(statuses) < 2 or statuses[0] != "C":
        return None
    if statuses[1] in ("C", "D"):
        return False
    if re.fullmatch(r"A[0-9]+", statuses[1]):
        return True
    return None


def _sources_on_server(server, mirrored_sources, object_class, name, deadline=None):
    """
    Ask one mirror about `name` in each of `mirrored_sources`, over one connection.

    Returns {source: bool} for the sources it answered definitively, which can be
    fewer than asked or none; sources_for checks the rest with separate pinned
    queries.

    Each source gets its own `!s<source>` + `!m` pair because `!m` returns only
    the first matching object, so one `!m` over a list of sources would hide every
    registry but one. Statuses are read as in _pinned_exists: `!s` must answer C
    (when it fails, the `!m` after it answers from the previous selection), then
    A<len> is found, C or D absent, and F unknown. The object text counts toward
    the read cap, so a large object cuts off the answers that follow it.
    """
    sources = sorted(mirrored_sources)
    key = _exact_key(object_class, name)
    query = ["!!"]
    for source in sources:
        query += [f"!s{source}", f"!m{object_class},{key}"]
    query.append("!q")
    try:
        text = _send(server, "\n".join(query), deadline)
    except OSError:
        return {}

    statuses = _read_statuses(text)
    answers = {}
    for source, select, match in zip(sources, statuses[0::2], statuses[1::2]):
        if select != "C" or match == "F":
            continue
        answers[source] = match == "A"
    return answers


def exists_in(source, name, object_class=None, deadline=None):
    """
    Whether object `name` exists in registry `source`.

    Returns True (present), False (provably absent), or None (unknown — lookup
    infrastructure could not answer; callers fail open). `source` must be one of
    IRR_SOURCE.

    Spends at most IRR_LOOKUP_BUDGET seconds, and stops at `deadline` (a
    time.monotonic() value) when that comes first, so several calls can share
    one budget.
    """
    source = source.upper()
    name = name.upper()
    if source not in IRR_SOURCE or not _SAFE_KEY.fullmatch(name):
        return None
    object_class = object_class or _object_class(name)

    cache_key = f"irr:exists:{source}:{object_class}:{name}"
    cached = _cache().get(cache_key)
    if cached is not None:
        return cached

    deadline = _deadline(deadline)
    for server in settings.IRR_LOOKUP_SERVERS:
        mirrored = _server_sources(server, deadline)
        if mirrored is not None and source not in mirrored:
            # This server does not carry `source`; its "no entries" would be a
            # false absent, so skip it entirely.
            continue
        result = _pinned_exists(server, source, object_class, name, deadline)
        if result is None:
            continue
        if result is False and mirrored is None:
            # Mirror list unknown (server reachable but its !s-lc was empty/
            # unparseable): we cannot confirm this server actually carries
            # `source`, so a "no entries" here may be a false absent. Trust only
            # a definitive True from such a server; treat its False as unknown
            # and keep looking. Rejecting on it would contradict the caller
            # policy that only a provably-absent object is refused.
            continue
        # Definitive answer — cache and return it.
        _cache().set(cache_key, result, timeout=settings.IRR_LOOKUP_CACHE_TTL)
        return result

    # No server could answer definitively (all errored, or none mirror `source`).
    return None


def sources_for(name, object_class=None, deadline=None):
    """
    Which IRR_SOURCE registries hold object `name`.

    Returns a LookupResult; `ok` is True only when every registry the pool covers
    answered definitively, so an empty `sources` with ok=True means "found nowhere"
    and never "could not tell". Anything less yields ok=False and is not cached —
    callers act on "found nowhere" by telling operators their AS-SET does not
    exist, so a fail-open artifact must not be replayed for the whole TTL.

    A configured mirror whose source list can't be had, and a lookup that ran
    out of its budget (IRR_LOOKUP_BUDGET seconds, or `deadline` when that comes
    first), also yield ok=False.

    Intended for the interactive editor and the cleanup command — one name at a
    time, cached.
    """
    name = name.upper()
    if not _SAFE_KEY.fullmatch(name):
        return LookupResult(frozenset(), False)
    object_class = object_class or _object_class(name)

    cache_key = f"irr:sources:{object_class}:{name}"
    cached = _cache().get(cache_key)
    if cached is not None:
        return LookupResult(frozenset(cached), True)

    # Usually this is one connection per configured mirror. Track which
    # registries received a definitive answer on it; only unresolved coverage
    # falls back to separate source-pinned queries.
    deadline = _deadline(deadline)
    reachable = set()
    checked = set()
    unresolved = set()
    found = set()
    known = set(IRR_SOURCE)
    # a mirror that could not be asked may carry a source no other one does
    incomplete = False
    for server in settings.IRR_LOOKUP_SERVERS:
        mirrored = _server_sources(server, deadline)
        if not mirrored:
            incomplete = True
            continue
        mirrored = set(mirrored) & known
        if not mirrored:
            continue
        reachable |= mirrored
        answers = _sources_on_server(server, mirrored, object_class, name, deadline)
        checked |= set(answers)
        unresolved |= mirrored - set(answers)
        found |= {source for source, present in answers.items() if present}

    if not reachable:
        return LookupResult(frozenset(), False)

    for source in sorted(unresolved - checked):
        result = exists_in(source, name, object_class, deadline)
        if result is None:
            # neither the mirror's batch nor the pinned fallback answered, so
            # `found` may be incomplete -- left out of `checked` on purpose
            continue
        checked.add(source)
        if result:
            found.add(source)

    if incomplete or time.monotonic() >= deadline:
        return LookupResult(frozenset(found), False)

    if checked != reachable:
        # at least one covered registry never answered (checked is a subset by
        # construction). A cached !s-lc mirror list keeps `reachable` populated even
        # while every object query fails, so reachability is not definitiveness.
        return LookupResult(frozenset(found), False)

    result = LookupResult(frozenset(found), True)
    _cache().set(cache_key, sorted(found), timeout=settings.IRR_LOOKUP_CACHE_TTL)
    return result


def coverage_report():
    """
    IRR_SOURCE coverage audit: map each PeeringDB IRR source to the configured
    servers that mirror it, and flag any that no server covers. Returns
    {"covered": {src: [hosts]}, "uncovered": [src]}.
    """
    covered = {}
    for server in settings.IRR_LOOKUP_SERVERS:
        mirrored = _server_sources(server) or frozenset()
        for source in IRR_SOURCE:
            if source in mirrored:
                covered.setdefault(source, []).append(server["host"])
    uncovered = [s for s in IRR_SOURCE if s not in covered]
    return {"covered": covered, "uncovered": uncovered}
