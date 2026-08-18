"""Tests for the #1973 IRR bulk dump fetch/cache lifecycle."""

import gzip
from io import BytesIO, StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from peeringdb_server import irr_bulk

pytestmark = pytest.mark.django_db

SAMPLE_RPSL = b"as-set: AS-EXAMPLE\nsource: RIPE\n\n"


def gzip_bytes(value=SAMPLE_RPSL):
    output = BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb") as handle:
        handle.write(value)
    return output.getvalue()


@pytest.fixture
def dump_source(monkeypatch):
    spec = {
        "name": "RIPE",
        "serial_url": "https://registry.example/RIPE.CURRENTSERIAL",
        "files": (("ripe.db.gz", "https://registry.example/ripe.db.gz"),),
    }
    monkeypatch.setattr(irr_bulk, "DUMP_SOURCES", (spec,))
    return spec


def install_responses(monkeypatch, responses):
    calls = []

    def open_url(url):
        calls.append(url)
        response = responses[url]
        if isinstance(response, Exception):
            raise response
        return BytesIO(response)

    monkeypatch.setattr(irr_bulk, "_open_url", open_url)
    return calls


def write_dump(path, value=SAMPLE_RPSL):
    with gzip.open(path, "wb") as handle:
        handle.write(value)


def test_dump_manifest_covers_every_source_except_live_only_idnic():
    dump_sources = {spec["name"] for spec in irr_bulk.DUMP_SOURCES}

    assert set(irr_bulk.IRR_SOURCE) - dump_sources == {"IDNIC"}


def test_fetch_changed_serial_updates_dump_and_marker(
    tmp_path, monkeypatch, dump_source
):
    calls = install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: gzip_bytes(),
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    assert outcomes[0].status == "updated"
    assert (tmp_path / ".ripe.serial").read_text() == "42\n"
    assert irr_bulk.load_index(str(tmp_path))["AS-EXAMPLE"] == {"RIPE"}
    assert calls == [
        dump_source["serial_url"],
        dump_source["files"][0][1],
    ]


def test_fetch_unchanged_serial_reuses_valid_cache(tmp_path, monkeypatch, dump_source):
    write_dump(tmp_path / "ripe.db.gz")
    (tmp_path / ".ripe.serial").write_text("42\n")
    calls = install_responses(monkeypatch, {dump_source["serial_url"]: b"42\n"})

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    assert outcomes[0].status == "fresh"
    assert outcomes[0].reason == "serial unchanged"
    assert calls == [dump_source["serial_url"]]


def test_fetch_without_serial_reuses_fresh_cache(tmp_path, monkeypatch):
    spec = {
        "name": "PANIX",
        "files": (("panix.db.gz", "https://registry.example/panix.db.gz"),),
    }
    monkeypatch.setattr(irr_bulk, "DUMP_SOURCES", (spec,))
    write_dump(tmp_path / "panix.db.gz")
    open_url = mock.Mock()
    monkeypatch.setattr(irr_bulk, "_open_url", open_url)

    outcomes = irr_bulk.fetch_dumps(str(tmp_path), max_age_hours=24)

    assert outcomes[0].status == "fresh"
    assert outcomes[0].reason == "cache age within limit"
    open_url.assert_not_called()


def test_fetch_failure_retains_valid_stale_cache(tmp_path, monkeypatch, dump_source):
    original = b"as-set: AS-OLD\nsource: RIPE\n\n"
    write_dump(tmp_path / "ripe.db.gz", original)
    (tmp_path / ".ripe.serial").write_text("41\n")
    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: OSError("registry unavailable"),
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    assert outcomes[0].status == "stale"
    with gzip.open(tmp_path / "ripe.db.gz", "rb") as handle:
        assert handle.read() == original
    assert (tmp_path / ".ripe.serial").read_text() == "41\n"


def test_fetch_corrupt_download_retains_valid_stale_cache(
    tmp_path, monkeypatch, dump_source
):
    original = b"as-set: AS-OLD\nsource: RIPE\n\n"
    write_dump(tmp_path / "ripe.db.gz", original)
    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: b"not a gzip stream",
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    assert outcomes[0].status == "stale"
    with gzip.open(tmp_path / "ripe.db.gz", "rb") as handle:
        assert handle.read() == original


def test_fetch_failure_without_cache_reports_failed(tmp_path, monkeypatch, dump_source):
    # No cache to retain, so there is no "stale" to report: the source comes back
    # "failed" carrying the reason, which pdb_irr_as_set_fetch turns into a
    # non-zero exit. Reported rather than raised so the other sources still run.
    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: OSError("registry unavailable"),
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    assert outcomes[0].status == "failed"
    assert "registry unavailable" in outcomes[0].reason
    assert irr_bulk.load_index(str(tmp_path)) is None


def test_fetch_promotion_failure_reports_failed(tmp_path, monkeypatch, dump_source):
    # Promotion is the one filesystem step outside the download try/except. Two
    # overlapping runs clear each other's staging, so the loser's temp file is gone
    # by the time it gets here; as a bare OSError that escapes the per-source
    # isolation in fetch_dumps and aborts every source behind it.
    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: gzip_bytes(),
        },
    )

    def vanished(src, dst):
        raise OSError("No such file or directory")

    monkeypatch.setattr(irr_bulk.os, "replace", vanished)

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    assert outcomes[0].status == "failed"
    assert "could not promote staged RIPE dump" in outcomes[0].reason


@override_settings(IRR_BULK_DUMP_MAX_BYTES=8)
def test_fetch_rejects_download_over_size_limit(tmp_path, monkeypatch, dump_source):
    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: gzip_bytes(),
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    assert outcomes[0].status == "failed"
    assert "MAX_BYTES" in outcomes[0].reason

    # nothing was promoted into the dump dir; only the (empty) staging dir remains
    assert list(tmp_path.iterdir()) == [tmp_path / ".staging"]
    assert not list((tmp_path / ".staging").iterdir())


@override_settings(IRR_BULK_DUMP_MAX_UNCOMPRESSED_BYTES=8)
def test_fetch_rejects_expanded_dump_over_size_limit(
    tmp_path, monkeypatch, dump_source
):
    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: gzip_bytes(),
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    # the reason names the ceiling that was breached -- "too large" must not be
    # conflated with "empty or corrupt", which is what makes a quiet stale run
    # diagnosable
    assert outcomes[0].status == "failed"
    assert "MAX_UNCOMPRESSED_BYTES" in outcomes[0].reason

    assert list(tmp_path.iterdir()) == [tmp_path / ".staging"]


def test_fetch_rejects_unknown_source_without_network(
    tmp_path, monkeypatch, dump_source
):
    open_url = mock.Mock()
    monkeypatch.setattr(irr_bulk, "_open_url", open_url)

    with pytest.raises(irr_bulk.BulkFetchError, match="unknown IRR dump source"):
        irr_bulk.fetch_dumps(str(tmp_path), source_names=["NOT-AN-IRR"])

    open_url.assert_not_called()


@mock.patch("peeringdb_server.irr_bulk.fetch_dumps")
def test_fetch_command_reports_outcomes(fetch_dumps, tmp_path):
    fetch_dumps.return_value = [
        irr_bulk.FetchOutcome(
            "RIPE",
            "fresh",
            (str(tmp_path / "ripe.db.gz"),),
            "serial unchanged",
        )
    ]
    output = StringIO()

    call_command(
        "pdb_irr_as_set_fetch",
        "--commit",
        "--source",
        "RIPE",
        "--dump-dir",
        str(tmp_path),
        stdout=output,
    )

    assert "[fresh] RIPE: ripe.db.gz (serial unchanged)" in output.getvalue()
    fetch_dumps.assert_called_once_with(
        dump_dir=str(tmp_path),
        source_names=["RIPE"],
        force=False,
        max_age_hours=None,
    )


@mock.patch("peeringdb_server.irr_bulk.fetch_dumps")
def test_fetch_command_exits_nonzero_when_a_source_is_stale(fetch_dumps, tmp_path):
    # A stale source means that registry has silently stopped refreshing while the
    # command otherwise looks successful -- one [stale] line among 17 is too quiet,
    # so the run must fail and cron must see it.
    fetch_dumps.return_value = [
        irr_bulk.FetchOutcome(
            "RIPE", "updated", (str(tmp_path / "a.gz"),), "downloaded"
        ),
        irr_bulk.FetchOutcome(
            "RADB",
            "stale",
            (str(tmp_path / "b.gz"),),
            "refresh failed; retained valid cache: boom",
        ),
    ]
    output = StringIO()

    with pytest.raises(CommandError, match="IRR dump refresh failed for RADB"):
        call_command("pdb_irr_as_set_fetch", "--commit", stdout=output)

    # the per-source lines are still printed before the failure
    assert "[stale] RADB" in output.getvalue()


def test_fetch_failure_without_cache_does_not_abort_later_sources(
    tmp_path, monkeypatch
):
    # A cold start has no cache to fall back on, so an unfetchable source raises
    # out of _fetch_source. That must not cost the sources behind it: one flaky
    # registry would otherwise leave the whole dump set unbuilt, and
    # pdb_irr_as_set_cleanup --commit needs every source present.
    specs = (
        {
            "name": "BELL",
            "serial_url": "https://registry.example/BELL.CURRENTSERIAL",
            "files": (("bell.db.gz", "https://registry.example/bell.db.gz"),),
        },
        {
            "name": "RIPE",
            "serial_url": "https://registry.example/RIPE.CURRENTSERIAL",
            "files": (("ripe.db.gz", "https://registry.example/ripe.db.gz"),),
        },
    )
    monkeypatch.setattr(irr_bulk, "DUMP_SOURCES", specs)
    install_responses(
        monkeypatch,
        {
            specs[0]["serial_url"]: b"42\n",
            specs[0]["files"][0][1]: OSError("data connection dropped"),
            specs[1]["serial_url"]: b"42\n",
            specs[1]["files"][0][1]: gzip_bytes(),
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path))

    by_source = {outcome.source: outcome for outcome in outcomes}
    assert by_source["BELL"].status == "failed"
    assert "data connection dropped" in by_source["BELL"].reason
    # the source behind the failure was still refreshed
    assert by_source["RIPE"].status == "updated"
    assert irr_bulk.load_index(str(tmp_path))["AS-EXAMPLE"] == {"RIPE"}
    # and the incomplete set still refuses to be written from
    missing, _stale = irr_bulk.dump_health(str(tmp_path))
    assert missing == ["BELL"]


@mock.patch("peeringdb_server.irr_bulk.fetch_dumps")
def test_fetch_command_exits_nonzero_when_a_source_failed(fetch_dumps, tmp_path):
    # "failed" (no usable dump at all) is at least as serious as "stale", so it
    # must also produce a non-zero exit rather than a quiet line among 17.
    fetch_dumps.return_value = [
        irr_bulk.FetchOutcome(
            "RIPE", "updated", (str(tmp_path / "a.gz"),), "downloaded"
        ),
        irr_bulk.FetchOutcome(
            "BELL",
            "failed",
            (str(tmp_path / "b.gz"),),
            "could not fetch ftp://example/bell.db.gz: boom",
        ),
    ]
    output = StringIO()

    with pytest.raises(CommandError, match=r"BELL \[failed\]"):
        call_command("pdb_irr_as_set_fetch", "--commit", stdout=output)

    assert "[failed] BELL" in output.getvalue()


def test_fetch_stages_downloads_outside_the_dump_dir(
    tmp_path, monkeypatch, dump_source
):
    # A fetch killed mid-download must not leave anything load_index would glob as
    # a dump, so staging happens in a dotted subdirectory, not the dump dir.
    staged = {}

    real_download = irr_bulk._download_to_temp

    def capture(url, destination):
        path = real_download(url, destination)
        staged["path"] = path
        return path

    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: gzip_bytes(),
        },
    )
    monkeypatch.setattr(irr_bulk, "_download_to_temp", capture)

    irr_bulk.fetch_dumps(str(tmp_path))

    assert staged["path"].startswith(str(tmp_path / ".staging"))


def test_fetch_clears_staging_leftovers(tmp_path, monkeypatch, dump_source):
    staging = tmp_path / ".staging"
    staging.mkdir()
    orphan = staging / "ripe.db.gz.killed.gz"
    orphan.write_bytes(b"\x1f\x8b truncated")
    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: b"42\n",
            dump_source["files"][0][1]: gzip_bytes(),
        },
    )

    irr_bulk.fetch_dumps(str(tmp_path))

    assert not orphan.exists()


def test_fetch_falls_back_to_age_when_serial_endpoint_fails(
    tmp_path, monkeypatch, dump_source
):
    # While a registry's CURRENTSERIAL is unreachable but its dump is served fine,
    # the age check must still apply -- otherwise the full dump is re-downloaded on
    # every run (hundreds of MB against a third party), and no serial marker is
    # written afterwards either, so the next run repeats it.
    write_dump(tmp_path / "ripe.db.gz")
    calls = install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: OSError("serial endpoint down"),
            dump_source["files"][0][1]: gzip_bytes(),
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path), max_age_hours=24)

    assert outcomes[0].status == "fresh"
    assert "serial unavailable" in outcomes[0].reason
    # only the serial was attempted; the dump was not re-downloaded
    assert calls == [dump_source["serial_url"]]


def test_fetch_downloads_when_serial_fails_and_cache_is_too_old(
    tmp_path, monkeypatch, dump_source
):
    write_dump(tmp_path / "ripe.db.gz")
    install_responses(
        monkeypatch,
        {
            dump_source["serial_url"]: OSError("serial endpoint down"),
            dump_source["files"][0][1]: gzip_bytes(),
        },
    )

    outcomes = irr_bulk.fetch_dumps(str(tmp_path), max_age_hours=0)

    assert outcomes[0].status == "updated"
    assert "without serial marker" in outcomes[0].reason


def test_valid_dump_cheap_check_does_not_expand_whole_file(tmp_path):
    # the no-op freshness path must not gzip-expand every cached dump end to end
    # (minutes of CPU per run across the whole-database dumps)
    path = tmp_path / "big.db.gz"
    write_dump(path, b"as-set: AS-EXAMPLE\nsource: RIPE\n\n" * 200_000)

    reads = []
    real_open = gzip.open

    def counting_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        real_read = handle.read

        def read(size=-1):
            reads.append(size)
            return real_read(size)

        handle.read = read
        return handle

    with mock.patch("peeringdb_server.irr_bulk.gzip.open", counting_open):
        assert irr_bulk._valid_dump(str(path)) is True
        cheap_reads = len(reads)
        reads.clear()
        assert irr_bulk._valid_dump(str(path), full=True) is True

    assert cheap_reads == 1  # one chunk, then stop
    assert len(reads) > cheap_reads  # the full check reads to the end


def test_dump_problem_distinguishes_too_large_from_corrupt(tmp_path):
    corrupt = tmp_path / "corrupt.db.gz"
    corrupt.write_bytes(b"not gzip at all")
    assert "unreadable" in irr_bulk._dump_problem(str(corrupt))

    empty = tmp_path / "empty.db.gz"
    empty.write_bytes(b"")
    assert irr_bulk._dump_problem(str(empty)) == "empty"

    assert irr_bulk._dump_problem(str(tmp_path / "nope.db.gz")) == "missing"

    big = tmp_path / "big.db.gz"
    write_dump(big, b"x" * 1024)
    with override_settings(IRR_BULK_DUMP_MAX_UNCOMPRESSED_BYTES=8):
        assert "MAX_UNCOMPRESSED_BYTES" in irr_bulk._dump_problem(str(big), full=True)


def test_plan_fetch_reports_would_download_without_a_cache(
    tmp_path, monkeypatch, dump_source
):
    # a dry run must be able to answer on a cold host, so it neither requests
    # anything nor creates the dump directory it is asked about
    open_url = mock.Mock()
    monkeypatch.setattr(irr_bulk, "_open_url", open_url)
    dump_dir = tmp_path / "not-created-yet"

    outcomes = irr_bulk.plan_fetch(str(dump_dir))

    assert [(o.source, o.status) for o in outcomes] == [("RIPE", "would-download")]
    assert "no usable cache" in outcomes[0].reason
    open_url.assert_not_called()
    assert not dump_dir.exists()


def test_plan_fetch_reports_a_usable_cache_as_serial_decided(
    tmp_path, monkeypatch, dump_source
):
    # the serial endpoint decides a usable cache's fate, and asking it is load on
    # someone else's server -- so the dry run says "only if the serial moved"
    # rather than guessing
    open_url = mock.Mock()
    monkeypatch.setattr(irr_bulk, "_open_url", open_url)
    write_dump(tmp_path / "ripe.db.gz")

    outcomes = irr_bulk.plan_fetch(str(tmp_path))

    assert outcomes[0].status == "serial-decides"
    assert "serial" in outcomes[0].reason
    open_url.assert_not_called()


def test_plan_fetch_does_not_call_an_old_cache_a_download(
    tmp_path, monkeypatch, dump_source
):
    """
    An aged cache is still the serial's call, not mtime's.

    Once the cache is valid `_fetch_source` compares the published serial and
    ignores file age entirely, so a source whose serial has not moved in longer
    than the age limit -- a quiet RADB mirror, not RIPE -- is `fresh` to the real
    run however old the file is. Reporting "would-download" off mtime here would
    promise a download that never happens, on the steady-state branch.
    """
    write_dump(tmp_path / "ripe.db.gz")

    outcomes = irr_bulk.plan_fetch(str(tmp_path), max_age_hours=0)

    assert outcomes[0].status == "serial-decides"
    # the age is still reported, it just does not decide
    assert "old" in outcomes[0].reason


def test_plan_fetch_reports_a_stale_cache_without_a_serial(tmp_path, monkeypatch):
    # no serial to consult -> file age IS the whole decision in the real run too,
    # so here it can be asserted
    monkeypatch.setattr(
        irr_bulk,
        "DUMP_SOURCES",
        ({"name": "RIPE", "files": (("ripe.db.gz", "https://x/ripe.db.gz"),)},),
    )
    write_dump(tmp_path / "ripe.db.gz")

    stale = irr_bulk.plan_fetch(str(tmp_path), max_age_hours=0)
    current = irr_bulk.plan_fetch(str(tmp_path))

    assert stale[0].status == "would-download"
    assert "older than" in stale[0].reason
    assert current[0].status == "fresh"


def test_plan_fetch_reason_tracks_the_local_serial_marker(
    tmp_path, monkeypatch, dump_source
):
    """
    Both states are `serial-decides`, but not for the same reason.

    With no local marker `_fetch_source` has nothing to compare the published
    serial against, so the shortcut cannot fire and the age fallback is skipped
    too -- it downloads. That is reachable in normal operation: a --commit run
    whose serial endpoint hiccuped downloads and writes no marker. Reading the
    marker is a local file read, so the reason can say which condition applies
    without breaking the offline rule.
    """
    write_dump(tmp_path / "ripe.db.gz")

    markerless = irr_bulk.plan_fetch(str(tmp_path))[0]
    assert markerless.status == "serial-decides"
    assert "no local serial marker" in markerless.reason

    (tmp_path / ".ripe.serial").write_text("12345\n")
    marked = irr_bulk.plan_fetch(str(tmp_path))[0]
    assert marked.status == "serial-decides"
    assert "no local serial marker" not in marked.reason
    assert "published serial moved" in marked.reason
    # and the other half of what the real run does: endpoint down falls back to age
    assert "unreachable" in marked.reason


def test_plan_fetch_reports_force_as_a_download(tmp_path, monkeypatch, dump_source):
    write_dump(tmp_path / "ripe.db.gz")

    forced = irr_bulk.plan_fetch(str(tmp_path), force=True)

    assert forced[0].status == "would-download"
    assert "--force" in forced[0].reason


def test_plan_fetch_rejects_unknown_source(tmp_path, monkeypatch, dump_source):
    open_url = mock.Mock()
    monkeypatch.setattr(irr_bulk, "_open_url", open_url)

    with pytest.raises(irr_bulk.BulkFetchError, match="unknown IRR dump source"):
        irr_bulk.plan_fetch(str(tmp_path), source_names=["NOT-AN-IRR"])

    open_url.assert_not_called()


@mock.patch("peeringdb_server.irr_bulk.fetch_dumps")
@mock.patch("peeringdb_server.irr_bulk.plan_fetch")
def test_fetch_command_without_commit_plans_and_downloads_nothing(
    plan_fetch, fetch_dumps, tmp_path
):
    # dry-run by default with --commit for the real thing, like every other
    # command in this suite -- so a run without --commit must reach plan_fetch and
    # never fetch_dumps
    plan_fetch.return_value = [
        irr_bulk.FetchOutcome(
            "RIPE",
            "would-download",
            (str(tmp_path / "ripe.db.gz"),),
            "no usable cache: ripe.db.gz missing",
        ),
        irr_bulk.FetchOutcome(
            "RADB",
            "serial-decides",
            (str(tmp_path / "radb.db.gz"),),
            "cache 2.0h old; downloads only if the published serial moved",
        ),
    ]
    output = StringIO()

    call_command("pdb_irr_as_set_fetch", "--dump-dir", str(tmp_path), stdout=output)

    # the base class marks dry-run lines [pretend], as in the sibling commands
    assert "[pretend] [would-download] RIPE: ripe.db.gz" in output.getvalue()
    assert "1 would download" in output.getvalue()
    assert "1 download only if the published serial moved" in output.getvalue()
    fetch_dumps.assert_not_called()
    plan_fetch.assert_called_once_with(
        dump_dir=str(tmp_path),
        source_names=None,
        force=False,
        max_age_hours=None,
    )


@mock.patch("peeringdb_server.irr_bulk.plan_fetch")
def test_fetch_command_without_commit_does_not_fail_on_would_download(
    plan_fetch, tmp_path
):
    # "would download" is the normal answer, not the failure the real run reports
    # for a stale or unfetchable source, so a dry run stays exit 0
    plan_fetch.return_value = [
        irr_bulk.FetchOutcome(
            "RIPE", "would-download", (str(tmp_path / "ripe.db.gz"),), "no usable cache"
        )
    ]

    call_command("pdb_irr_as_set_fetch", stdout=StringIO())
