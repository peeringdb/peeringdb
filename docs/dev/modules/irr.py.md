Generated from irr.py on 2026-08-15 04:17:12.049436

# peeringdb_server.irr

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

# Functions
---

## _object_class
`def _object_class(name)`

Infer the RPSL object class to query for a single as-set token.

---
## _pinned_exists
`def _pinned_exists(server, source, object_class, name)`

Does `name` exist in `source` per this server? True/False when the server
answers definitively, None on error or an unrecognized response. Reads only
the first non-empty line — never the (potentially huge) object.

---
## _send
`def _send(server, payload)`

Send one query to an IRRd server over port-43 whois and return the decoded
response text. Raises OSError (incl. socket.timeout) on any network failure —
callers translate that into a fail-open "unknown".

---
## _server_sources
`def _server_sources(server)`

The set of IRR sources a server mirrors, via IRRd's !s-lc command (response
shape "A<len>\n<comma,list>\nC"). Cached; None on failure.

---
## _sources_on_server
`def _sources_on_server(server, mirrored_sources, object_class, name)`

Return the sources in one mirror's exact-name response.

A small object exposes every matching object's source in one query. If the
bounded response is truncated (large member lists) or unrecognized, return
None so sources_for falls back to the existing source-pinned checks.

---
## coverage_report
`def coverage_report()`

IRR_SOURCE coverage audit: map each PeeringDB IRR source to the configured
servers that mirror it, and flag any that no server covers. Returns
{"covered": {src: [hosts]}, "uncovered": [src]}.

---
## exists_in
`def exists_in(source, name, object_class=None)`

Whether object `name` exists in registry `source`.

Returns True (present), False (provably absent), or None (unknown — lookup
infrastructure could not answer; callers fail open). `source` must be one of
IRR_SOURCE.

---
## sources_for
`def sources_for(name, object_class=None)`

Which IRR_SOURCE registries hold object `name`.

Returns a LookupResult; `ok` is True only when every registry the pool covers
answered definitively, so an empty `sources` with ok=True means "found nowhere"
and never "could not tell". Anything less yields ok=False and is not cached —
callers act on "found nowhere" by telling operators their AS-SET does not
exist, so a fail-open artifact must not be replayed for the whole TTL.

Intended for the interactive editor and the cleanup command — one name at a
time, cached.

---
# Classes
---

## LookupResult

```
LookupResult(builtins.tuple)
```

LookupResult(sources, ok)


### Class Methods

#### _make
`def _make(cls, iterable)`

Make a new LookupResult object from a sequence or iterable

---

### Methods

#### \__getnewargs__
`def __getnewargs__(self)`

Return self as a plain tuple.  Used by copy and pickle.

---
#### \__replace__
`def __replace__(self, **kwds)`

Return a new LookupResult object replacing specified fields with new values

---
#### \__repr__
`def __repr__(self)`

Return a nicely formatted representation string

---
#### _asdict
`def _asdict(self)`

Return a new dict which maps field names to their values.

---
#### _replace
`def _replace(self, **kwds)`

Return a new LookupResult object replacing specified fields with new values

---
