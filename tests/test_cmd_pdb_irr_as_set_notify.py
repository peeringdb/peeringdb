"""
Tests for pdb_irr_as_set_notify (#1974), the soft-window nudge that warns
networks still listing more than the single-set cap before the hard-start date.
"""

from datetime import datetime, timedelta
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from peeringdb_server.models import Network, NetworkContact, Organization

pytestmark = pytest.mark.django_db

SOFT = datetime(2000, 1, 1)  # already open
HARD_FUTURE = datetime(2999, 1, 1)  # not yet reached


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org", status="ok")


def make_net(org, asn, irr_as_set, contact=True):
    net = Network.objects.create(
        name=f"Network {asn}", asn=asn, irr_as_set=irr_as_set, status="ok", org=org
    )
    if contact:
        NetworkContact.objects.create(
            network=net, role="Technical", email=f"as{asn}@example.com", status="ok"
        )
    return net


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_warns_over_cap_networks(org, django_capture_on_commit_callbacks):
    make_net(org, 3001, "RIPE::AS-FOO RADB::AS-BAR")  # 2 sets > cap 1 -> warned
    make_net(org, 3002, "RIPE::AS-FOO")  # single set -> not warned
    make_net(org, 3003, "RIPE::AS-FOO RADB::AS-BAR", contact=False)  # no contact

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", "--commit", stdout=StringIO())

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["as3001@example.com"]
    # the hard-start deadline (2999) is cited in the nudge
    assert "2999" in mail.outbox[0].body


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=HARD_FUTURE,  # soft window not open yet
    IRR_AS_SET_CAP_HARD_START=None,
)
def test_notify_before_soft_window_noop(org, django_capture_on_commit_callbacks):
    make_net(org, 3010, "RIPE::AS-FOO RADB::AS-BAR")
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", "--commit", stdout=StringIO())
    assert mail.outbox == []


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=datetime(2000, 1, 1),
    IRR_AS_SET_CAP_HARD_START=datetime(2000, 1, 2),  # already reached
)
def test_notify_after_hard_start_noop(org, django_capture_on_commit_callbacks):
    make_net(org, 3020, "RIPE::AS-FOO RADB::AS-BAR")
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", "--commit", stdout=StringIO())
    assert mail.outbox == []


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=0,  # uncapped -> nothing to warn
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_uncapped_noop(org, django_capture_on_commit_callbacks):
    make_net(org, 3030, "RIPE::AS-FOO RADB::AS-BAR")
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", "--commit", stdout=StringIO())
    assert mail.outbox == []


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_dry_run_sends_no_mail(org, django_capture_on_commit_callbacks):
    make_net(org, 3040, "RIPE::AS-FOO RADB::AS-BAR")
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", stdout=StringIO())  # no --commit
    assert mail.outbox == []


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_respects_max_notifications(org, django_capture_on_commit_callbacks):
    make_net(org, 3051, "RIPE::AS-FOO RADB::AS-BAR")
    make_net(org, 3052, "RIPE::AS-FOO RADB::AS-BAR")
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_notify",
            "--commit",
            "--max-notifications",
            "1",
            stdout=StringIO(),
        )
    assert len(mail.outbox) == 1


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_does_not_rewarn_within_cadence(org, django_capture_on_commit_callbacks):
    # This command is meant to be scheduled for the whole soft window, so it must
    # not mail every over-cap network on every run.
    net = make_net(org, 3061, "RIPE::AS-FOO RADB::AS-BAR")

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", "--commit", stdout=StringIO())
    assert len(mail.outbox) == 1
    net.refresh_from_db()
    assert net.irr_as_set_cap_notified is not None

    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", "--commit", stdout=StringIO())
    assert len(mail.outbox) == 1  # no reminder yet (default cadence is 30 days)


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_rewarns_after_cadence(org, django_capture_on_commit_callbacks):
    net = make_net(org, 3062, "RIPE::AS-FOO RADB::AS-BAR")
    Network.objects.filter(id=net.id).update(
        irr_as_set_cap_notified=timezone.now() - timedelta(days=40)
    )

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", "--commit", stdout=StringIO())
    assert len(mail.outbox) == 1  # 40 days > the 30-day default cadence


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_warn_once_with_zero_cadence(org, django_capture_on_commit_callbacks):
    net = make_net(org, 3063, "RIPE::AS-FOO RADB::AS-BAR")
    Network.objects.filter(id=net.id).update(
        irr_as_set_cap_notified=timezone.now() - timedelta(days=4000)
    )

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_irr_as_set_notify",
            "--commit",
            "--renotify-after-days",
            "0",
            stdout=StringIO(),
        )
    assert mail.outbox == []


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_max_notifications_advances_across_runs(
    org, django_capture_on_commit_callbacks
):
    make_net(org, 3071, "RIPE::AS-FOO RADB::AS-BAR")
    make_net(org, 3072, "RIPE::AS-FOO RADB::AS-BAR")

    mail.outbox = []
    for _run in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            call_command(
                "pdb_irr_as_set_notify",
                "--commit",
                "--max-notifications",
                "1",
                stdout=StringIO(),
            )

    recipients = sorted(address for message in mail.outbox for address in message.to)
    assert recipients == ["as3071@example.com", "as3072@example.com"]


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_dry_run_does_not_stamp_marker(org, django_capture_on_commit_callbacks):
    net = make_net(org, 3081, "RIPE::AS-FOO RADB::AS-BAR")
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", stdout=StringIO())
    net.refresh_from_db()
    assert net.irr_as_set_cap_notified is None


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_counts_sets_with_the_validators_tokenizer(
    org, django_capture_on_commit_callbacks
):
    # comma, comma-space and space are all separators for this field; the nudge
    # and the enforcement must agree on what counts as more than one set
    for asn, value in (
        (3091, "RIPE::AS-FOO,RADB::AS-BAR"),
        (3092, "RIPE::AS-FOO, RADB::AS-BAR"),
        (3093, "RIPE::AS-FOO RADB::AS-BAR"),
    ):
        make_net(org, asn, value)

    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_irr_as_set_notify", "--commit", stdout=StringIO())

    assert len(mail.outbox) == 3


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_commit_refuses_zero_max_notifications(org):
    # 0 means the same thing everywhere in this command family: refused under
    # --commit, never "no cap". pdb_irr_as_set_cleanup and pdb_irr_as_set_status
    # already did this; a cron entry written by analogy must not send an
    # unbounded mail run here instead.
    make_net(org, 3101, "RIPE::AS-FOO RADB::AS-BAR")

    mail.outbox = []
    with pytest.raises(CommandError) as excinfo:
        call_command(
            "pdb_irr_as_set_notify",
            "--commit",
            "--max-notifications",
            "0",
            stdout=StringIO(),
        )

    assert "positive --max-notifications" in str(excinfo.value)
    assert mail.outbox == []


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_dry_run_allows_zero_max_notifications(org):
    # the refusal is a --commit rule only, so 0 stays usable for reporting the
    # whole population -- again matching the sibling commands
    make_net(org, 3102, "RIPE::AS-FOO RADB::AS-BAR")

    out = StringIO()
    call_command("pdb_irr_as_set_notify", "--max-notifications", "0", stdout=out)

    assert "1 network(s) to warn" in out.getvalue()


@override_settings(
    MAIL_DEBUG=False,
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=SOFT,
    IRR_AS_SET_CAP_HARD_START=HARD_FUTURE,
)
def test_notify_rejects_negative_bounds(org):
    for flag in ("--max-notifications", "--renotify-after-days"):
        with pytest.raises(CommandError) as excinfo:
            call_command("pdb_irr_as_set_notify", flag, "-1", stdout=StringIO())
        assert "zero or greater" in str(excinfo.value)
