"""
IRR lookup service (#1973).

The format-only `validate_irr_as_set` (validators.py) cannot answer the two
questions the unambiguous-as-set work needs:

- sources_for(name)      — which registries hold object X? (editor completions
                           and the cleanup's found-in-one / many / nowhere split)
- exists_in(source, name) — does object X exist in registry S? (the save-path
                           live check and the periodic re-verification)

Both are answered against a configurable pool of full-mirror IRRd servers
(settings.IRR_LOOKUP_SERVERS), queried over the port-43 whois interface.
Existence checks pin one source; source completion first uses one explicit
multi-source query per mirror and falls back to pinned checks if a response is too large or
unrecognized. Results are cached in the "negative" (Redis) cache for
settings.IRR_LOOKUP_CACHE_TTL seconds.

Every outbound path fails open: a query that errors, times out, or returns an
unrecognized response yields an "unknown" result — exists_in returns None and
sources_for returns ok=False — and never raises. A third-party IRR outage must
not block a save or the editor. Callers decide policy: the save path rejects only
a definitive False (provably absent), accepting None.

Correctness note: a source-pinned query against a server that does not mirror
that source returns "no entries" — a false absent. So a server's answer for a
given source is trusted only when the server actually carries it, per the
server's !s-lc mirror list (also the basis of coverage_report()).
"""

import re
import socket
from collections import namedtuple

from django.conf import settings
from django.core.cache import caches

from peeringdb_server.inet import IRR_SOURCE

# Result of a sources_for() lookup. `sources` is the frozenset of IRR_SOURCE
# registries found to hold the object; `ok` is False when the pool could not be
# reached at all (so an empty `sources` means "unknown", not "found nowhere").
LookupResult = namedtuple("LookupResult", ["sources", "ok"])

# IRRd port-43 responses to a source-pinned RPSL query start either with an RPSL
# attribute line ("as-set: …", "aut-num: …") when the object exists, or with a
# "%"-prefixed comment ("%  No entries found …") when it does not.
_NO_ENTRIES_PREFIX = "%"
_MAX_RESPONSE_BYTES = 8192

# A safe object key: the tokens we look up are already format-validated upstream,
# but irr.py is a library — reject anything that could break out of the whois
# command line (whitespace / control chars) before it hits a socket.
_SAFE_KEY = re.compile(r"^[A-Z0-9_:.-]+$")


def _object_class(name):
    """Infer the RPSL object class to query for a single as-set token."""
    if re.fullmatch(r"AS[0-9]+", name):
        return "aut-num"
    if "RS-" in name:
        return "route-set"
    return "as-set"


def _cache():
    return caches["negative"]


def _timeout(server):
    return server.get("timeout", settings.IRR_LOOKUP_DEFAULT_TIMEOUT)


def _send(server, payload):
    """
    Send one query to an IRRd server over port-43 whois and return the decoded
    response text. Raises OSError (incl. socket.timeout) on any network failure —
    callers translate that into a fail-open "unknown".
    """
    timeout = _timeout(server)
    host = server["host"]
    port = server.get("port", 43)
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        sock.sendall((payload + "\r\n").encode("ascii", "ignore"))
        chunks = []
        total = 0
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
            total += len(data)
            # We only ever need the leading bytes (first RPSL line, or the short
            # `!s-lc` listing). Cap the read so a huge as-set object with tens of
            # thousands of `members:` lines can't blow up memory or wall-time.
            if total >= _MAX_RESPONSE_BYTES:
                break
        return b"".join(chunks).decode("utf-8", "replace")
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _server_sources(server):
    """
    The set of IRR sources a server mirrors, via IRRd's !s-lc command (response
    shape "A<len>\\n<comma,list>\\nC"). Cached; None on failure.
    """
    cache_key = f"irr:srcs:{server['host']}:{server.get('port', 43)}"
    cached = _cache().get(cache_key)
    if cached is not None:
        return frozenset(cached)
    try:
        text = _send(server, "!s-lc")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "ACD":
            # skip the IRRd status/length lines (A<len>, C, D)
            continue
        sources = frozenset(s.strip().upper() for s in line.split(",") if s.strip())
        if sources:
            _cache().set(
                cache_key, list(sources), timeout=settings.IRR_LOOKUP_CACHE_TTL
            )
            return sources
    return None


def _pinned_exists(server, source, object_class, name):
    """
    Does `name` exist in `source` per this server? True/False when the server
    answers definitively, None on error or an unrecognized response. Reads only
    the first non-empty line — never the (potentially huge) object.
    """
    query = f"-s {source} -T {object_class} {name}"
    try:
        text = _send(server, query)
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(_NO_ENTRIES_PREFIX):
            return False
        if line.startswith(f"{object_class}:"):
            return True
        # Unrecognized first line → don't guess.
        return None
    return None


def _sources_on_server(server, mirrored_sources, object_class, name):
    """
    Return the sources in one mirror's exact-name response.

    A small object exposes every matching object's source in one query. If the
    bounded response is truncated (large member lists) or unrecognized, return
    None so sources_for falls back to the existing source-pinned checks.
    """
    source_list = ",".join(sorted(mirrored_sources))
    try:
        text = _send(server, f"-s {source_list} -T {object_class} {name}")
    except OSError:
        return None
    if len(text.encode("utf-8")) >= _MAX_RESPONSE_BYTES:
        return None

    found_sources = {
        match.group(1).upper()
        for match in re.finditer(r"^source:\s*(\S+)", text, flags=re.MULTILINE | re.I)
        if match.group(1).upper() in IRR_SOURCE
    }
    if found_sources:
        return frozenset(found_sources)

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(_NO_ENTRIES_PREFIX):
            return frozenset()
        return None
    return None


def exists_in(source, name, object_class=None):
    """
    Whether object `name` exists in registry `source`.

    Returns True (present), False (provably absent), or None (unknown — lookup
    infrastructure could not answer; callers fail open). `source` must be one of
    IRR_SOURCE.
    """
    source = source.upper()
    name = name.upper()
    if source not in IRR_SOURCE or not _SAFE_KEY.match(name):
        return None
    object_class = object_class or _object_class(name)

    cache_key = f"irr:exists:{source}:{object_class}:{name}"
    cached = _cache().get(cache_key)
    if cached is not None:
        return cached

    for server in settings.IRR_LOOKUP_SERVERS:
        mirrored = _server_sources(server)
        if mirrored is not None and source not in mirrored:
            # This server does not carry `source`; its "no entries" would be a
            # false absent, so skip it entirely.
            continue
        result = _pinned_exists(server, source, object_class, name)
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


def sources_for(name, object_class=None):
    """
    Which IRR_SOURCE registries hold object `name`.

    Returns a LookupResult; `ok` is True only when every registry the pool covers
    answered definitively, so an empty `sources` with ok=True means "found nowhere"
    and never "could not tell". Anything less yields ok=False and is not cached —
    callers act on "found nowhere" by telling operators their AS-SET does not
    exist, so a fail-open artifact must not be replayed for the whole TTL.

    Intended for the interactive editor and the cleanup command — one name at a
    time, cached.
    """
    name = name.upper()
    if not _SAFE_KEY.match(name):
        return LookupResult(frozenset(), False)
    object_class = object_class or _object_class(name)

    cache_key = f"irr:sources:{object_class}:{name}"
    cached = _cache().get(cache_key)
    if cached is not None:
        return LookupResult(frozenset(cached), True)

    # Usually this is one bounded exact-name query per configured mirror. Track
    # which registries received a definitive multi-source answer; only unresolved
    # coverage falls back to the more expensive source-pinned path.
    reachable = set()
    checked = set()
    unresolved = set()
    found = set()
    known = set(IRR_SOURCE)
    for server in settings.IRR_LOOKUP_SERVERS:
        mirrored = _server_sources(server)
        if not mirrored:
            continue
        mirrored = set(mirrored) & known
        if not mirrored:
            continue
        reachable |= mirrored
        result = _sources_on_server(server, mirrored, object_class, name)
        if result is None:
            unresolved |= mirrored
            continue
        checked |= mirrored
        found |= set(result) & known

    if not reachable:
        return LookupResult(frozenset(), False)

    for source in sorted(unresolved - checked):
        result = exists_in(source, name, object_class)
        if result is None:
            # neither the multi-source query nor the pinned fallback answered, so
            # `found` may be incomplete -- left out of `checked` on purpose
            continue
        checked.add(source)
        if result:
            found.add(source)

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
