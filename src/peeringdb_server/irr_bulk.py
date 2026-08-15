"""
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
"""

import gzip
import logging
import os
import re
import tempfile
import time
from collections import namedtuple
from urllib import request

from django.conf import settings

from peeringdb_server.inet import IRR_SOURCE

logger = logging.getLogger(__name__)

# object classes whose primary keys we index (as-set / route-set names + ASN
# aut-nums — the token types irr_as_set can hold)
_OBJECT_CLASSES = ("as-set", "route-set", "aut-num")

_ATTR_RE = re.compile(r"^([a-z0-9-]+):\s*(.*)$")

# Registry-hosted dumps plus the smaller registries mirrored in RADB's dbase
# directory. IDNIC is the only IRR_SOURCE without a self-serve dump; batch misses
# for it are confirmed through the live pool before any outreach is sent.
DUMP_SOURCES = (
    {
        "name": "RIPE",
        "serial_url": "https://ftp.ripe.net/ripe/dbase/RIPE.CURRENTSERIAL",
        "files": (
            (
                "ripe.db.as-set.gz",
                "https://ftp.ripe.net/ripe/dbase/split/ripe.db.as-set.gz",
            ),
            (
                "ripe.db.aut-num.gz",
                "https://ftp.ripe.net/ripe/dbase/split/ripe.db.aut-num.gz",
            ),
            (
                "ripe.db.route-set.gz",
                "https://ftp.ripe.net/ripe/dbase/split/ripe.db.route-set.gz",
            ),
        ),
    },
    {
        "name": "APNIC",
        "serial_url": "https://ftp.apnic.net/apnic/whois/APNIC.CURRENTSERIAL",
        "files": (
            (
                "apnic.db.as-set.gz",
                "https://ftp.apnic.net/apnic/whois/apnic.db.as-set.gz",
            ),
            (
                "apnic.db.aut-num.gz",
                "https://ftp.apnic.net/apnic/whois/apnic.db.aut-num.gz",
            ),
            (
                "apnic.db.route-set.gz",
                "https://ftp.apnic.net/apnic/whois/apnic.db.route-set.gz",
            ),
        ),
    },
    {
        "name": "AFRINIC",
        "serial_url": "https://ftp.afrinic.net/pub/dbase/AFRINIC.CURRENTSERIAL",
        "files": (
            (
                "afrinic.db.gz",
                "https://ftp.afrinic.net/pub/dbase/afrinic.db.gz",
            ),
        ),
    },
    {
        "name": "ARIN",
        "serial_url": "https://ftp.arin.net/pub/rr/ARIN.CURRENTSERIAL",
        "files": (("arin.db.gz", "https://ftp.arin.net/pub/rr/arin.db.gz"),),
    },
    {
        "name": "LACNIC",
        "serial_url": "https://ftp.lacnic.net/lacnic/irr/LACNIC.CURRENTSERIAL",
        "files": (
            (
                "lacnic.db.gz",
                "https://ftp.lacnic.net/lacnic/irr/lacnic.db.gz",
            ),
        ),
    },
    {
        "name": "LEVEL3",
        "serial_url": "https://rr.level3.net/LEVEL3.CURRENTSERIAL",
        "files": (("level3.db.gz", "https://rr.level3.net/level3.db.gz"),),
    },
)

# Registries whose dumps we take from RADB's dbase directory, as
# (IRR_SOURCE name, dump file basename). FTP is not a leftover -- RADB serves this
# tree over FTP only: :443 is refused, :80 answers 503, and their docs publish only
# ftp:// URLs (verified 2026-07-30). Do not "upgrade" these to https. If egress
# blocks passive FTP the sources go stale and cleanup --commit refuses the partial
# index, which is the intended failure mode.
_RADB_MIRRORS = (
    ("RADB", "radb"),
    ("ALTDB", "altdb"),
    ("BELL", "bell"),
    ("BBOI", "bboi"),
    ("CANARIE", "canarie"),
    ("JPIRR", "jpirr"),
    ("NTTCOM", "nttcom"),
    ("REACH", "reach"),
    ("TC", "tc"),
)
# NESTEGG and PANIX were dropped here together with their IRR_SOURCE entries
# (#1973, 2026-08-04). Both edits have to happen in one change: build_index
# filters to `set(IRR_SOURCE)`, so a source left here after being pruned there
# would keep costing a download while contributing nothing to the index -- and
# dump_health would still demand it be present and fresh, which blocks
# pdb_irr_as_set_cleanup --commit outright.

_RADB_DBASE_URL = "ftp://ftp.radb.net/radb/dbase"

DUMP_SOURCES += tuple(
    {
        "name": source,
        "serial_url": f"{_RADB_DBASE_URL}/{source}.CURRENTSERIAL",
        "files": ((f"{filename}.db.gz", f"{_RADB_DBASE_URL}/{filename}.db.gz"),),
    }
    for source, filename in _RADB_MIRRORS
)

FetchOutcome = namedtuple("FetchOutcome", ["source", "status", "files", "reason"])


class BulkFetchError(Exception):
    """A dump refresh failed and no usable cache is available."""


def _open_url(url):
    req = request.Request(url, headers={"User-Agent": "PeeringDB IRR bulk checker"})
    return request.urlopen(req, timeout=settings.IRR_BULK_DUMP_TIMEOUT)


def _dump_problem(path, full=False):
    """
    Why `path` is not a usable dump, or None when it is.

    The default cheap check is what a freshness decision needs: non-empty and the
    first chunk decompresses, which catches a truncated or non-gzip file. `full`
    reads to the end and enforces IRR_BULK_DUMP_MAX_UNCOMPRESSED_BYTES — only
    worth it for freshly downloaded bytes, since expanding every cached dump means
    gunzipping ~700 MB on the path whose point is to avoid work.
    """
    if not os.path.isfile(path):
        return "missing"
    if os.path.getsize(path) == 0:
        return "empty"
    opener = gzip.open if path.endswith(".gz") else open
    total = 0
    try:
        with opener(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.IRR_BULK_DUMP_MAX_UNCOMPRESSED_BYTES:
                    return (
                        "expands beyond IRR_BULK_DUMP_MAX_UNCOMPRESSED_BYTES "
                        f"({settings.IRR_BULK_DUMP_MAX_UNCOMPRESSED_BYTES} bytes)"
                    )
                if not full:
                    break
    except (OSError, EOFError) as exc:
        return f"unreadable ({exc})"
    if total == 0:
        return "decompresses to nothing"
    return None


def _valid_dump(path, full=False):
    """Return whether path is a non-empty, readable dump within safety bounds."""
    return _dump_problem(path, full=full) is None


def _all_valid(paths):
    return bool(paths) and all(_valid_dump(path) for path in paths)


def _all_fresh(paths, max_age_hours):
    cutoff = time.time() - (max_age_hours * 3600)
    return _all_valid(paths) and all(os.path.getmtime(path) >= cutoff for path in paths)


def _read_serial(url):
    try:
        with _open_url(url) as response:
            value = response.read(1025)
    except OSError as exc:
        raise BulkFetchError(f"could not fetch serial {url}: {exc}") from exc
    if len(value) > 1024:
        raise BulkFetchError(f"serial response from {url} is unexpectedly large")
    try:
        serial = value.decode("ascii", "strict").strip()
    except UnicodeError as exc:
        raise BulkFetchError(f"serial response from {url} is invalid") from exc
    if not serial or not re.fullmatch(r"[A-Za-z0-9._:-]+", serial):
        raise BulkFetchError(f"serial response from {url} is invalid")
    return serial


def _read_local_serial(path):
    try:
        with open(path, encoding="ascii") as handle:
            return handle.read(1025).strip()
    except OSError:
        return None


def _write_text_atomic(path, value):
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(value)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _staging_dir(dump_dir):
    """
    The subdirectory downloads are staged in before promotion.

    Deliberately not the dump dir itself: a fetch killed mid-download leaves its
    partial file behind, and load_index globs any .gz there as a dump — so the next
    cleanup run would die on a truncated gzip instead of skipping it.
    """
    path = os.path.join(dump_dir, ".staging")
    os.makedirs(path, exist_ok=True)
    return path


def _clear_staging(dump_dir):
    """Drop partial downloads a previously killed run left staged."""
    staging = _staging_dir(dump_dir)
    for name in os.listdir(staging):
        path = os.path.join(staging, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            logger.warning("IRR bulk: could not clear staged %s: %s", path, exc)


def _download_to_temp(url, destination):
    filename = os.path.basename(destination)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{filename}.",
        suffix=".gz" if destination.endswith(".gz") else ".tmp",
        dir=_staging_dir(os.path.dirname(destination)),
    )
    os.close(fd)
    total = 0
    complete = False
    try:
        with _open_url(url) as response, open(tmp_path, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.IRR_BULK_DUMP_MAX_BYTES:
                    raise BulkFetchError(
                        f"download {url} exceeds IRR_BULK_DUMP_MAX_BYTES "
                        f"({settings.IRR_BULK_DUMP_MAX_BYTES} bytes)"
                    )
                handle.write(chunk)
        # full validation: this is freshly downloaded bytes, the one place the
        # expanded-size ceiling is worth paying for
        problem = _dump_problem(tmp_path, full=True)
        if problem is not None:
            raise BulkFetchError(f"download {url} is unusable: {problem}")
        complete = True
        return tmp_path
    except (OSError, EOFError, UnicodeError) as exc:
        raise BulkFetchError(f"could not fetch {url}: {exc}") from exc
    finally:
        if os.path.exists(tmp_path) and not complete:
            os.remove(tmp_path)


def _fetch_source(spec, dump_dir, max_age_hours, force):
    source = spec["name"]
    files = tuple(spec["files"])
    paths = _source_paths(spec, dump_dir)
    if any(
        os.path.basename(path) != filename
        for path, (filename, _url) in zip(paths, files)
    ):
        raise BulkFetchError(f"unsafe dump filename configured for {source}")

    serial_path = _serial_path(source, dump_dir)
    remote_serial = None
    serial_error = None
    if spec.get("serial_url"):
        try:
            remote_serial = _read_serial(spec["serial_url"])
        except BulkFetchError as exc:
            serial_error = exc
        if (
            not force
            and remote_serial is not None
            and remote_serial == _read_local_serial(serial_path)
            and _all_valid(paths)
        ):
            return FetchOutcome(source, "fresh", paths, "serial unchanged")

    # Age is the fallback whenever no serial comparison could be made: no
    # CURRENTSERIAL published, or its endpoint is failing. Without the second case
    # a registry with an unreachable serial but a fine dump is re-downloaded in
    # full every run, and writes no marker afterwards, so the next run repeats it.
    if not force and remote_serial is None and _all_fresh(paths, max_age_hours):
        reason = "cache age within limit"
        if serial_error is not None:
            reason = f"cache age within limit; serial unavailable ({serial_error})"
        return FetchOutcome(source, "fresh", paths, reason)

    staged = []
    try:
        for (filename, url), path in zip(files, paths):
            staged.append((_download_to_temp(url, path), path))
    except BulkFetchError as exc:
        for tmp_path, _path in staged:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        if _all_valid(paths):
            reason = f"refresh failed; retained valid cache: {exc}"
            logger.warning("IRR bulk %s: %s", source, reason)
            return FetchOutcome(source, "stale", paths, reason)
        if serial_error is not None:
            raise BulkFetchError(f"{serial_error}; {exc}") from exc
        raise

    # Promotion is the one filesystem step outside the download try/except. Two
    # overlapping runs (a full fetch is ~7 min) clear each other's staging, so the
    # loser finds its temp file gone here — as a bare OSError that would escape the
    # per-source isolation in fetch_dumps, which only catches BulkFetchError, and
    # abort every source behind it.
    try:
        for tmp_path, path in staged:
            os.replace(tmp_path, path)
        if remote_serial is not None:
            _write_text_atomic(serial_path, remote_serial)
    except OSError as exc:
        raise BulkFetchError(f"could not promote staged {source} dump: {exc}") from exc
    reason = "downloaded"
    if serial_error is not None:
        reason = f"downloaded without serial marker ({serial_error})"
    return FetchOutcome(source, "updated", paths, reason)


def _selected_specs(source_names):
    """
    The DUMP_SOURCES entries `source_names` selects, all of them when it is empty.

    Shared by fetch_dumps and plan_fetch so a name the dry run accepts is a name the
    real run accepts.
    """
    selected = {name.upper() for name in (source_names or ())}
    known = {spec["name"] for spec in DUMP_SOURCES}
    unknown = selected - known
    if unknown:
        raise BulkFetchError(
            f"unknown IRR dump source(s): {', '.join(sorted(unknown))}"
        )
    return [spec for spec in DUMP_SOURCES if not selected or spec["name"] in selected]


def _resolved_max_age(max_age_hours):
    """The effective cache age limit in hours, defaulting to the setting."""
    max_age_hours = (
        settings.IRR_BULK_DUMP_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    )
    if max_age_hours < 0:
        raise BulkFetchError("max_age_hours must be zero or greater")
    return max_age_hours


def _source_paths(spec, dump_dir):
    return tuple(os.path.join(dump_dir, filename) for filename, _url in spec["files"])


def _serial_path(source, dump_dir):
    """Where a source's last-downloaded serial marker lives."""
    return os.path.join(dump_dir, f".{source.lower()}.serial")


def _cache_age_hours(paths):
    """Age of the oldest file in `paths`, in hours, or None when one is missing."""
    try:
        oldest = min(os.path.getmtime(path) for path in paths)
    except (OSError, ValueError):
        return None
    return (time.time() - oldest) / 3600


def plan_fetch(dump_dir=None, source_names=None, force=False, max_age_hours=None):
    """
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
    """
    dump_dir = dump_dir or settings.IRR_BULK_DUMP_DIR
    if not dump_dir:
        raise BulkFetchError("IRR_BULK_DUMP_DIR is not configured")
    max_age_hours = _resolved_max_age(max_age_hours)

    outcomes = []
    for spec in _selected_specs(source_names):
        paths = _source_paths(spec, dump_dir)
        if force:
            status, reason = "would-download", "--force was given"
        elif not _all_valid(paths):
            problems = [
                f"{os.path.basename(path)} {_dump_problem(path)}"
                for path in paths
                if not _valid_dump(path)
            ]
            status, reason = "would-download", f"no usable cache: {', '.join(problems)}"
        elif spec.get("serial_url"):
            # Which condition actually decides depends on whether a local marker
            # exists to compare the published serial against, and the marker is a
            # local file read, so saying so costs nothing the offline rule protects.
            # Without one _fetch_source cannot take the shortcut and also skips the
            # age fallback (it only applies when the serial could not be read at
            # all), so it downloads -- reachable in normal operation, since a run
            # whose serial endpoint hiccuped downloads and writes no marker.
            age = _cache_age_hours(paths)
            status = "serial-decides"
            prefix = f"cache {age:.1f}h old; " if age is not None else ""
            if _read_local_serial(_serial_path(spec["name"], dump_dir)) is None:
                reason = (
                    f"{prefix}no local serial marker to compare, so it downloads "
                    "unless the serial endpoint is unreachable and the cache is "
                    f"newer than {max_age_hours}h"
                )
            else:
                reason = (
                    f"{prefix}downloads if the published serial moved, or if the "
                    "serial endpoint is unreachable and the cache is older than "
                    f"{max_age_hours}h"
                )
        elif not _all_fresh(paths, max_age_hours):
            status, reason = "would-download", f"cache older than {max_age_hours}h"
        else:
            status, reason = "fresh", "cache age within limit"
        outcomes.append(FetchOutcome(spec["name"], status, paths, reason))
    return outcomes


def fetch_dumps(dump_dir=None, source_names=None, force=False, max_age_hours=None):
    """
    Refresh configured IRR dumps and return one FetchOutcome per source.

    Serial markers avoid unchanged downloads where registries publish them;
    otherwise file age is used. Every file is staged and validated before it
    replaces the cache. A failed refresh retains a complete valid cache.
    """
    dump_dir = dump_dir or settings.IRR_BULK_DUMP_DIR
    if not dump_dir:
        raise BulkFetchError("IRR_BULK_DUMP_DIR is not configured")
    specs = _selected_specs(source_names)
    max_age_hours = _resolved_max_age(max_age_hours)

    os.makedirs(dump_dir, exist_ok=True)
    _clear_staging(dump_dir)

    outcomes = []
    for spec in specs:
        try:
            outcomes.append(_fetch_source(spec, dump_dir, max_age_hours, force))
        except BulkFetchError as exc:
            # One unfetchable source must not abort the sources behind it: on a cold
            # start there is no cache to fall back to, so a single flaky registry
            # (seen: RADB dropping a passive-FTP data connection) left the rest
            # unfetched, and cleanup --commit needs the whole set. The caller turns
            # "failed" into a non-zero exit; dump_health still blocks --commit.
            paths = _source_paths(spec, dump_dir)
            logger.warning("IRR bulk %s: refresh failed: %s", spec["name"], exc)
            outcomes.append(FetchOutcome(spec["name"], "failed", paths, str(exc)))
    return outcomes


def parse_rpsl(lines):
    """
    Yield (object_class, primary_key, source) for every as-set / route-set /
    aut-num object in an RPSL dump. Objects are blank-line separated; the first
    attribute line names the class and key, and a source: attribute names the
    registry. Keys and sources are upper-cased. Non-target objects are skipped.

    `lines` is an iterable — an open file handle, or `text.splitlines()` for an
    in-memory dump. Not a whole-dump string: expanded these run to hundreds of MB,
    which is the point of streaming here.
    """
    if isinstance(lines, str):
        raise TypeError(
            "parse_rpsl takes an iterable of lines, not a whole-dump string; "
            "pass a file handle or value.splitlines()"
        )

    cls = key = source = None

    def flush():
        if cls in _OBJECT_CLASSES and key:
            return (cls, key.upper(), (source or "").upper())
        return None

    for line in lines:
        line = line.rstrip("\r\n")
        if not line.strip():
            obj = flush()
            if obj:
                yield obj
            cls = key = source = None
            continue
        # comments and RPSL continuation lines (leading whitespace) carry no
        # attribute we need
        if line[0] in "#%" or line[0].isspace():
            continue
        match = _ATTR_RE.match(line)
        if not match:
            continue
        attr, value = match.group(1), match.group(2).strip()
        if cls is None and attr in _OBJECT_CLASSES:
            cls = attr
            key = value.split()[0] if value else None
        elif attr == "source" and value:
            source = value.split()[0]

    obj = flush()
    if obj:
        yield obj


def build_index(paths):
    """Build {PRIMARY_KEY -> {SOURCE, …}} from a list of dump file paths."""
    index = {}
    known = set(IRR_SOURCE)
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            for _cls, key, source in parse_rpsl(handle):
                # only index sources PeeringDB recognizes; a dump may carry
                # RIPE-NONAUTH / RPKI pseudo-sources we don't track
                if source in known:
                    index.setdefault(key, set()).add(source)
    return index


def load_index(dump_dir=None):
    """
    Build the index from every *.db / *.db.gz under `dump_dir` (default
    settings.IRR_BULK_DUMP_DIR). Returns None when no dump dir is configured or it
    holds no dumps — callers then report syntactic buckets only.

    Dotfiles are skipped — the serial markers and .staging/ live here too.

    The index reflects whatever files are present, of whatever age, so a caller
    that writes off it (pdb_irr_as_set_cleanup --commit) must check dump_health()
    too: an index missing one registry makes an ambiguous name look unambiguous.
    """
    dump_dir = dump_dir or getattr(settings, "IRR_BULK_DUMP_DIR", "")
    if not dump_dir or not os.path.isdir(dump_dir):
        return None
    paths = [
        os.path.join(dump_dir, name)
        for name in sorted(os.listdir(dump_dir))
        if name.endswith((".db", ".db.gz", ".gz")) and not name.startswith(".")
    ]
    if not paths:
        return None
    return build_index(paths)


def dump_health(dump_dir=None, max_age_hours=None):
    """
    Whether the on-disk dump set is complete and fresh enough to write from.

    Returns (missing, stale): source names with an absent or unusable dump file,
    and source names whose files are all present but older than `max_age_hours`
    (default IRR_BULK_DUMP_MAX_AGE_HOURS). Both empty means every source in
    DUMP_SOURCES is covered by a readable, current dump.

    IDNIC is intentionally absent from DUMP_SOURCES (no self-serve dump) and so
    is never reported here; batch misses for it are confirmed live instead.
    """
    dump_dir = dump_dir or getattr(settings, "IRR_BULK_DUMP_DIR", "")
    if max_age_hours is None:
        max_age_hours = settings.IRR_BULK_DUMP_MAX_AGE_HOURS

    missing = []
    stale = []
    for spec in DUMP_SOURCES:
        paths = [os.path.join(dump_dir, filename) for filename, _url in spec["files"]]
        if not _all_valid(paths):
            missing.append(spec["name"])
        elif not _all_fresh(paths, max_age_hours):
            stale.append(spec["name"])
    return missing, stale


def describe_dump_problems(dump_dir=None, max_age_hours=None):
    """
    A human-readable description of what is wrong with the on-disk dump set, or None
    when it is complete and current.

    The fact-gathering half of the guard both irr batch commands put in front of
    --commit. They share this and keep their own policy, because the consequence of
    an unhealthy set differs: pdb_irr_as_set_cleanup would write a wrong source
    prefix, while pdb_irr_as_set_status merely spends its live-lookup budget on
    tokens the index should have answered for free.
    """
    missing, stale = dump_health(dump_dir, max_age_hours)
    if not missing and not stale:
        return None

    problems = []
    if missing:
        problems.append(f"missing or unreadable: {', '.join(missing)}")
    if stale:
        problems.append(f"older than IRR_BULK_DUMP_MAX_AGE_HOURS: {', '.join(stale)}")
    return "; ".join(problems)


def sources_for_bulk(name, index):
    """The known IRR sources holding `name` per a built index (frozenset)."""
    return frozenset(index.get(name.upper(), frozenset()))
