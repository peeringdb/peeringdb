"""
Tests for pdb_irr_as_set_cleanup (#1973), the cleanup/report that supersedes the
standalone pdb_audit_irr_as_set (its classifier folded in), plus the bulk IRR
dump index (irr_bulk) that powers the found-in-one/many/nowhere registry split.

Without --commit the command never modifies the database; --commit auto-prefixes
the found-in-one (unambiguous) bare values.
"""

import gzip
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone
from reversion.models import Version

from peeringdb_server import irr_bulk
from peeringdb_server.irr import LookupResult
from peeringdb_server.management.commands.pdb_irr_as_set_cleanup import (
    Command,
    auto_prefix_value,
    classify_irr_as_set,
    classify_network,
    partly_prefixed,
    registry_split,
)
from peeringdb_server.models import Network, NetworkContact, Organization
from tests.util import write_irr_dump_set

# a name published in two registries -> found-in-many (ambiguous)
MULTI_DUMP = "as-set:  AS-MULTI\nsource:  RIPE\n\nas-set:  AS-MULTI\nsource:  RADB\n"

# every test needs the DB: the autouse cleanup fixture clears the geo
# DatabaseCache, which hits the DB even for the pure-function tests.
pytestmark = pytest.mark.django_db


def live_pool(sources_by_name, default=LookupResult(frozenset(), True)):
    """
    An `irr.sources_for` side_effect driven by the queried name.

    Auto-prefix now takes a live second opinion before writing (it must agree the
    name is held by exactly the one source the index picked), so a --commit test
    that expects a rewrite has to say what the pool reports.
    """

    def _sources_for(name, object_class=None):
        return sources_by_name.get(name.upper(), default)

    return _sources_for


@pytest.mark.parametrize(
    "value,category",
    [
        ("RIPE::AS-FOO", "prefixed"),
        ("RIPE::AS-FOO RADB::AS-BAR", "prefixed"),
        ("ripe::as-foo", "prefixed"),
        ("AS-FOO", "bare"),
        ("RIPE::AS-FOO AS-BAR", "bare"),
        ("AS15562", "bare"),
        ("AS-SET", "placeholder"),
        ("RIPE::AS-SET", "placeholder"),
        ("as-any", "placeholder"),
        ("UNKNOWN::AS-FOO", "invalid"),
        ("AS-Resound Networks,LLC", "invalid"),
    ],
)
@pytest.mark.django_db
def test_classify_irr_as_set(value, category):
    # django_db: the autouse cleanup fixture clears the geo DatabaseCache (DB).
    result, _note = classify_irr_as_set(value)
    assert result == category


# --- bulk index (irr_bulk) ---------------------------------------------------

SAMPLE_DUMP = """\
as-set:         AS-FOO
descr:          example
members:        AS1, AS2
source:         RIPE

as-set:         AS-BAR
members:        AS3
source:         RADB

route-set:      RS-THING
source:         RADB

aut-num:        AS15562
source:         RIPE

# a person object we should ignore
person:         Jane Doe
source:         RIPE
"""


def test_parse_rpsl_extracts_target_objects():
    objs = list(irr_bulk.parse_rpsl(SAMPLE_DUMP.splitlines()))
    assert ("as-set", "AS-FOO", "RIPE") in objs
    assert ("as-set", "AS-BAR", "RADB") in objs
    assert ("route-set", "RS-THING", "RADB") in objs
    assert ("aut-num", "AS15562", "RIPE") in objs
    # the person object is not a target class
    assert all(cls != "person" for cls, _k, _s in objs)


def test_parse_rpsl_accepts_streaming_lines():
    objs = list(irr_bulk.parse_rpsl(StringIO(SAMPLE_DUMP)))
    assert ("as-set", "AS-FOO", "RIPE") in objs
    assert ("aut-num", "AS15562", "RIPE") in objs


def test_parse_rpsl_rejects_whole_dump_string():
    # a str is iterable one character at a time, which would silently parse to
    # nothing -- and holding a multi-GB dump as a string is what streaming here
    # set out to stop doing, so it is refused explicitly.
    with pytest.raises(TypeError, match="iterable of lines"):
        list(irr_bulk.parse_rpsl(SAMPLE_DUMP))


def test_build_index_and_sources_for_bulk(tmp_path):
    dump = tmp_path / "sample.db"
    dump.write_text(SAMPLE_DUMP)
    index = irr_bulk.build_index([str(dump)])
    assert irr_bulk.sources_for_bulk("AS-FOO", index) == frozenset({"RIPE"})
    assert irr_bulk.sources_for_bulk("as-foo", index) == frozenset({"RIPE"})  # case
    assert irr_bulk.sources_for_bulk("AS-MISSING", index) == frozenset()


def test_load_index_none_without_dumps(tmp_path):
    assert irr_bulk.load_index(str(tmp_path)) is None  # empty dir
    assert irr_bulk.load_index("/no/such/dir") is None


# edge cases: an object with no source line, an unknown (untracked) source, a
# continuation line, and a target object at EOF with no trailing blank line.
# Built with explicit newlines so the last object has NO trailing blank (it must
# still be flushed at end-of-input).
EDGE_DUMP = (
    "as-set:         AS-NOSOURCE\n"
    "members:        AS9\n"
    "\n"
    "as-set:         AS-NONAUTH\n"
    "source:         RIPE-NONAUTH\n"
    "\n"
    "as-set:         AS-WRAP\n"
    "members:        AS1,\n"
    "                AS2\n"
    "source:         RADB"
)


def test_parse_rpsl_edge_cases():
    objs = list(irr_bulk.parse_rpsl(EDGE_DUMP.splitlines()))
    keys = {k for _c, k, _s in objs}
    # a target object at EOF (no trailing blank line) is still flushed
    assert "AS-WRAP" in keys
    # an object with no source: line is yielded with an empty source
    nosrc = [o for o in objs if o[1] == "AS-NOSOURCE"]
    assert nosrc and nosrc[0][2] == ""


def test_build_index_excludes_unknown_and_sourceless(tmp_path):
    dump = tmp_path / "edge.db"
    dump.write_text(EDGE_DUMP)
    index = irr_bulk.build_index([str(dump)])
    # RIPE-NONAUTH is not in IRR_SOURCE -> excluded
    assert irr_bulk.sources_for_bulk("AS-NONAUTH", index) == frozenset()
    # a source-less object -> excluded
    assert irr_bulk.sources_for_bulk("AS-NOSOURCE", index) == frozenset()
    # AS-WRAP is indexed under RADB despite the continuation line + EOF flush
    assert irr_bulk.sources_for_bulk("AS-WRAP", index) == frozenset({"RADB"})


def test_build_index_reads_gzip(tmp_path):
    path = tmp_path / "sample.db.gz"
    with gzip.open(path, "wt") as fh:
        fh.write(SAMPLE_DUMP)
    index = irr_bulk.build_index([str(path)])
    assert irr_bulk.sources_for_bulk("AS-FOO", index) == frozenset({"RIPE"})


def test_registry_split_precedence():
    # AS-ONE in one source, AS-MANY in two, AS-NONE in none
    index = {"AS-ONE": {"RIPE"}, "AS-MANY": {"RIPE", "RADB"}}
    assert registry_split("AS-ONE", index) == "one"
    assert registry_split("AS-MANY", index) == "many"
    assert registry_split("AS-NONE", index) == "nowhere"
    # nowhere outranks one when a value mixes them
    assert registry_split("AS-ONE AS-NONE", index) == "nowhere"
    # an already-prefixed token in a mixed value is skipped; only the bare one
    # is resolved
    assert registry_split("RIPE::AS-MANY AS-ONE", index) == "one"


def test_registry_split_resolves_bare_asn_tokens():
    """
    Bare ASN tokens are bucketed like any other bare token, so the report is not
    silent about rows auto_prefix_value rewrites and _notify_reason mails.
    """
    index = {
        "AS64500": {"RIPE"},
        "AS64501": {"RIPE", "RADB"},
        "AS-ONE": {"RIPE"},
    }
    assert registry_split("AS64500", index) == "one"
    assert registry_split("AS64501", index) == "many"
    # not registered in any indexed registry
    assert registry_split("AS64502", index) == "nowhere"
    # an ambiguous ASN outranks a resolvable set name in a mixed value
    assert registry_split("AS-ONE AS64501", index) == "many"
    # only a value with no bare tokens at all yields None
    assert registry_split("RIPE::AS-ONE", index) is None


def test_auto_prefix_value():
    index = {
        "AS-ONE": {"RIPE"},
        "AS-TWO": {"RADB"},
        "AS-MANY": {"RIPE", "RADB"},
        "AS-SET": {"RIPE"},
        "RS-ONE": {"RADB"},
    }
    # found in exactly one -> prefixed
    assert auto_prefix_value("AS-ONE", index) == "RIPE::AS-ONE"
    # every bare token resolves unambiguously -> all prefixed, space-separated
    assert auto_prefix_value("AS-ONE AS-TWO", index) == "RIPE::AS-ONE RADB::AS-TWO"
    # an already-prefixed token is kept; the bare one is resolved
    assert (
        auto_prefix_value("RADB::AS-BAR AS-ONE", index) == "RADB::AS-BAR RIPE::AS-ONE"
    )
    # found in several registries -> not safe to auto-fix
    assert auto_prefix_value("AS-MANY", index) is None
    # found nowhere -> not auto-fixed
    assert auto_prefix_value("AS-GHOST", index) is None
    # an ambiguous token no longer taints the whole value -- the unambiguous
    # one is still prefixed and the ambiguous one is left exactly as it was
    assert auto_prefix_value("AS-ONE AS-MANY", index) == "RIPE::AS-ONE AS-MANY"
    # same for a token found nowhere
    assert auto_prefix_value("AS-ONE AS-GHOST", index) == "RIPE::AS-ONE AS-GHOST"
    # a route-set is never auto-prefixed, even when found in exactly one
    assert auto_prefix_value("RS-ONE", index) is None
    # ... and it does not stop the resolvable token beside it
    assert auto_prefix_value("AS-ONE RS-ONE", index) == "RIPE::AS-ONE RS-ONE"
    # a generic placeholder is never auto-prefixed even if a dump contains it
    assert auto_prefix_value("AS-SET", index) is None
    assert auto_prefix_value("AS-ONE AS-SET", index) == "RIPE::AS-ONE AS-SET"
    # nothing to change (already fully prefixed) -> None
    assert auto_prefix_value("RIPE::AS-ONE", index) is None
    # nothing resolvable at all -> None, so no pointless rewrite is proposed
    assert auto_prefix_value("AS-MANY AS-GHOST", index) is None


def test_partly_prefixed():
    """
    Drives whether the disclosure mail may say "no action is needed". It must be
    true for every reason a token can be left alone, not just the ambiguous one.
    """
    assert partly_prefixed("RIPE::AS-ONE AS-MANY") is True
    assert partly_prefixed("RIPE::AS-ONE AS-GHOST") is True
    assert partly_prefixed("RIPE::AS-ONE RS-ONE") is True
    assert partly_prefixed("RIPE::AS-ONE AS-SET") is True
    assert partly_prefixed("RIPE::AS-ONE RADB::AS-TWO") is False
    assert partly_prefixed("RIPE::AS-ONE") is False
    # an unknown registry prefix is not a pin, so the value is not fully fixed
    assert partly_prefixed("NOTAREGISTRY::AS-ONE") is True


# --- command (dry-run) -------------------------------------------------------


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org", status="ok")


def make_network(org, asn, irr_as_set, status="ok"):
    # Network.save() does not call clean(), so this stores bare/invalid values
    # the way legacy / bulk-imported rows exist in prod.
    return Network.objects.create(
        name=f"Network {asn}",
        asn=asn,
        irr_as_set=irr_as_set,
        status=status,
        org=org,
    )


def add_contact(net, role="Technical", email="tech@example.com"):
    return NetworkContact.objects.create(
        network=net, role=role, email=email, status="ok"
    )


@pytest.mark.django_db
def test_cleanup_summary_counts(org):
    make_network(org, 2001, "RIPE::AS-FOO")  # prefixed
    make_network(org, 2002, "AS-FOO")  # bare
    make_network(org, 2003, "AS-SET")  # placeholder
    make_network(org, 2004, "UNKNOWN::AS-FOO")  # invalid
    make_network(org, 2005, "")  # skipped (no value)
    make_network(org, 2006, "AS-BAR", status="deleted")  # skipped (not ok)

    out = StringIO()
    call_command("pdb_irr_as_set_cleanup", stdout=out)
    output = out.getvalue()

    assert "Networks with a value:       4" in output
    assert "prefixed (SOURCE::):       1" in output
    assert "bare (no IRR source):      1" in output
    assert "placeholder (AS-SET/etc):  1" in output
    assert "invalid (fails validator): 1" in output
    assert "Actionable (bare+placeholder+invalid): 3" in output
    # no bulk dumps configured -> registry split not computed
    assert "Registry split (found-in-one" in output


@pytest.mark.django_db
def test_cleanup_reports_multi_and_route_set(org):
    make_network(org, 2101, "RIPE::AS-FOO RADB::AS-BAR")  # multi-set
    make_network(org, 2102, "RIPE::RS-THING")  # route-set

    out = StringIO()
    call_command("pdb_irr_as_set_cleanup", stdout=out)
    output = out.getvalue()
    assert "multi-set (#1974):         1" in output
    assert "route-set (#1974):         1" in output


@pytest.mark.django_db
def test_cleanup_registry_split_with_dump_dir(org, tmp_path):
    make_network(org, 2201, "AS-FOO")  # bare, found in one (RIPE)
    make_network(org, 2202, "AS-GHOST")  # bare, found nowhere

    dump = tmp_path / "sample.db"
    dump.write_text(SAMPLE_DUMP)

    out = StringIO()
    call_command("pdb_irr_as_set_cleanup", "--dump-dir", str(tmp_path), stdout=out)
    output = out.getvalue()
    assert "Registry split of bare values" in output
    assert "found in exactly one:      1" in output
    assert "found nowhere:             1" in output


@pytest.mark.django_db
def test_cleanup_does_not_modify_db(org):
    net = make_network(org, 2301, "AS-FOO")
    call_command("pdb_irr_as_set_cleanup", stdout=StringIO())
    net.refresh_from_db()
    assert net.irr_as_set == "AS-FOO"


@pytest.mark.django_db
def test_cleanup_commit_auto_prefixes(org, tmp_path):
    one = make_network(org, 2401, "AS-FOO")  # found in exactly one (RIPE)
    ghost = make_network(org, 2402, "AS-GHOST")  # found nowhere
    already = make_network(org, 2403, "RIPE::AS-FOO")  # already prefixed

    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE"], True)}),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=out,
        )
    output = out.getvalue()

    one.refresh_from_db()
    ghost.refresh_from_db()
    already.refresh_from_db()
    assert one.irr_as_set == "RIPE::AS-FOO"  # auto-prefixed
    assert ghost.irr_as_set == "AS-GHOST"  # left for outreach
    assert already.irr_as_set == "RIPE::AS-FOO"  # untouched
    assert "[auto-prefix] id:" in output
    assert "Auto-prefixed (--commit):    1 of 1" in output
    # the report is no longer labelled "dry-run" when it describes applied changes
    assert "(status=ok, commit)" in output
    assert "dry-run" not in output


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_commit_notifies_auto_prefixed_network(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    An auto-prefixed network is told its value changed: applied without asking, but
    not without telling. The notice carries the previous value, since by send time
    net.irr_as_set already holds the new one.
    """
    net = make_network(org, 2450, "AS-FOO")  # found in exactly one (RIPE)
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE"], True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=out,
            )

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO"
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "RIPE::AS-FOO" in body  # the new value
    assert "AS-FOO" in body
    assert "source prefix added" in mail.outbox[0].subject
    assert "disclosure notice queued for 1 of those network(s)." in out.getvalue()
    # every applied row was notified, so there is no remainder to explain
    assert "no eligible contact" not in out.getvalue()
    # the disclosure must not burn the outreach cursor -- a later problem with this
    # network still has to be mailable
    assert net.irr_as_set_notified is None


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_commit_auto_prefixes_without_contacts(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    No eligible contact does not block the rewrite -- it stands on being unambiguous
    and version-tracked, not on the network being reachable.
    """
    net = make_network(org, 2451, "AS-FOO")  # no contacts added
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE"], True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=out,
            )

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO"  # still fixed
    assert mail.outbox == []
    assert "[auto-prefix:unnotified] id:" in out.getvalue()
    assert (
        "disclosure notice queued for 0 of those network(s); no eligible contact "
        "for the other 1 network(s)." in out.getvalue()
    )


@pytest.mark.django_db
def test_cleanup_commit_skips_row_changed_during_the_run(org, tmp_path):
    """
    A row the operator edited between classification and write is left alone.

    The pool mock stands in for that window -- it fires during confirmation, which
    is when a concurrent edit would land.
    """
    net = make_network(org, 2440, "AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    def _pool_then_edit(name, object_class=None):
        # simulate the operator saving their own value mid-run
        Network.objects.filter(id=net.id).update(irr_as_set="RADB::AS-MINE")
        return LookupResult(["RIPE"], True)

    out = StringIO()
    with mock.patch("peeringdb_server.irr.sources_for", side_effect=_pool_then_edit):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=out,
        )
    output = out.getvalue()

    net.refresh_from_db()
    # the operator's value survives; the campaign did not write over it
    assert net.irr_as_set == "RADB::AS-MINE"
    assert "[skip:superseded] id:" in output
    assert "Auto-prefixed (--commit):    0 of 1" in output
    assert "the operator's own value wins" in output
    # the cap must not be blamed for a row it did not stop
    assert "left unexamined by --max-changes" not in output


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_notifies_unresolved_bare_asn(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    A found-nowhere bare ASN is live-confirmed and mailed like any other token.

    _confirm_unresolved used to skip ASN tokens, so an ASN-only value could be
    counted as found-nowhere yet never produce the mail the report promised.
    """
    net = make_network(org, 2441, "AS64502")  # no aut-num in the dump set
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        # definitive "held nowhere" -> the disappearance is confirmed
        side_effect=live_pool({}, default=LookupResult(frozenset(), True)),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=out,
            )

    assert "[notify:unresolved] id:" in out.getvalue()
    assert len(mail.outbox) == 1
    assert "AS64502" in mail.outbox[0].body
    net.refresh_from_db()
    assert net.irr_as_set_notified is not None


@pytest.mark.django_db
def test_cleanup_commit_requires_dump_index(org):
    make_network(org, 2410, "AS-FOO")
    with pytest.raises(CommandError):
        call_command("pdb_irr_as_set_cleanup", "--commit", stdout=StringIO())


@pytest.mark.parametrize("option", ["--max-changes", "--max-notifications"])
def test_cleanup_rejects_negative_bounds(option):
    with pytest.raises(CommandError, match="must be zero or greater"):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            option,
            "-1",
            stdout=StringIO(),
        )


@pytest.mark.parametrize("option", ["--max-changes", "--max-notifications"])
def test_cleanup_commit_rejects_uncapped_bounds(option):
    # 0 uncaps the live pool fan-out under --commit, and for --max-changes the
    # disclosure mail with it -- one per rewrite, and nothing else bounds it.
    with pytest.raises(CommandError, match="needs a positive"):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            option,
            "0",
            stdout=StringIO(),
        )


@pytest.mark.django_db
@pytest.mark.parametrize("option", ["--max-changes", "--max-notifications"])
def test_cleanup_dry_run_allows_uncapped_bounds(org, option):
    # the guard is about writes and mail, so it must not touch the report path
    make_network(org, 2415, "AS-FOO")
    call_command("pdb_irr_as_set_cleanup", option, "0", stdout=StringIO())


@pytest.mark.django_db
def test_cleanup_dry_run_with_index_does_not_write(org, tmp_path):
    net = make_network(org, 2420, "AS-FOO")  # would be a found-in-one candidate
    dump = tmp_path / "sample.db"
    dump.write_text(SAMPLE_DUMP)

    call_command(
        "pdb_irr_as_set_cleanup", "--dump-dir", str(tmp_path), stdout=StringIO()
    )
    net.refresh_from_db()
    assert net.irr_as_set == "AS-FOO"  # no --commit -> unchanged


@pytest.mark.django_db
def test_cleanup_commit_respects_max_changes(org, tmp_path):
    # AS-FOO (RIPE) and AS-BAR (RADB) are both found-in-one candidates
    a = make_network(org, 2431, "AS-FOO")
    b = make_network(org, 2432, "AS-BAR")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool(
            {
                "AS-FOO": LookupResult(["RIPE"], True),
                "AS-BAR": LookupResult(["RADB"], True),
            }
        ),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--max-changes",
            "1",
            stdout=out,
        )
    output = out.getvalue()

    a.refresh_from_db()
    b.refresh_from_db()
    # exactly one of the two candidates was rewritten (the cap stopped the rest)
    changed = [n for n in (a, b) if "::" in n.irr_as_set]
    assert len(changed) == 1
    assert "Auto-prefixed (--commit):    1 of 2" in output
    assert "left unexamined by --max-changes 1" in output


@pytest.mark.django_db
def test_cleanup_max_changes_is_bounded_by_default(org, tmp_path):
    # Must NOT default to "no cap": each candidate costs a live pool confirmation
    # (~3.4s), so uncapped over the real ~11k candidates is ~10h -- killed by any job
    # deadline, and the writes land after that loop, so a kill commits nothing.
    parser = Command().create_parser("manage.py", "pdb_irr_as_set_cleanup")
    default = parser.get_default("max_changes")

    assert default > 0
    assert default == 100


@pytest.mark.django_db
def test_cleanup_detail_lists_flagged_rows(org):
    make_network(org, 2501, "RIPE::AS-FOO")  # prefixed -> not listed
    make_network(org, 2502, "AS-FOO")  # bare -> listed

    out = StringIO()
    call_command("pdb_irr_as_set_cleanup", "--detail", stdout=out)
    output = out.getvalue()
    assert "[bare] id:" in output
    assert "asn:2502" in output
    assert "asn:2501" not in output


# --- outreach notifications (--commit) ---------------------------------------


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_notifies_found_nowhere_when_confirmed(
    org, tmp_path, django_capture_on_commit_callbacks
):
    net = make_network(org, 2601, "AS-GHOST")  # bare, found nowhere
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    mail.outbox = []
    # live pool confirms the name is in no registry (ok, empty)
    with mock.patch(
        "peeringdb_server.irr.sources_for", return_value=LookupResult([], True)
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=StringIO(),
            )

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["tech@example.com"]
    assert "AS2601" in mail.outbox[0].subject
    assert "could not be found" in mail.outbox[0].body.lower()


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_notifies_route_set_found_in_one(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # RS-THING is in exactly one registry (bucket "one") but is a route-set, so
    # it can't be auto-prefixed -- it must still be notified (regression: it used
    # to be silently dropped because bucket=="one").
    net = make_network(org, 2650, "RS-THING")
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    assert len(mail.outbox) == 1
    assert net.irr_as_set == "RS-THING"  # not auto-prefixed
    assert "route-set" in mail.outbox[0].subject.lower()


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
@pytest.mark.parametrize(
    "value,subject_fragment,body_fragment",
    [
        ("AS-SET", "generic placeholder", "generic placeholder"),
        ("RIPE::AS-SET", "generic placeholder", "generic placeholder"),
        ("RADB::RS-THING", "route-set", "route-set"),
    ],
)
def test_cleanup_notifies_placeholder_and_prefixed_route_set(
    org,
    tmp_path,
    django_capture_on_commit_callbacks,
    value,
    subject_fragment,
    body_fragment,
):
    net = make_network(org, 2651, value)
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    mail.outbox = []
    with mock.patch("peeringdb_server.irr.sources_for") as sources_for:
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=StringIO(),
            )

    assert len(mail.outbox) == 1
    assert subject_fragment in mail.outbox[0].subject.lower()
    assert body_fragment in mail.outbox[0].body.lower()
    # These values are structurally invalid; no live disappearance check is
    # needed to decide that outreach is appropriate.
    sources_for.assert_not_called()


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_notifies_found_in_many(
    org, tmp_path, django_capture_on_commit_callbacks
):
    net = make_network(org, 2602, "AS-MULTI")  # bare, found in RIPE + RADB
    add_contact(net, role="Policy", email="policy@example.com")
    write_irr_dump_set(tmp_path, MULTI_DUMP)

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["policy@example.com"]
    assert "ambiguous" in mail.outbox[0].subject.lower()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "live_result",
    [LookupResult(["RADB"], True), LookupResult([], False)],
    ids=["pool-finds-it", "pool-unreachable"],
)
def test_cleanup_found_nowhere_not_emailed_without_confirmation(
    org, tmp_path, django_capture_on_commit_callbacks, live_result
):
    net = make_network(org, 2603, "AS-GHOST")
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    mail.outbox = []
    # either the live pool finds the name (stale dump) or it can't answer
    # (outage) -> no disappearance confirmed -> no warning goes out
    with mock.patch("peeringdb_server.irr.sources_for", return_value=live_result):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=StringIO(),
            )

    assert mail.outbox == []


@pytest.mark.django_db
def test_cleanup_no_contacts_no_email_no_live_lookup(
    org, tmp_path, django_capture_on_commit_callbacks
):
    make_network(org, 2604, "AS-GHOST")  # no contact
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    mail.outbox = []
    with mock.patch("peeringdb_server.irr.sources_for") as sources_for:
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=StringIO(),
            )

    assert mail.outbox == []
    # recipients are checked before any live lookup, so the pool is never hit
    sources_for.assert_not_called()


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_respects_max_notifications(
    org, tmp_path, django_capture_on_commit_callbacks
):
    add_contact(make_network(org, 2611, "AS-MULTI"), email="a@example.com")
    add_contact(make_network(org, 2612, "AS-MULTI"), email="b@example.com")
    write_irr_dump_set(tmp_path, MULTI_DUMP)

    mail.outbox = []
    out = StringIO()
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--max-notifications",
            "1",
            stdout=out,
        )

    assert len(mail.outbox) == 1
    assert "Notified (--commit):         1" in out.getvalue()


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_max_notifications_bounds_live_rechecks(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # 4 found-nowhere nets with contacts; the live pool never confirms (it finds
    # them -> stale dump), so none are emailed. --max-notifications 2 must still
    # bound the live re-check fan-out to 2 lookups, not one per net.
    for asn in (3061, 3062, 3063, 3064):
        add_contact(make_network(org, asn, f"AS-GHOST{asn}"))
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    mail.outbox = []
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        return_value=LookupResult(["RADB"], True),
    ) as sources_for:
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                "--max-notifications",
                "2",
                stdout=StringIO(),
            )

    assert mail.outbox == []  # none confirmed -> none emailed
    assert sources_for.call_count == 2  # re-check fan-out bounded by the cap


@pytest.mark.django_db
def test_cleanup_rollback_discards_notification_callback(
    org, tmp_path, django_capture_on_commit_callbacks
):
    contradicted = make_network(org, 3070, "AS-BAR")
    auto = make_network(org, 3071, "AS-FOO")
    flagged = make_network(org, 3072, "AS-MULTI")
    add_contact(flagged)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP + MULTI_DUMP)

    with (
        mock.patch(
            "peeringdb_server.irr.sources_for",
            side_effect=live_pool(
                {
                    "AS-BAR": LookupResult(["RIPE", "RADB"], True),
                    "AS-FOO": LookupResult(["RIPE"], True),
                }
            ),
        ),
        mock.patch.object(Network, "save", side_effect=RuntimeError("write failed")),
        mock.patch(
            "peeringdb_server.management.commands.pdb_irr_as_set_cleanup."
            "mail_network_irr_as_set_flagged"
        ) as send_mail,
        pytest.raises(RuntimeError, match="write failed"),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=StringIO(),
            )

    contradicted.refresh_from_db()
    auto.refresh_from_db()
    flagged.refresh_from_db()
    assert auto.irr_as_set == "AS-FOO"
    send_mail.assert_not_called()
    # The contradiction cursor shares the write transaction too. A later write
    # failure must not suppress this candidate on the retry.
    assert contradicted.irr_as_set_auto_prefix_candidate == ""
    assert contradicted.irr_as_set_auto_prefix_checked is None
    # the notified marker is written in the same transaction as the mail, so the
    # rollback must leave the network eligible for outreach on the next run
    assert flagged.irr_as_set_notified is None


@pytest.mark.django_db
def test_cleanup_dry_run_sends_no_mail(
    org, tmp_path, django_capture_on_commit_callbacks
):
    add_contact(make_network(org, 2620, "AS-MULTI"))
    write_irr_dump_set(tmp_path, MULTI_DUMP)

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    assert mail.outbox == []


@override_settings(MAIL_DEBUG=True)
@pytest.mark.django_db
def test_cleanup_mail_debug_suppresses_outreach(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # non-prod guard: with MAIL_DEBUG set, no operator email is put on the wire
    # even though there is a flagged network with a contact.
    add_contact(make_network(org, 2630, "AS-MULTI"))
    write_irr_dump_set(tmp_path, MULTI_DUMP)

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    assert mail.outbox == []


# --- notified-state cursor ---------------------------------------------------


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_second_run_does_not_renotify(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # The "re-run to continue" promise: a network mailed on the first run keeps
    # irr_as_set_notified set and is not mailed again, so --max-notifications is
    # a cursor rather than a truncation that re-mails the same networks forever.
    net = make_network(org, 2701, "AS-MULTI")
    add_contact(net)
    write_irr_dump_set(tmp_path, MULTI_DUMP)

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )
    assert len(mail.outbox) == 1
    net.refresh_from_db()
    assert net.irr_as_set_notified is not None
    first_stamp = net.irr_as_set_notified

    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )
    net.refresh_from_db()
    assert len(mail.outbox) == 1  # no second mail
    assert net.irr_as_set_notified == first_stamp


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_max_notifications_advances_across_runs(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # Two flagged networks, cap of 1: the first run mails one, the second run
    # mails the *other* one. Before the notified marker existed the second run
    # re-mailed the first network and the second was never reached.
    a = make_network(org, 2711, "AS-MULTI")
    b = make_network(org, 2712, "AS-MULTI")
    add_contact(a, email="a@example.com")
    add_contact(b, email="b@example.com")
    write_irr_dump_set(tmp_path, MULTI_DUMP)

    mail.outbox = []
    for _run in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                "--max-notifications",
                "1",
                stdout=StringIO(),
            )

    recipients = sorted(address for message in mail.outbox for address in message.to)
    assert recipients == ["a@example.com", "b@example.com"]


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_renotify_after_days_reopens_outreach(
    org, tmp_path, django_capture_on_commit_callbacks
):
    net = make_network(org, 2721, "AS-MULTI")
    add_contact(net)
    write_irr_dump_set(tmp_path, MULTI_DUMP)
    # already notified 10 days ago
    Network.objects.filter(id=net.id).update(
        irr_as_set_notified=timezone.now() - timedelta(days=10)
    )

    mail.outbox = []
    # a 30-day cadence still considers it recently notified
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--renotify-after-days",
            "30",
            stdout=StringIO(),
        )
    assert mail.outbox == []

    # a 5-day cadence makes it due again
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--renotify-after-days",
            "5",
            stdout=StringIO(),
        )
    assert len(mail.outbox) == 1


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_recheck_budget_does_not_stop_other_reasons(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # A run whose first candidates are all unconfirmed found-nowhere values must
    # still reach the ambiguous candidate behind them: the recheck budget bounds
    # the live fan-out, it does not end the scan.
    for asn in (2731, 2732):
        add_contact(make_network(org, asn, f"AS-GHOST{asn}"), email=f"g{asn}@e.com")
    add_contact(make_network(org, 2733, "AS-MULTI"), email="many@example.com")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP + MULTI_DUMP)

    mail.outbox = []
    # the pool finds the ghosts (stale dump) -> never confirmed -> never mailed
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({}, default=LookupResult(["RADB"], True)),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                "--max-notifications",
                "1",
                stdout=StringIO(),
            )

    assert [address for message in mail.outbox for address in message.to] == [
        "many@example.com"
    ]


# --- invalid values get outreach ---------------------------------------------


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_notifies_invalid_value(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # An outright invalid value cannot be auto-fixed, so outreach is the only way
    # it is ever addressed -- it used to be counted as actionable and then
    # silently dropped (#1973 "1 set name is improperly formatted").
    net = make_network(org, 2801, "UNKNOWN::AS-FOO")
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    assert len(mail.outbox) == 1
    assert "improperly formatted" in mail.outbox[0].subject.lower()
    assert "not a valid AS-SET reference" in mail.outbox[0].body
    assert net.irr_as_set == "UNKNOWN::AS-FOO"  # never rewritten


def test_classify_network_invalid_is_notified():
    index = {"AS-FOO": {"RIPE"}}
    result = classify_network("UNKNOWN::AS-FOO", index, commit=True)
    assert result.category == "invalid"
    assert result.notify_reason == "invalid"
    assert result.prefix_candidate is None


def test_classify_network_dry_run_selects_nothing():
    index = {"AS-FOO": {"RIPE"}}
    result = classify_network("AS-FOO", index, commit=False)
    assert result.category == "bare"
    assert result.bucket == "one"  # the report split is still computed
    assert result.prefix_candidate is None
    assert result.notify_reason is None


# --- writing off a stale / incomplete index ----------------------------------


@pytest.mark.django_db
def test_cleanup_commit_refuses_incomplete_dump_set(org, tmp_path):
    # One registry's dump missing makes a genuinely ambiguous name look
    # unambiguous, so --commit must refuse rather than write the wrong prefix.
    make_network(org, 2901, "AS-FOO")
    (tmp_path / "ripe.db.as-set.gz").write_bytes(gzip.compress(SAMPLE_DUMP.encode()))

    with pytest.raises(CommandError, match="not fit to write from"):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )


@pytest.mark.django_db
def test_cleanup_commit_checks_dump_health_before_building_the_index(org, tmp_path):
    # load_index expands every dump (~19s / 700MB on the real set), so an unhealthy
    # dump set has to be rejected before that cost is paid, not after.
    make_network(org, 2904, "AS-FOO")
    (tmp_path / "ripe.db.as-set.gz").write_bytes(gzip.compress(SAMPLE_DUMP.encode()))

    with mock.patch.object(irr_bulk, "load_index") as load_index:
        with pytest.raises(CommandError, match="not fit to write from"):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=StringIO(),
            )

    load_index.assert_not_called()


@pytest.mark.django_db
def test_cleanup_commit_allows_stale_index_with_override(org, tmp_path):
    net = make_network(org, 2902, "AS-FOO")
    (tmp_path / "ripe.db.as-set.gz").write_bytes(gzip.compress(SAMPLE_DUMP.encode()))

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE"], True)}),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--allow-stale-index",
            "--dump-dir",
            str(tmp_path),
            stdout=out,
        )

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO"
    assert "WARNING: proceeding with an unhealthy dump set" in out.getvalue()


@override_settings(IRR_BULK_DUMP_MAX_AGE_HOURS=0)
@pytest.mark.django_db
def test_cleanup_commit_refuses_out_of_date_dump_set(org, tmp_path):
    make_network(org, 2903, "AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with pytest.raises(CommandError, match="older than IRR_BULK_DUMP_MAX_AGE_HOURS"):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )


def test_dump_health_reports_complete_set(tmp_path):
    assert irr_bulk.dump_health(str(tmp_path)) == (
        [spec["name"] for spec in irr_bulk.DUMP_SOURCES],
        [],
    )
    for spec in irr_bulk.DUMP_SOURCES:
        for filename, _url in spec["files"]:
            (tmp_path / filename).write_bytes(gzip.compress(SAMPLE_DUMP.encode()))
    assert irr_bulk.dump_health(str(tmp_path)) == ([], [])


def test_load_index_ignores_staging_leftovers(tmp_path):
    # a fetch killed mid-download leaves a truncated gzip staged; it must not be
    # picked up as a dump (build_index would die on BadGzipFile / EOFError)
    (tmp_path / "sample.db").write_text(SAMPLE_DUMP)
    staging = tmp_path / ".staging"
    staging.mkdir()
    (staging / "radb.db.gz.partial.gz").write_bytes(b"\x1f\x8b truncated garbage")
    (tmp_path / ".ripe.serial").write_text("42\n")

    index = irr_bulk.load_index(str(tmp_path))
    assert irr_bulk.sources_for_bulk("AS-FOO", index) == frozenset({"RIPE"})


# --- auto-prefix safety ------------------------------------------------------


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_contradicted_rewrite_is_routed_to_outreach(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # The index says AS-FOO is RIPE-only, but the live pool holds it in RIPE *and*
    # RADB -- i.e. the index is missing RADB's dump and the name is really
    # ambiguous. Writing RIPE::AS-FOO would be wrong, and dropping the row silently
    # would leave it with neither a fix nor an email, so it becomes outreach.
    net = make_network(org, 3101, "AS-FOO")
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    out = StringIO()
    mail.outbox = []
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE", "RADB"], True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                stdout=out,
            )
    output = out.getvalue()

    net.refresh_from_db()
    assert net.irr_as_set == "AS-FOO"  # not rewritten
    assert "[unconfirmed:ambiguous]" in output
    assert "1 candidate(s) contradicted by the live IRR pool" in output
    # ...and it was actually mailed, rather than dropping out of the campaign
    assert net.irr_as_set_notified is not None
    assert net.irr_as_set_auto_prefix_candidate == "RIPE::AS-FOO"
    assert net.irr_as_set_auto_prefix_checked is not None
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_cleanup_pool_outage_is_retried_not_mailed(org, tmp_path):
    # A pool that cannot answer has told us nothing: the row must be neither
    # rewritten nor mailed, so the next run can decide it properly.
    net = make_network(org, 3105, "AS-FOO")
    add_contact(net)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult([], False)}),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=out,
        )

    net.refresh_from_db()
    assert net.irr_as_set == "AS-FOO"
    assert net.irr_as_set_notified is None
    assert net.irr_as_set_auto_prefix_candidate == ""
    assert net.irr_as_set_auto_prefix_checked is None
    assert mail.outbox == []
    assert "could not answer" in out.getvalue()


@pytest.mark.django_db
def test_cleanup_max_changes_bounds_confirmation_attempts(org, tmp_path):
    # --max-changes must bound the live lookups, not only the writes. Every one of
    # these candidates is contradicted, so a cap counting successes alone would
    # never fill and the run would query the pool once per candidate -- the
    # unbounded-fan-out shape the cap exists to prevent, reached from the other
    # side.
    for asn in range(3201, 3207):
        make_network(org, asn, f"AS-MANY{asn}")
    dump = (
        SAMPLE_DUMP
        + "\n\n"
        + "\n\n".join(
            f"as-set: AS-MANY{asn}\nsource: RIPE" for asn in range(3201, 3207)
        )
    )
    write_irr_dump_set(tmp_path, dump)

    calls = []

    def _sources_for(name, object_class=None):
        calls.append(name.upper())
        return LookupResult(["RIPE", "RADB"], True)  # always contradicts

    out = StringIO()
    with mock.patch("peeringdb_server.irr.sources_for", side_effect=_sources_for):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--max-changes",
            "2",
            # positive because --commit refuses 0; cannot skew `calls` -- these
            # networks have no contacts, so outreach skips them before any lookup
            "--max-notifications",
            "1",
            stdout=out,
        )

    # 6 candidates, cap 2, zero confirmed -> exactly 2 lookups, not 6
    assert len(calls) == 2
    assert "Auto-prefixed (--commit):    0 of 6" in out.getvalue()


@pytest.mark.django_db
def test_cleanup_contradiction_cursor_advances_without_contacts(org, tmp_path):
    # A definitive contradiction must become lookup-cursor state even when there
    # is nobody to email. Otherwise the same low-ASN row consumes the first slot on
    # every run and the valid candidate behind it is never reached.
    first = make_network(org, 3207, "AS-FOO")
    second = make_network(org, 3208, "AS-BAR")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE", "RADB"], True)}),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--max-changes",
            "1",
            stdout=StringIO(),
        )

    first.refresh_from_db()
    assert first.irr_as_set == "AS-FOO"
    assert first.irr_as_set_notified is None  # no contacts, so no mail marker
    assert first.irr_as_set_auto_prefix_candidate == "RIPE::AS-FOO"
    assert first.irr_as_set_auto_prefix_checked is not None

    calls = []

    def _sources_for(name, object_class=None):
        calls.append(name.upper())
        return LookupResult(["RADB"], True)

    out = StringIO()
    with mock.patch("peeringdb_server.irr.sources_for", side_effect=_sources_for):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--max-changes",
            "1",
            stdout=out,
        )

    second.refresh_from_db()
    assert calls == ["AS-BAR"]  # AS-FOO used no budget on the second run
    assert second.irr_as_set == "RADB::AS-BAR"
    assert (
        "1 candidate(s) skipped because the same rewrite was already" in out.getvalue()
    )
    assert "left unexamined by --max-changes" not in out.getvalue()


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_checked_contradiction_remains_pending_outreach(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # The lookup cursor and mail cursor are independent. If another outreach row
    # consumes the first run's mail cap, a newly contradicted candidate must still
    # be mailed later without spending another live lookup.
    backlog = make_network(org, 3212, "AS-MULTI")
    contradicted = make_network(org, 3213, "AS-FOO")
    add_contact(backlog, email="backlog@example.com")
    add_contact(contradicted, email="contradicted@example.com")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP + MULTI_DUMP)

    mail.outbox = []
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE", "RADB"], True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                "--max-notifications",
                "1",
                stdout=StringIO(),
            )

    contradicted.refresh_from_db()
    assert [address for message in mail.outbox for address in message.to] == [
        "backlog@example.com"
    ]
    assert contradicted.irr_as_set_notified is None
    assert contradicted.irr_as_set_auto_prefix_candidate == "RIPE::AS-FOO"

    with mock.patch("peeringdb_server.irr.sources_for") as sources_for:
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                "--commit",
                "--dump-dir",
                str(tmp_path),
                "--max-notifications",
                "1",
                stdout=StringIO(),
            )

    contradicted.refresh_from_db()
    sources_for.assert_not_called()
    assert [address for message in mail.outbox for address in message.to] == [
        "backlog@example.com",
        "contradicted@example.com",
    ]
    assert contradicted.irr_as_set_notified is not None


@pytest.mark.django_db
def test_cleanup_changed_dump_candidate_reopens_contradiction_cursor(org, tmp_path):
    # Cursor state is keyed to the proposed rewrite, not only the bare value. If a
    # later dump derives a different source, that candidate has never been checked.
    net = make_network(org, 3209, "AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE", "RADB"], True)}),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    assert net.irr_as_set_auto_prefix_candidate == "RIPE::AS-FOO"

    write_irr_dump_set(tmp_path, "as-set: AS-FOO\nsource: RADB\n")
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RADB"], True)}),
    ) as sources_for:
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    sources_for.assert_called_once_with("AS-FOO")
    assert net.irr_as_set == "RADB::AS-FOO"


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_prior_found_in_many_outreach_does_not_block_auto_prefix(
    org, tmp_path, django_capture_on_commit_callbacks
):
    # The mail marker cannot double as the lookup cursor. This row was previously
    # mailed because dumps found it in many registries, not because a proposed
    # auto-prefix was live-contradicted.
    net = make_network(org, 3210, "AS-MULTI")
    add_contact(net)
    write_irr_dump_set(tmp_path, MULTI_DUMP)

    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    assert net.irr_as_set_notified is not None
    assert net.irr_as_set_auto_prefix_candidate == ""
    assert net.irr_as_set_auto_prefix_checked is None

    write_irr_dump_set(tmp_path, "as-set: AS-MULTI\nsource: RIPE\n")
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-MULTI": LookupResult(["RIPE"], True)}),
    ) as sources_for:
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    sources_for.assert_called_once_with("AS-MULTI")
    assert net.irr_as_set == "RIPE::AS-MULTI"


@pytest.mark.django_db
def test_cleanup_renotify_after_days_reopens_contradiction_cursor(org, tmp_path):
    net = make_network(org, 3211, "AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    checked_at = timezone.now() - timedelta(days=10)
    Network.objects.filter(id=net.id).update(
        irr_as_set_auto_prefix_candidate="RIPE::AS-FOO",
        irr_as_set_auto_prefix_checked=checked_at,
        updated=checked_at - timedelta(days=1),
    )

    with mock.patch("peeringdb_server.irr.sources_for") as sources_for:
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--renotify-after-days",
            "30",
            stdout=StringIO(),
        )
    sources_for.assert_not_called()

    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE"], True)}),
    ) as sources_for:
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--renotify-after-days",
            "5",
            stdout=StringIO(),
        )

    net.refresh_from_db()
    sources_for.assert_called_once_with("AS-FOO")
    assert net.irr_as_set == "RIPE::AS-FOO"


@pytest.mark.django_db
def test_cleanup_summary_does_not_blame_the_cap_for_unconfirmed_rows(org, tmp_path):
    # A candidate the pool contradicted is not one the cap deferred: reporting it
    # as "re-run to continue" promises progress that will never come.
    make_network(org, 3211, "AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE", "RADB"], True)}),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            "--max-changes",
            "100",
            stdout=out,
        )
    output = out.getvalue()

    assert "contradicted by the live IRR pool" in output
    assert "left unexamined by --max-changes" not in output


@pytest.mark.django_db
def test_cleanup_skips_rewrite_that_would_overflow_max_length(org, tmp_path):
    # Prefixing only ever lengthens the value, so a row near the 255-char limit
    # can overflow. One such row must not abort every other write (and all
    # outreach) from inside the shared transaction.
    long_names = " ".join(f"AS-LONG{index:03d}" for index in range(23))
    assert len(long_names) <= 255
    dump = "\n\n".join(f"as-set: {name}\nsource: RIPE" for name in long_names.split())
    overflow = make_network(org, 3103, long_names)
    fine = make_network(org, 3104, "AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP + "\n\n" + dump)

    out = StringIO()
    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({}, default=LookupResult(["RIPE"], True)),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=out,
        )

    overflow.refresh_from_db()
    fine.refresh_from_db()
    assert overflow.irr_as_set == long_names  # skipped, not written
    assert "max_length" in out.getvalue()
    assert fine.irr_as_set == "RIPE::AS-FOO"  # the rest of the run still applied


@pytest.mark.django_db
def test_cleanup_commit_creates_reversion_version(org, tmp_path):
    # version history is required on the rewrite, so assert a Version exists.
    net = make_network(org, 3105, "AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.irr.sources_for",
        side_effect=live_pool({"AS-FOO": LookupResult(["RIPE"], True)}),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO"
    versions = Version.objects.get_for_object(net)
    assert versions.count() >= 1
    assert "pdb_irr_as_set_cleanup auto-prefix" in versions[0].revision.comment


# --- notify-contact selection ------------------------------------------------


@pytest.mark.django_db
def test_irr_as_set_notify_contacts_filters_roles(org):
    net = make_network(org, 3201, "AS-MULTI")
    add_contact(net, role="Technical", email="tech@example.com")
    add_contact(net, role="Sales", email="sales@example.com")
    add_contact(net, role="NOC", email="noc@example.com")
    add_contact(net, role="Technical", email="")  # blank -> excluded
    NetworkContact.objects.create(
        network=net, role="Policy", email="gone@example.com", status="deleted"
    )

    assert sorted(net.irr_as_set_notify_contacts) == [
        "noc@example.com",
        "tech@example.com",
    ]


@override_settings(IRR_AS_SET_NOTIFY_ROLES=[])
@pytest.mark.django_db
def test_irr_as_set_notify_contacts_empty_roles_disables(org):
    net = make_network(org, 3202, "AS-MULTI")
    add_contact(net)
    assert net.irr_as_set_notify_contacts == []


@override_settings(IRR_AS_SET_NOTIFY_ROLES=[""])
@pytest.mark.django_db
def test_irr_as_set_notify_contacts_blank_env_disables(org):
    # an empty env var yields [""] via _set_list, which must also disable it
    net = make_network(org, 3203, "AS-MULTI")
    add_contact(net)
    assert net.irr_as_set_notify_contacts == []


@override_settings(IRR_AS_SET_NOTIFY_ROLES=[], MAIL_DEBUG=False)
@pytest.mark.django_db
def test_cleanup_no_mail_when_notify_roles_disabled(
    org, tmp_path, django_capture_on_commit_callbacks
):
    net = make_network(org, 3204, "AS-MULTI")
    add_contact(net)
    write_irr_dump_set(tmp_path, MULTI_DUMP)

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_cleanup",
            "--commit",
            "--dump-dir",
            str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    assert mail.outbox == []
    # nothing was mailed, so nothing may be marked notified either
    assert net.irr_as_set_notified is None


# --- per-token auto-prefix and its single combined mail ------------------


@override_settings(MAIL_DEBUG=False)
def test_commit_prefixes_the_unambiguous_token_of_a_mixed_value(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    #1973: auto-prefixing applies to whatever tokens are unambiguous, so a multi-set
    value does not block the prefix cleanup. Before this, one ambiguous token meant
    neither token got fixed.
    """
    net = make_network(org, 1, "AS-ONE AS-MULTI")
    add_contact(net)
    write_irr_dump_set(
        tmp_path,
        "as-set: AS-ONE\nsource: RIPE\n\n" + MULTI_DUMP,
    )

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_cleanup.irr.sources_for",
        side_effect=live_pool({"AS-ONE": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                commit=True,
                dump_dir=str(tmp_path),
                stdout=StringIO(),
            )

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-ONE AS-MULTI"


@override_settings(MAIL_DEBUG=False)
def test_partial_rewrite_sends_one_mail_that_names_what_is_left(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    The operator must not get a "no action is needed" disclosure about a value that
    still needs them, and must not get two mails about one value in one run.
    """
    net = make_network(org, 1, "AS-ONE AS-MULTI")
    add_contact(net)
    write_irr_dump_set(tmp_path, "as-set: AS-ONE\nsource: RIPE\n\n" + MULTI_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_cleanup.irr.sources_for",
        side_effect=live_pool({"AS-ONE": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                commit=True,
                dump_dir=str(tmp_path),
                stdout=StringIO(),
            )

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert "still needs you" in message.subject
    assert "No action is needed" not in message.body
    assert "still needs you" in message.body
    assert "exists in more than one IRR registry" in message.body
    # the disclosure half is still there: what changed, and from what
    assert "AS-ONE AS-MULTI" in message.body
    assert "RIPE::AS-ONE AS-MULTI" in message.body


@override_settings(MAIL_DEBUG=False)
def test_full_rewrite_still_says_no_action_needed(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """The unchanged case must not regress: a fully fixed value needs nothing."""
    add_contact(make_network(org, 1, "AS-ONE"))
    write_irr_dump_set(tmp_path, "as-set: AS-ONE\nsource: RIPE\n")
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_cleanup.irr.sources_for",
        side_effect=live_pool({"AS-ONE": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_cleanup",
                commit=True,
                dump_dir=str(tmp_path),
                stdout=StringIO(),
            )

    assert len(mail.outbox) == 1
    assert "No action is needed" in mail.outbox[0].body
    assert "still needs you" not in mail.outbox[0].subject


def test_partial_rewrite_leaves_the_outreach_cursor_unset(org, tmp_path):
    """
    irr_as_set_notified must stay unset so a later run can still do full outreach if
    the operator never finishes the value — the disclosure is not the campaign mail.
    """
    net = make_network(org, 1, "AS-ONE AS-MULTI")
    add_contact(net)
    write_irr_dump_set(tmp_path, "as-set: AS-ONE\nsource: RIPE\n\n" + MULTI_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_cleanup.irr.sources_for",
        side_effect=live_pool({"AS-ONE": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        call_command(
            "pdb_irr_as_set_cleanup",
            commit=True,
            dump_dir=str(tmp_path),
            stdout=StringIO(),
        )

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-ONE AS-MULTI"
    assert net.irr_as_set_notified is None
