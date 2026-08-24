"""
Tests for pdb_irr_as_set_status (#1973), the periodic re-verification of
already-correct irr_as_set values.

The load-bearing behaviours here are the ones that decide whether an operator gets
told their as-set is gone:

  - a dump miss alone never produces a finding; the live pool is what makes a claim
  - `unknown` (pool could not answer) is a no-op, not evidence
  - `moved` and `gone` are separate outcomes, because "your as-set does not exist"
    is the wrong thing to tell someone who merely migrated registries
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from peeringdb_server import irr_bulk
from peeringdb_server.irr import LookupResult
from peeringdb_server.management.commands.pdb_irr_as_set_status import (
    _ID_CHUNK,
    BUDGET_SPENT,
    STATUS_DEFERRED,
    STATUS_GONE,
    STATUS_MOVED,
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_UNKNOWN,
    Command,
    _id_chunks,
    verify_network,
)
from peeringdb_server.models import Network, NetworkContact, Organization
from tests.util import write_irr_dump_set

# every test needs the DB: the autouse cleanup fixture clears the geo
# DatabaseCache, which hits the DB even for the pure-function tests.
pytestmark = pytest.mark.django_db

# AS-FOO lives in RIPE per the dump
SAMPLE_DUMP = "as-set:  AS-FOO\nsource:  RIPE\n\nas-set:  AS-BAR\nsource:  RADB\n"


@pytest.fixture(autouse=True)
def _no_live_pool():
    """
    Nothing in this module may open a real whois socket.

    The command goes live on every index miss, so a test that neither seeds the
    dump nor patches the pool would connect out to whois.radb.net — slow, and a CI
    flake that looks like a logic failure. The default here answers "pool could not
    reach anything" (the fail-open shape); tests that care patch over it.
    """
    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=unreachable_pool,
    ):
        yield


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org", status="ok")


def make_net(org, asn, irr_as_set):
    return Network.objects.create(
        name=f"Network {asn}", asn=asn, irr_as_set=irr_as_set, status="ok", org=org
    )


def pool(sources_by_name, default=LookupResult(frozenset(), True)):
    """A `resolve` callable driven by the queried name."""

    def _resolve(name):
        return sources_by_name.get(name.upper(), default)

    return _resolve


def unreachable_pool(name):
    """The pool cannot answer at all — every token comes back unknown."""
    return LookupResult(frozenset(), False)


def never_called(name):  # pragma: no cover - asserted by not being called
    raise AssertionError(f"the live pool must not be queried for {name}")


# --- verify_network: the classifier ------------------------------------------


def test_index_hit_verifies_without_a_lookup():
    """
    The whole point of resolving against the dump first: a token the index already
    holds in its pinned source costs no live query. With ~18.5k networks swept per
    run, going live for every token is not an option.
    """
    index = {"AS-FOO": {"RIPE"}}
    result = verify_network("RIPE::AS-FOO", index, never_called)
    assert result.status == STATUS_OK
    assert result.lookups == 0


def test_index_miss_is_confirmed_live_and_not_flagged_on_its_own():
    """
    The hard rule. A dump up to IRR_BULK_DUMP_MAX_AGE_HOURS old, or one registry
    that silently stopped refreshing, would otherwise become mail telling operators
    their working as-set is dead.
    """
    index = {}  # the dump knows nothing about this name
    result = verify_network(
        "RIPE::AS-FOO", index, pool({"AS-FOO": LookupResult(frozenset({"RIPE"}), True)})
    )
    assert result.status == STATUS_OK
    assert result.lookups == 1


def test_index_holding_only_another_source_still_goes_live():
    """
    An index that lists the name in RADB but not RIPE is not evidence the RIPE
    object is gone — it is equally consistent with the RIPE dump being stale. Only
    the pool decides.
    """
    index = {"AS-FOO": {"RADB"}}
    result = verify_network(
        "RIPE::AS-FOO", index, pool({"AS-FOO": LookupResult(frozenset({"RIPE"}), True)})
    )
    assert result.status == STATUS_OK
    assert result.lookups == 1


def test_moved_reports_where_the_object_actually_is():
    """
    The benign common case: an operator migrated the object and updated PeeringDB
    late. The mail has to be able to say "we found it in RIPE", which means the
    classification has to carry the sources, not just the verdict.
    """
    result = verify_network(
        "RADB::AS-FOO", {}, pool({"AS-FOO": LookupResult(frozenset({"RIPE"}), True)})
    )
    assert result.status == STATUS_MOVED
    assert result.moved_to == ["RIPE"]
    assert "RADB::AS-FOO now in RIPE" in result.note


def test_gone_only_when_the_pool_definitively_holds_it_nowhere():
    result = verify_network(
        "RIPE::AS-FOO", {}, pool({"AS-FOO": LookupResult(frozenset(), True)})
    )
    assert result.status == STATUS_GONE
    assert result.moved_to == []


def test_pool_outage_is_unknown_not_gone():
    """
    ok=False means the pool could not answer. Treating it as "found nowhere" would
    turn an IRR outage into a mass disappearance notice.
    """
    result = verify_network("RIPE::AS-FOO", {}, unreachable_pool)
    assert result.status == STATUS_UNKNOWN


def test_unprefixed_value_is_skipped_not_flagged():
    """
    "Does AS-FOO still exist" has no answer until the operator says in which
    registry. Those rows belong to pdb_irr_as_set_cleanup; flagging them here would
    double-mail the same operator about the same value.
    """
    result = verify_network("AS-FOO", {"AS-FOO": {"RIPE"}}, never_called)
    assert result.status == STATUS_SKIPPED
    assert result.lookups == 0


def test_partly_prefixed_value_is_not_verified():
    """
    A mixed value is worth checking for the part that can be checked, but the
    unpinned token must be ranked rather than dropped: the value is still
    non-compliant, so stamping it verified would render "Verified present" on the
    public record and count it as verified in the PC report. That shape is what the
    per-token auto-prefix produces.
    """
    result = verify_network("RIPE::AS-FOO AS-BARE", {"AS-FOO": {"RIPE"}}, never_called)
    assert result.status == STATUS_SKIPPED
    assert "AS-BARE carries no IRR source prefix" in result.note


def test_a_repeated_token_is_noted_once():
    """
    One note per distinct finding: a value naming the same unprefixed token twice
    otherwise reads "AS-BARE carries no IRR source prefix; AS-BARE carries no IRR
    source prefix" in the operator-facing --detail log.
    """
    result = verify_network(
        "RIPE::AS-FOO AS-BARE AS-BARE", {"AS-FOO": {"RIPE"}}, never_called
    )
    assert result.note == "AS-BARE carries no IRR source prefix"


def test_a_repeated_token_is_looked_up_once():
    """
    Deduping the tokens, not just their notes: the resolve closure charges
    --max-lookups per call, so sources_for's own cache does not give it back.
    """
    result = verify_network(
        "RADB::AS-DEAD AS-BARE RADB::AS-DEAD",
        {},
        pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    )
    assert result.status == STATUS_GONE
    assert result.lookups == 1
    assert result.note == (
        "RADB::AS-DEAD in no registry; AS-BARE carries no IRR source prefix"
    )


def test_a_definitive_finding_outranks_an_unpinned_sibling():
    """
    Ranking the unpinned token must not bury a real finding: `gone` is what the
    operator needs to hear about a mixed value, not "no source prefix to check".
    """
    result = verify_network(
        "RIPE::AS-DEAD AS-BARE", {}, pool({"AS-DEAD": LookupResult(frozenset(), True)})
    )
    assert result.status == STATUS_GONE


def test_unknown_outranks_ok_so_a_value_cannot_escape_verification():
    """
    One confirmed token and one unanswerable token is not a verified value. If `ok`
    won here the row would be stamped and never looked at again — exactly what
    this command exists to prevent.
    """

    def _resolve(name):
        if name == "AS-BAR":
            return LookupResult(frozenset(), False)
        return LookupResult(frozenset({"RIPE"}), True)

    result = verify_network("RIPE::AS-FOO RADB::AS-BAR", {}, _resolve)
    assert result.status == STATUS_UNKNOWN


def test_gone_outranks_moved_and_unknown():
    """
    A definitive finding about one token is actionable whatever happened to the
    others, and `gone` is the one the operator most needs to hear.
    """

    def _resolve(name):
        return {
            "AS-GONE": LookupResult(frozenset(), True),
            "AS-MOVED": LookupResult(frozenset({"RIPE"}), True),
            "AS-DUNNO": LookupResult(frozenset(), False),
        }[name]

    result = verify_network("RIPE::AS-GONE RADB::AS-MOVED RIPE::AS-DUNNO", {}, _resolve)
    assert result.status == STATUS_GONE


def test_budget_spent_defers_without_a_finding():
    """
    A row the run never got to must keep whatever state it had — reporting it as
    `unknown` would be indistinguishable from a pool outage, and stamping anything
    would be a claim we did not check.
    """

    def _resolve(name):
        return BUDGET_SPENT

    result = verify_network("RIPE::AS-FOO", {}, _resolve)
    assert result.status == STATUS_DEFERRED
    assert result.lookups == 0


def test_no_index_resolves_everything_live():
    """
    load_index returns None when no dumps are configured. The command still works,
    it just spends budget — it must not silently treat "no index" as "not found".
    """
    result = verify_network(
        "RIPE::AS-FOO", None, pool({"AS-FOO": LookupResult(frozenset({"RIPE"}), True)})
    )
    assert result.status == STATUS_OK
    assert result.lookups == 1


def test_unknown_registry_prefix_is_not_a_pin():
    """
    A prefix naming a registry PeeringDB does not know cannot be verified against,
    so the value has no pinned token and is skipped rather than flagged.
    """
    result = verify_network("NOTAREGISTRY::AS-FOO", {}, never_called)
    assert result.status == STATUS_SKIPPED


# --- the command -------------------------------------------------------------


def run(**options):
    out = StringIO()
    call_command("pdb_irr_as_set_status", stdout=out, **options)
    return out.getvalue()


def test_dry_run_reports_and_writes_nothing(org, tmp_path):
    net_ok = make_net(org, 1, "RIPE::AS-FOO")
    net_gone = make_net(org, 2, "RIPE::AS-DEAD")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        output = run(dump_dir=str(tmp_path))

    assert "irr_as_set re-verification report" in output
    assert "dry-run" in output

    # nothing written: the state fields are P3-T3's job, and a dry run never writes
    for net in (net_ok, net_gone):
        net.refresh_from_db()
        assert net.irr_as_set_status == "unknown"
        assert net.irr_as_set_verified is None
        assert net.irr_as_set_missing_since is None


def test_sweep_counts_each_outcome(org, tmp_path):
    make_net(org, 1, "RIPE::AS-FOO")  # index hit -> verified
    make_net(org, 2, "RADB::AS-MOVED")  # pool says RIPE -> moved
    make_net(org, 3, "RIPE::AS-DEAD")  # pool says nowhere -> gone
    make_net(org, 4, "AS-BARE")  # no pin -> skipped
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool(
            {
                "AS-MOVED": LookupResult(frozenset({"RIPE"}), True),
                "AS-DEAD": LookupResult(frozenset(), True),
            }
        ),
    ):
        output = run(dump_dir=str(tmp_path), detail=True)

    assert "Networks with a value:       4" in output
    assert "verified present:          1" in output
    assert "moved to another registry: 1" in output
    assert "gone from every registry:  1" in output
    assert "no source prefix to check: 1" in output

    # --detail names the unverified rows and stays quiet about the verified one
    assert "[moved] id:" in output
    assert "[gone] id:" in output
    assert "[skipped] id:" in output
    assert "[ok] id:" not in output


def test_empty_value_networks_are_not_swept(org, tmp_path):
    make_net(org, 1, "RIPE::AS-FOO")
    make_net(org, 2, "")
    make_net(org, 3, "   ")  # whitespace-only is not a value either
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    output = run(dump_dir=str(tmp_path))
    assert "Networks with a value:       1" in output


def test_deleted_networks_are_not_swept(org, tmp_path):
    make_net(org, 1, "RIPE::AS-FOO")
    gone = make_net(org, 2, "RIPE::AS-FOO")
    Network.objects.filter(pk=gone.pk).update(status="deleted")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    output = run(dump_dir=str(tmp_path))
    assert "Networks with a value:       1" in output


def test_max_lookups_bounds_the_live_fan_out(org, tmp_path):
    """
    The first sweep over ~18.5k networks could send every token to the pool if the
    dumps are incomplete. The budget bounds that, and the rows behind it are
    reported as deferred rather than silently dropped.
    """
    for asn in range(1, 6):
        make_net(org, asn, f"RIPE::AS-MISS{asn}")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    sources_for = mock.Mock(return_value=LookupResult(frozenset({"RIPE"}), True))
    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        sources_for,
    ):
        output = run(dump_dir=str(tmp_path), max_lookups=2)

    assert sources_for.call_count == 2
    assert "Live pool queries:           2" in output
    assert "deferred by --max-lookups: 3" in output
    assert "lookup budget reached" in output


def test_max_lookups_zero_uncaps_a_dry_run(org, tmp_path):
    """
    0 is a reporting affordance: a read-only run the operator deliberately let off
    the leash. It is refused under --commit — see the test below.
    """
    for asn in range(1, 4):
        make_net(org, asn, f"RIPE::AS-MISS{asn}")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    sources_for = mock.Mock(return_value=LookupResult(frozenset({"RIPE"}), True))
    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        sources_for,
    ):
        output = run(dump_dir=str(tmp_path), max_lookups=0)

    assert sources_for.call_count == 3
    assert "deferred by --max-lookups: 0" in output


def test_commit_refuses_zero_max_lookups(org, tmp_path):
    """
    Same call pdb_irr_as_set_cleanup makes for --max-changes: at ~3.4s per pool
    query an uncapped sweep is many hours, and since the state writes land after the
    loop a killed run commits nothing and repeats forever.
    """
    make_net(org, 1, "RIPE::AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    with pytest.raises(CommandError) as excinfo:
        run(commit=True, dump_dir=str(tmp_path), max_lookups=0)
    assert "uncaps the live pool queries" in str(excinfo.value)


def test_negative_max_lookups_is_rejected():
    with pytest.raises(CommandError):
        run(max_lookups=-1)


def test_commit_refuses_an_unhealthy_dump_set(org, tmp_path):
    """
    Same guard shape as the cleanup command, for a different reason: an unhealthy
    index here does not write a wrong value, it makes every token pinned to the
    missing registry a live lookup and starves the rest of the sweep.
    """
    make_net(org, 1, "RIPE::AS-FOO")
    with pytest.raises(CommandError) as excinfo:
        run(commit=True, dump_dir=str(tmp_path))
    assert "not fit to resolve from" in str(excinfo.value)


def test_allow_stale_index_overrides_the_guard_with_a_warning(org, tmp_path):
    make_net(org, 1, "RIPE::AS-FOO")
    output = run(commit=True, dump_dir=str(tmp_path), allow_stale_index=True)
    assert "WARNING: proceeding with an unhealthy dump set" in output


def test_missing_index_is_reported_not_silently_treated_as_absent(org, tmp_path):
    """
    With no dumps at all, load_index returns None. Every token then goes live, and
    the report has to say so — otherwise a run whose budget cut the sweep short
    reads as a clean bill of health.
    """
    make_net(org, 1, "RIPE::AS-FOO")

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-FOO": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        output = run(dump_dir=str(tmp_path))

    assert "No bulk IRR dump index" in output
    assert "verified present:          1" in output


# --- --commit: state transitions and notifications ---------------------------


def make_net_with_contact(org, asn, irr_as_set, role="Technical"):
    net = make_net(org, asn, irr_as_set)
    NetworkContact.objects.create(
        network=net, role=role, email=f"as{asn}@example.com", status="ok"
    )
    return net


@override_settings(MAIL_DEBUG=False)
def test_commit_stamps_verified_and_clears_missing_since(org, tmp_path):
    """
    Recovery: a value that was flagged and is now present again must have its
    missing_since cleared, or the PC histogram keeps counting it and a re-broken
    value would inherit the old clock instead of starting a fresh one.
    """
    net = make_net_with_contact(org, 1, "RIPE::AS-FOO")
    was_missing = timezone.now() - timedelta(days=10)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status="gone", irr_as_set_missing_since=was_missing
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_OK
    assert net.irr_as_set_verified is not None
    assert net.irr_as_set_missing_since is None


@override_settings(MAIL_DEBUG=False)
def test_recovery_clears_the_notify_cursor(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    A value that recovers and then breaks again inside --renotify-after-days must
    still be mailed about the second disappearance. Left set, the cursor from the
    first notice suppresses it until the reminder falls due, so recovery clears it
    -- the same thing pdb_rir_status does with rir_status_notified.
    """
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    first_notice = timezone.now() - timedelta(days=5)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status=STATUS_GONE,
        irr_as_set_missing_since=first_notice,
        irr_as_set_verify_notified=first_notice,
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    # run 1: the pool now holds it in RIPE again -> recovered
    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_OK
    assert net.irr_as_set_verify_notified is None

    # run 2, still inside the 30-day cadence: it is gone again, so tell them
    mail.outbox = []
    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            run(commit=True, dump_dir=str(tmp_path), renotify_after_days=30)

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE
    assert net.irr_as_set_verify_notified is not None
    assert len(mail.outbox) == 1
    # a fresh clock, not the one the first disappearance started
    assert net.irr_as_set_missing_since > first_notice


@override_settings(MAIL_DEBUG=False)
def test_commit_flags_and_mails_a_gone_value(
    org, tmp_path, django_capture_on_commit_callbacks
):
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            output = run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE
    assert net.irr_as_set_missing_since is not None
    assert net.irr_as_set_verify_notified is not None
    assert net.irr_as_set_verified is None

    assert len(mail.outbox) == 1
    assert "no longer exists" in mail.outbox[0].subject.lower()
    assert "Notified (--commit):         1 of 1" in output


@override_settings(MAIL_DEBUG=False)
def test_commit_mails_moved_with_the_registries_that_hold_it(
    org, tmp_path, django_capture_on_commit_callbacks
):
    net = make_net_with_contact(org, 1, "RADB::AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-FOO": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_MOVED
    assert len(mail.outbox) == 1
    assert "We did find it in: RIPE" in mail.outbox[0].body


@override_settings(MAIL_DEBUG=False)
def test_commit_does_not_mail_or_restamp_on_a_pool_outage(org, tmp_path):
    """
    `unknown` is the one outcome that must be inert. The pool being unreachable is
    not news, and if it stamped or cleared anything an IRR outage would erase the
    missing_since clocks of every already-flagged network.

    Inert includes the status column: a row already flagged `gone` keeps that
    verdict through the outage rather than being reset to `unknown`, so the record
    page and the missing-days histogram do not lose the flagged population for the
    duration.
    """
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    was_missing = timezone.now() - timedelta(days=10)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status="gone", irr_as_set_missing_since=was_missing
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=unreachable_pool,
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE
    assert net.irr_as_set_missing_since == was_missing
    assert net.irr_as_set_verified is None
    assert mail.outbox == []


@override_settings(MAIL_DEBUG=False)
def test_missing_since_is_not_restamped_while_still_missing(org, tmp_path):
    """
    missing_since answers "since when", which is what the histogram and any future
    escalation read. Re-stamping it every run would peg every gone value at
    zero days forever.
    """
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    original = timezone.now() - timedelta(days=45)
    Network.objects.filter(pk=net.pk).update(irr_as_set_missing_since=original)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_missing_since == original


@override_settings(MAIL_DEBUG=False)
def test_verify_cursor_is_separate_from_the_cleanup_campaign_cursor(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    The reason for a fourth field: if this command shared irr_as_set_notified, a
    cleanup campaign mail would suppress a disappearance notice, and vice versa.
    """
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    campaign_mail = timezone.now()
    Network.objects.filter(pk=net.pk).update(irr_as_set_notified=campaign_mail)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    # told anyway, and the campaign's own cursor is left alone
    assert len(mail.outbox) == 1
    assert net.irr_as_set_verify_notified is not None
    assert net.irr_as_set_notified == campaign_mail


@override_settings(MAIL_DEBUG=False)
def test_already_notified_is_not_remailed_without_a_due_reminder(org, tmp_path):
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_verify_notified=timezone.now() - timedelta(days=5)
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path), renotify_after_days=30)

    assert mail.outbox == []


@override_settings(MAIL_DEBUG=False)
def test_reminder_is_sent_once_the_cadence_has_passed(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """The spec asks for reminders on a cadence, not a single notice."""
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_verify_notified=timezone.now() - timedelta(days=40)
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            run(commit=True, dump_dir=str(tmp_path), renotify_after_days=30)

    assert len(mail.outbox) == 1


@override_settings(MAIL_DEBUG=False)
def test_renotify_zero_never_reminds(org, tmp_path):
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_verify_notified=timezone.now() - timedelta(days=4000)
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path), renotify_after_days=0)

    assert mail.outbox == []


@override_settings(MAIL_DEBUG=False)
def test_max_notifications_is_a_cursor_not_a_truncation(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    The rows beyond the cap must keep irr_as_set_verify_notified unset so the next
    run picks them up, instead of the run re-mailing the same first N forever.
    """
    for asn in range(1, 4):
        make_net_with_contact(org, asn, "RIPE::AS-DEAD")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            output = run(commit=True, dump_dir=str(tmp_path), max_notifications=2)

    assert len(mail.outbox) == 2
    assert Network.objects.filter(irr_as_set_verify_notified__isnull=True).count() == 1
    assert "notification cap reached" in output
    # every row is still flagged, cap or not -- the cap bounds mail, not state
    assert Network.objects.filter(irr_as_set_status=STATUS_GONE).count() == 3


def test_commit_refuses_zero_max_notifications(org, tmp_path):
    make_net(org, 1, "RIPE::AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    with pytest.raises(CommandError) as excinfo:
        run(commit=True, dump_dir=str(tmp_path), max_notifications=0)
    assert "uncaps the moved/gone mail" in str(excinfo.value)


def test_negative_notification_options_are_rejected():
    with pytest.raises(CommandError):
        run(max_notifications=-1)
    with pytest.raises(CommandError):
        run(renotify_after_days=-1)


@override_settings(MAIL_DEBUG=False)
def test_no_contacts_still_flags_the_network(org, tmp_path):
    """
    Unreachability is not a reason to stop recording what we found: the PC report
    and the website record are the other two consumers of this state.
    """
    net = make_net(org, 1, "RIPE::AS-DEAD")  # no contact
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE
    assert net.irr_as_set_missing_since is not None
    assert net.irr_as_set_verify_notified is None
    assert mail.outbox == []


@override_settings(MAIL_DEBUG=False)
def test_value_changed_during_the_run_is_not_mailed(org, tmp_path):
    """
    Telling an operator their as-set is gone moments after they replaced it is the
    one stale-read consequence a later run cannot take back, so the mail path
    re-reads before sending.
    """
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    def _sources_for(name, object_class=None):
        # the operator fixes the value while the run is mid-sweep
        Network.objects.filter(pk=net.pk).update(irr_as_set="RIPE::AS-FOO")
        return LookupResult(frozenset(), True)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=_sources_for,
    ):
        output = run(commit=True, dump_dir=str(tmp_path))

    assert mail.outbox == []
    assert "[skip:superseded]" in output


@override_settings(MAIL_DEBUG=False)
def test_state_writes_do_not_touch_the_operator_value_or_bump_updated(org, tmp_path):
    """
    bulk_update over the internal columns only: a full save() would write the
    stale in-memory row over a concurrent edit -- the MR 855 lost-update fix -- and
    would bump `updated` and cut a reversion version for an internal marker.
    """
    net = make_net_with_contact(org, 1, "RIPE::AS-FOO")
    before = Network.objects.filter(pk=net.pk).values_list("updated", flat=True)[0]
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO"
    assert net.updated == before
    assert net.irr_as_set_status == STATUS_OK


@override_settings(MAIL_DEBUG=False)
def test_deferred_rows_keep_their_existing_state(org, tmp_path):
    """
    A row the lookup budget never reached must not be restamped: `deferred` is a
    fact about the run, not about the value.
    """
    net_a = make_net_with_contact(org, 1, "RIPE::AS-MISS1")
    net_b = make_net_with_contact(org, 2, "RIPE::AS-MISS2")
    stamped = timezone.now() - timedelta(days=3)
    Network.objects.filter(pk=net_b.pk).update(
        irr_as_set_status=STATUS_OK, irr_as_set_verified=stamped
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({}, default=LookupResult(frozenset(), True)),
    ):
        run(commit=True, dump_dir=str(tmp_path), max_lookups=1)

    net_a.refresh_from_db()
    net_b.refresh_from_db()
    assert net_a.irr_as_set_status == STATUS_GONE  # the one lookup was spent here
    assert net_b.irr_as_set_status == STATUS_OK  # untouched
    assert net_b.irr_as_set_verified == stamped


@override_settings(MAIL_DEBUG=False)
def test_skipped_retracts_a_standing_flag(org, tmp_path):
    """
    A verdict must not outlive the value it was about. Once a row reports `skipped`
    the run has looked at every token and found none of them verifiable, so a
    `gone` left over from the value the operator has since replaced would keep the
    record rendering "no longer exists" and keep the PC histogram counting the row
    toward the over-90-days bucket forever.
    """
    net = make_net_with_contact(org, 1, "RIPE::AS-FOO AS-BARE")
    flagged = timezone.now() - timedelta(days=120)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status=STATUS_GONE,
        irr_as_set_missing_since=flagged,
        irr_as_set_verify_notified=flagged,
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    output = run(commit=True, dump_dir=str(tmp_path), detail=True)

    net.refresh_from_db()
    assert "[skipped] id:" in output
    assert net.irr_as_set_status == STATUS_UNKNOWN
    assert net.irr_as_set_missing_since is None
    assert net.irr_as_set_verify_notified is None
    # and it drops out of the report it was inflating
    assert sum(count for _label, count in Command().missing_histogram()) == 0


@override_settings(MAIL_DEBUG=False)
def test_skipped_retracts_a_stale_verified_stamp(org, tmp_path):
    """
    The same property in the other direction: a value that was verified and has
    since been edited to something with no verifiable token must stop claiming
    "Verified present" on the public record. The verified date goes with the status
    -- with the status row empty it would stand alone as "IRR AS-SET Verified:
    <date>" about a value that was never verified.
    """
    net = make_net_with_contact(org, 1, "AS-BARE")
    stamped = timezone.now() - timedelta(days=3)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status=STATUS_OK, irr_as_set_verified=stamped
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_UNKNOWN
    assert net.irr_as_set_verified is None


@override_settings(MAIL_DEBUG=False)
@pytest.mark.parametrize("cleared", ["", "   "])
def test_a_cleared_value_retracts_a_standing_flag(org, tmp_path, cleared):
    """
    Emptying the field is how some operators comply with the gone mail, and the sweep
    never visits those rows -- "" is excluded by the queryset, whitespace-only by the
    loop. Unless the retraction reaches them from outside the per-row path the record
    renders "no longer exists" for a network publishing no as-set at all, and the
    histogram the PC decision reads keeps counting it, forever: nothing else clears
    these columns.
    """
    net = make_net_with_contact(org, 1, cleared)
    flagged = timezone.now() - timedelta(days=120)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status=STATUS_GONE,
        irr_as_set_verified=flagged,
        irr_as_set_missing_since=flagged,
        irr_as_set_verify_notified=flagged,
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    run(dump_dir=str(tmp_path))
    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE  # a dry run retracts nothing either

    output = run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_UNKNOWN
    assert net.irr_as_set_verified is None
    assert net.irr_as_set_missing_since is None
    assert net.irr_as_set_verify_notified is None
    # retracted from outside the sweep: the row is still counted nowhere
    assert "Networks with a value:       0" in output
    assert sum(count for _label, count in Command().missing_histogram()) == 0


@override_settings(MAIL_DEBUG=False)
def test_a_cleared_value_retracts_a_lone_verified_stamp(org, tmp_path):
    """
    The row the retraction filter is easiest to get wrong on: status already
    `unknown`, both clocks null, only the verified stamp left standing. It is reached
    by a verified value whose next sweep hit a pool outage -- `unknown` writes status
    only, so the stamp survives -- and is then emptied by the operator. A filter that
    does not also require the stamp to be null reads that row as "nothing to
    retract", so /net/<id> keeps "IRR AS-SET Verified: <date>" as its only statement
    about a value the network no longer holds, and no later run revisits it.
    """
    net = make_net_with_contact(org, 1, "")
    stamped = timezone.now() - timedelta(days=120)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status=STATUS_UNKNOWN, irr_as_set_verified=stamped
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_verified is None
    assert net.irr_as_set_status == STATUS_UNKNOWN


@override_settings(MAIL_DEBUG=False)
def test_a_cleared_value_on_a_deleted_network_is_left_alone(org, tmp_path):
    """
    The retraction is scoped to status=ok like the sweep it stands in for: a deleted
    network is not one this command reports on or reasons about.
    """
    net = make_net_with_contact(org, 1, "")
    flagged = timezone.now() - timedelta(days=120)
    Network.objects.filter(pk=net.pk).update(
        status="deleted",
        irr_as_set_status=STATUS_GONE,
        irr_as_set_missing_since=flagged,
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE
    assert net.irr_as_set_missing_since == flagged


@override_settings(MAIL_DEBUG=True)
def test_mail_debug_suppresses_the_send_but_not_the_state(org, tmp_path):
    net = make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)
    mail.outbox = []

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert mail.outbox == []
    assert net.irr_as_set_status == STATUS_GONE


@override_settings(MAIL_DEBUG=False)
def test_a_failing_send_does_not_lose_the_state_or_the_other_sends(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """
    The sends happen on_commit, after the state is durable. One raising send is
    logged and skipped so it cannot roll back the run or silence the rest.
    """
    make_net_with_contact(org, 1, "RIPE::AS-DEAD")
    make_net_with_contact(org, 2, "RIPE::AS-DEAD")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    calls = []

    def _mail(net, recipients, reason, **kwargs):
        calls.append(net.asn)
        if net.asn == 1:
            raise RuntimeError("smtp is down")

    with (
        mock.patch(
            "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
            side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
        ),
        mock.patch(
            "peeringdb_server.management.commands.pdb_irr_as_set_status."
            "mail_network_irr_as_set_flagged",
            side_effect=_mail,
        ),
        django_capture_on_commit_callbacks(execute=True),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    assert calls == [1, 2]
    assert Network.objects.filter(irr_as_set_status=STATUS_GONE).count() == 2


# --- the PC aggregate report -------------------------------------------------


def flag_net(org, asn, missing_days, status=STATUS_GONE):
    """A network already flagged, missing since `missing_days` ago."""
    net = make_net(org, asn, "RIPE::AS-DEAD")
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status=status,
        irr_as_set_missing_since=timezone.now() - timedelta(days=missing_days),
    )
    return net


def test_report_histogram_buckets_by_age(org, tmp_path):
    flag_net(org, 1, 2)  # under 7
    flag_net(org, 2, 6)  # under 7
    flag_net(org, 3, 20)  # 7 to 30
    flag_net(org, 4, 60, status=STATUS_MOVED)  # 30 to 90, moved counts too
    flag_net(org, 5, 400)  # over 90

    command = Command()
    histogram = dict(command.missing_histogram())

    assert histogram["under 7 days"] == 2
    assert histogram["7 to 30 days"] == 1
    assert histogram["30 to 90 days"] == 1
    assert histogram["over 90 days"] == 1


def test_report_histogram_buckets_are_disjoint(org, tmp_path):
    """
    Half-open ranges: a row exactly on a boundary lands in one bucket, and the
    bucket totals must equal the flagged population — a double-counted row would
    make the PC's "how bad is it" number wrong in the alarming direction.
    """
    for asn, days in enumerate([7, 30, 90], start=1):
        flag_net(org, asn, days)

    command = Command()
    histogram = command.missing_histogram()
    assert sum(count for _label, count in histogram) == 3


def test_report_histogram_excludes_recovered_and_unflagged(org, tmp_path):
    """
    Only currently-flagged rows count. A recovered value has missing_since cleared,
    and an `unknown` row is not a finding, so neither may inflate the number.
    """
    flag_net(org, 1, 10)
    make_net(org, 2, "RIPE::AS-FOO")  # never flagged
    recovered = make_net(org, 3, "RIPE::AS-FOO")
    Network.objects.filter(pk=recovered.pk).update(
        irr_as_set_status=STATUS_OK, irr_as_set_missing_since=None
    )
    unknown = make_net(org, 4, "RIPE::AS-FOO")
    Network.objects.filter(pk=unknown.pk).update(irr_as_set_status=STATUS_UNKNOWN)

    command = Command()
    assert sum(count for _label, count in command.missing_histogram()) == 1


def test_report_histogram_excludes_deleted_networks(org, tmp_path):
    flag_net(org, 1, 10)
    gone = flag_net(org, 2, 10)
    Network.objects.filter(pk=gone.pk).update(status="deleted")

    command = Command()
    assert sum(count for _label, count in command.missing_histogram()) == 1


def test_report_histogram_counts_rows_this_run_never_resolved(org, tmp_path):
    """
    The histogram is read from the database, not accumulated during the sweep, so a
    run whose lookup budget deferred every row still reports the standing backlog.
    Counting only this run's findings would make a budget-limited run read as an
    improvement.
    """
    flag_net(org, 1, 100)
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    output = run(dump_dir=str(tmp_path), max_lookups=0)

    assert "deferred by --max-lookups: 0" in output
    assert "over 90 days             1" in output


def test_report_prints_the_histogram_and_a_none_line_when_empty(org, tmp_path):
    make_net(org, 1, "RIPE::AS-FOO")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    output = run(dump_dir=str(tmp_path))

    assert "Currently flagged, by how long the value has been wrong:" in output
    assert "  none" in output


@override_settings(MAIL_DEBUG=False)
def test_report_histogram_reflects_this_run_after_commit(
    org, tmp_path, django_capture_on_commit_callbacks
):
    """End to end: a value found gone this run shows up in the youngest bucket."""
    make_net(org, 1, "RIPE::AS-DEAD")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            output = run(commit=True, dump_dir=str(tmp_path))

    assert "under 7 days             1" in output
    assert "total                    1" in output


@override_settings(MAIL_DEBUG=False)
def test_verdict_change_keeps_the_original_clock(org, tmp_path):
    """
    moved -> gone is a new verdict about a value that has been wrong the whole time,
    so the clock must not restart. Covers the branch that updates the status while
    leaving a non-NULL missing_since alone.
    """
    net = make_net(org, 1, "RIPE::AS-DEAD")
    original = timezone.now() - timedelta(days=60)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status=STATUS_MOVED, irr_as_set_missing_since=original
    )
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE
    assert net.irr_as_set_missing_since == original


def test_id_chunks_bounds_the_in_clause():
    """
    A first sweep can classify every network the same way, so the id lists feeding
    `id__in` are the size of the whole set. Chunking is what keeps that out of one
    query.
    """
    assert list(_id_chunks(None)) == []
    assert list(_id_chunks([])) == []
    assert list(_id_chunks([1, 2, 3], size=2)) == [[1, 2], [3]]

    ids = list(range(_ID_CHUNK * 2 + 5))
    chunks = list(_id_chunks(ids))
    assert len(chunks) == 3
    assert all(len(chunk) <= _ID_CHUNK for chunk in chunks)
    # nothing lost, nothing duplicated
    assert [i for chunk in chunks for i in chunk] == ids


def test_unknown_does_not_overwrite_a_standing_gone(org, tmp_path):
    """
    An IRR outage makes the pool ignorant, not the value good.

    Overwriting a proven `gone` with `unknown` blanks the label on the network
    record and drops the row out of the missing-days histogram -- during an
    outage, which is exactly when the flagged population is what anyone would
    want to look at. Only a definitive answer may replace a definitive answer.
    """
    net = make_net(org, 1, "RIPE::AS-DEAD")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE
    flagged_at = net.irr_as_set_missing_since
    assert flagged_at is not None

    # the pool stops answering: the run reports unknown but the verdict stands
    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-DEAD": LookupResult(frozenset(), False)}),
    ):
        output = run(commit=True, dump_dir=str(tmp_path))

    assert "pool could not answer:     1" in output
    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_GONE
    assert net.irr_as_set_missing_since == flagged_at

    # and it still counts toward the report the PC reads
    assert sum(count for _label, count in Command().missing_histogram()) == 1


def test_unknown_does_not_overwrite_a_standing_moved(org, tmp_path):
    net = make_net(org, 1, "RADB::AS-MOVED")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-MOVED": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_MOVED

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-MOVED": LookupResult(frozenset(), False)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_MOVED


def test_unknown_still_lands_on_a_row_carrying_no_verdict(org, tmp_path):
    """
    The protection is for standing moved/gone only. A row that was verified, or
    never swept, still records `unknown` -- it says "not confirmed on this run",
    which is true and is not overwriting a finding.
    """
    net = make_net(org, 1, "RIPE::AS-MISS")
    write_irr_dump_set(tmp_path, SAMPLE_DUMP)

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-MISS": LookupResult(frozenset({"RIPE"}), True)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_OK

    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_status.irr.sources_for",
        side_effect=pool({"AS-MISS": LookupResult(frozenset(), False)}),
    ):
        run(commit=True, dump_dir=str(tmp_path))

    net.refresh_from_db()
    assert net.irr_as_set_status == STATUS_UNKNOWN
