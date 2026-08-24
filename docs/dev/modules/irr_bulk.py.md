Generated from irr_bulk.py on 2026-08-15 04:17:12.049436

# peeringdb_server.irr_bulk

Bulk IRR dump index (#1973) — the batch backend for the cleanup / periodic
checker.

Those two jobs must answer "which registries hold object X?" for ~20-30k names.
Doing that with per-name live queries would hammer the mirrors, so the batch path
builds a local {name -> {sources}} index from downloaded IRR dump files and
answers every lookup in memory. (Transiently ingesting registry dumps for private
checking is fine; PeeringDB is not running or republishing an IRR.)

This module owns the download/cache lifecycle plus the parser and index. Registry
dumps are refreshed into settings.IRR_BULK_DUMP_DIR, validated, and atomically
replaced. A failed refresh keeps a valid older cache. The interactive save-path /
editor use the live irr.py pool instead — this is only for the batch sweeps.

# Functions
---

## _cache_age_hours
`def _cache_age_hours(paths)`

Age of the oldest file in `paths`, in hours, or None when one is missing.

---
## _clear_staging
`def _clear_staging(dump_dir)`

Drop partial downloads a previously killed run left staged.

---
## _dump_problem
`def _dump_problem(path, full=False)`

Why `path` is not a usable dump, or None when it is.

The default cheap check is what a freshness decision needs: non-empty and the
first chunk decompresses, which catches a truncated or non-gzip file. `full`
reads to the end and enforces IRR_BULK_DUMP_MAX_UNCOMPRESSED_BYTES — only
worth it for freshly downloaded bytes, since expanding every cached dump means
gunzipping ~700 MB on the path whose point is to avoid work.

---
## _resolved_max_age
`def _resolved_max_age(max_age_hours)`

The effective cache age limit in hours, defaulting to the setting.

---
## _selected_specs
`def _selected_specs(source_names)`

The DUMP_SOURCES entries `source_names` selects, all of them when it is empty.

Shared by fetch_dumps and plan_fetch so a name the dry run accepts is a name the
real run accepts.

---
## _serial_path
`def _serial_path(source, dump_dir)`

Where a source's last-downloaded serial marker lives.

---
## _staging_dir
`def _staging_dir(dump_dir)`

The subdirectory downloads are staged in before promotion.

Deliberately not the dump dir itself: a fetch killed mid-download leaves its
partial file behind, and load_index globs any .gz there as a dump — so the next
cleanup run would die on a truncated gzip instead of skipping it.

---
## _valid_dump
`def _valid_dump(path, full=False)`

Return whether path is a non-empty, readable dump within safety bounds.

---
## build_index
`def build_index(paths)`

Build {PRIMARY_KEY -> {SOURCE, …}} from a list of dump file paths.

---
## describe_dump_problems
`def describe_dump_problems(dump_dir=None, max_age_hours=None)`

A human-readable description of what is wrong with the on-disk dump set, or None
when it is complete and current.

The fact-gathering half of the guard both irr batch commands put in front of
--commit. They share this and keep their own policy, because the consequence of
an unhealthy set differs: pdb_irr_as_set_cleanup would write a wrong source
prefix, while pdb_irr_as_set_status merely spends its live-lookup budget on
tokens the index should have answered for free.

---
## dump_health
`def dump_health(dump_dir=None, max_age_hours=None)`

Whether the on-disk dump set is complete and fresh enough to write from.

Returns (missing, stale): source names with an absent or unusable dump file,
and source names whose files are all present but older than `max_age_hours`
(default IRR_BULK_DUMP_MAX_AGE_HOURS). Both empty means every source in
DUMP_SOURCES is covered by a readable, current dump.

IDNIC is intentionally absent from DUMP_SOURCES (no self-serve dump) and so
is never reported here; batch misses for it are confirmed live instead.

---
## fetch_dumps
`def fetch_dumps(dump_dir=None, source_names=None, force=False, max_age_hours=None)`

Refresh configured IRR dumps and return one FetchOutcome per source.

Serial markers avoid unchanged downloads where registries publish them;
otherwise file age is used. Every file is staged and validated before it
replaces the cache. A failed refresh retains a complete valid cache.

---
## load_index
`def load_index(dump_dir=None)`

Build the index from every *.db / *.db.gz under `dump_dir` (default
settings.IRR_BULK_DUMP_DIR). Returns None when no dump dir is configured or it
holds no dumps — callers then report syntactic buckets only.

Dotfiles are skipped — the serial markers and .staging/ live here too.

The index reflects whatever files are present, of whatever age, so a caller
that writes off it (pdb_irr_as_set_cleanup --commit) must check dump_health()
too: an index missing one registry makes an ambiguous name look unambiguous.

---
## parse_rpsl
`def parse_rpsl(lines)`

Yield (object_class, primary_key, source) for every as-set / route-set /
aut-num object in an RPSL dump. Objects are blank-line separated; the first
attribute line names the class and key, and a source: attribute names the
registry. Keys and sources are upper-cased. Non-target objects are skipped.

`lines` is an iterable — an open file handle, or `text.splitlines()` for an
in-memory dump. Not a whole-dump string: expanded these run to hundreds of MB,
which is the point of streaming here.

---
## plan_fetch
`def plan_fetch(dump_dir=None, source_names=None, force=False, max_age_hours=None)`

What fetch_dumps would do, as one FetchOutcome per selected source, without
downloading anything or touching the dump directory.

Deliberately makes no request at all, not even for the serial markers: a dry
run should not put load on someone else's server, and it has to answer on a
cold host. Read-only in both directions -- unlike fetch_dumps it does not
create the dump directory or clear the staging area.

That offline constraint decides the statuses, which are three rather than two:

  would-download  the real run downloads whatever the serial says -- forced,
                  or there is no usable cache to keep (the serial shortcut in
                  _fetch_source requires a valid one)
  serial-decides  a usable cache plus a published serial, so the outcome is
                  not knowable offline
  fresh           a usable cache and no serial to consult, so file age is the
                  whole decision, exactly as in the real run

`serial-decides` exists because reporting the age branch here would be wrong in
the common case: once the cache is valid, _fetch_source compares the published
serial and ignores mtime entirely. A source whose serial sits still for longer
than IRR_BULK_DUMP_MAX_AGE_HOURS -- the quiet RADB mirrors, not RIPE -- is
"older than the limit" on disk and still `fresh` to the real run, so an age
verdict here would promise a download that never happens. The age is reported
in the reason instead, where it informs without asserting.

---
## sources_for_bulk
`def sources_for_bulk(name, index)`

The known IRR sources holding `name` per a built index (frozenset).

---
# Classes
---

## BulkFetchError

```
BulkFetchError(builtins.Exception)
```

A dump refresh failed and no usable cache is available.


## DumpSource

```
DumpSource(builtins.dict)
```

dict() -> new empty dictionary
dict(mapping) -> new dictionary initialized from a mapping object's
    (key, value) pairs
dict(iterable) -> new dictionary initialized as if via:
    d = {}
    for k, v in iterable:
        d[k] = v
dict(**kwargs) -> new dictionary initialized with the name=value pairs
    in the keyword argument list.  For example:  dict(one=1, two=2)


## FetchOutcome

```
FetchOutcome(builtins.tuple)
```

FetchOutcome(source, status, files, reason)


### Class Methods

#### _make
`def _make(cls, iterable)`

Make a new FetchOutcome object from a sequence or iterable

---

### Methods

#### \__getnewargs__
`def __getnewargs__(self)`

Return self as a plain tuple.  Used by copy and pickle.

---
#### \__replace__
`def __replace__(self, **kwds)`

Return a new FetchOutcome object replacing specified fields with new values

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

Return a new FetchOutcome object replacing specified fields with new values

---
