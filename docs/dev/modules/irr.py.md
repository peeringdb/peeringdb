Generated from irr.py on 2026-11-17 18:01:18.661144

# peeringdb_server.irr

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

# Functions
---

## _block_body
`def _block_body(text)`

The data of a reply that is exactly one A<len> block closed by C, or None.

A<len> counts the data and the newline after it.

---
## _connect
`def _connect(host, port, time_left)`

Connect to the first address of `host` that answers, every attempt within
the time left: create_connection would give each address the whole
timeout. Name resolution itself is not bounded.

---
## _deadline
`def _deadline(deadline=None)`

The end of a lookup's budget, and no later than a caller's deadline.

---
## _exact_key
`def _exact_key(object_class, name)`

The key `!m` matches exactly: whois normalized AS0003333 to AS3333.

---
## _object_class
`def _object_class(name)`

Infer the RPSL object class to query for a single as-set token.

---
## _pinned_exists
`def _pinned_exists(server, source, object_class, name, deadline=None)`

Does `name` exist in `source` per this server? True/False when the server
answers definitively, None on error or an unrecognized response.

Asked over IRRd's `!` protocol rather than whois (#499): there an error reply
("%% ERROR: ...") starts with "%" just like "no entries", while here they are
distinct status lines -- A<len> found, C/D no data, F error. Reads only the
status lines, never the (potentially huge) object.

---
## _read_statuses
`def _read_statuses(text)`

Split a pipelined `!` protocol reply into one status per command.

A<len> (found; its object follows and is skipped by its byte length), C, D
and F. Reading stops at the first incomplete or unrecognized reply, since
nothing after it can be matched to its command anymore.

---
## _send
`def _send(server, payload, deadline=None)`

Send one query (whois or `!` protocol) to an IRRd server on port 43 and
return the decoded response text. Raises OSError (incl. TimeoutError) on
any network failure — callers translate that into a fail-open "unknown".

The whole exchange, name resolution excepted, has to finish within the
server's timeout, and before `deadline` (a time.monotonic() value) when
given. A mirror whose exchange ran out of its own time is skipped for
IRR_LOOKUP_MIRROR_DOWN_TTL seconds.

---
## _server_sources
`def _server_sources(server, deadline=None)`

The set of IRR sources a server mirrors, via IRRd's !s-lc command (response
shape "A<len>\n<comma,list>\nC"). Cached; None on failure.

---
## _sources_on_server
`def _sources_on_server(server, mirrored_sources, object_class, name, deadline=None)`

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

---
## coverage_report
`def coverage_report()`

IRR_SOURCE coverage audit: map each PeeringDB IRR source to the configured
servers that mirror it, and flag any that no server covers. Returns
{"covered": {src: [hosts]}, "uncovered": [src]}.

---
## exists_in
`def exists_in(source, name, object_class=None, deadline=None)`

Whether object `name` exists in registry `source`.

Returns True (present), False (provably absent), or None (unknown — lookup
infrastructure could not answer; callers fail open). `source` must be one of
IRR_SOURCE.

Spends at most IRR_LOOKUP_BUDGET seconds, and stops at `deadline` (a
time.monotonic() value) when that comes first, so several calls can share
one budget.

---
## sources_for
`def sources_for(name, object_class=None, deadline=None)`

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
