from unittest.mock import patch

import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rdap.assignment import RIRAssignmentLookup

from peeringdb_server.mail import mail_network_rir_status_flagged
from peeringdb_server.models import Network, NetworkContact, Organization

now = timezone.now()


@pytest.mark.parametrize(
    "network, rdap_rir_status,new_rir_status, new_network_status",
    [
        (
            {
                "name": "test network",
                "rir_status": "ok",
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=100),
                "rir_status_notified": None,
            },
            None,
            "missing",
            "ok",
        ),
        (
            {
                "name": "test network",
                "rir_status": "pending",
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=100),
                "rir_status_notified": None,
            },
            "assigned",
            "assigned",
            "ok",
        ),
        (
            {
                "name": "test network",
                "rir_status": "reserved",
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=100),
                # already warned, so the network is eligible for deletion
                "rir_status_notified": now - timezone.timedelta(days=100),
            },
            "reserved",
            "reserved",
            "deleted",
        ),
        (
            {
                "name": "test network",
                "rir_status": None,
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=100),
                "rir_status_notified": None,
            },
            "assigned",
            "assigned",
            "ok",
        ),
    ],
)
@pytest.mark.django_db
def test_pdb_rir_status_asn(
    network, rdap_rir_status, new_rir_status, new_network_status
):
    with patch.object(
        RIRAssignmentLookup,
        "load_data",
        side_effect=lambda data_path, cache_days: None,
    ):
        org = Organization.objects.create(name="test org")
        Network.objects.bulk_create(
            [Network(org=org, **network, updated=now, status="ok")]
        )
        net = Network.objects.first()
        with patch.object(
            RIRAssignmentLookup,
            "get_status",
            side_effect=lambda asn: rdap_rir_status,
        ):
            # without commit
            call_command("pdb_rir_status", asn=net.asn)
            assert net.rir_status == network.get("rir_status")
            call_command("pdb_rir_status", asn=net.asn, commit=True)
            net.refresh_from_db()
            if new_network_status == "deleted":
                assert net.status == "deleted"
            else:
                assert net.rir_status == new_rir_status
                assert net.rir_status_updated >= network.get("rir_status_updated")


@override_settings(KEEP_RIR_STATUS=90)
@pytest.mark.django_db
def test_pdb_rir_status():
    with patch.object(
        RIRAssignmentLookup,
        "load_data",
        side_effect=lambda data_path, cache_days: None,
    ):
        org = Organization.objects.create(name="test org")
        network_list = [
            {
                "rir_status": "reserved",
                "asn": 1231,
                "rir_status_updated": now - timezone.timedelta(days=92),
                "rir_status_notified": now - timezone.timedelta(days=92),
            },
            {
                "rir_status": "reserved",
                "asn": 1232,
                "rir_status_updated": now - timezone.timedelta(days=91),
                "rir_status_notified": now - timezone.timedelta(days=91),
            },
            {
                "rir_status": "reserved",
                "asn": 1233,
                "rir_status_updated": now - timezone.timedelta(days=89),
                "rir_status_notified": now - timezone.timedelta(days=89),
            },
            {
                "rir_status": "reserved",
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=90),
                "rir_status_notified": now - timezone.timedelta(days=90),
            },
            {
                "rir_status": "ok",
                "asn": 1235,
                "rir_status_updated": now - timezone.timedelta(days=10),
            },
            {
                "rir_status": None,
                "asn": 1236,
                "rir_status_updated": now - timezone.timedelta(days=100),
            },
            {
                "rir_status": "ok",
                "asn": 1237,
                "rir_status_updated": now - timezone.timedelta(days=120),
            },
        ]

        rdap_rir_list = {
            "1231": "ok",
            "1232": "reserved",
            "1233": "available",
            "1234": "available",
            "1235": "reserved",
            "1236": "assigned",
        }
        with patch.object(
            RIRAssignmentLookup,
            "get_status",
            side_effect=lambda asn: rdap_rir_list.get(str(asn)),
        ):
            Network.objects.bulk_create(
                [
                    Network(
                        org=org, name=f"net-{i}", **network, updated=now, status="ok"
                    )
                    for i, network in enumerate(network_list)
                ]
            )

            # without commit
            call_command("pdb_rir_status")
            assert Network.objects.filter(status="ok").count() == len(network_list)
            assert Network.objects.filter(status="deleted").count() == 0

            call_command("pdb_rir_status", commit=True)
            assert Network.objects.filter(status="deleted").count() == 2
            assert (
                Network.objects.filter(status="ok", rir_status="missing").count() == 1
            )
            assert Network.objects.filter(status="ok").count() == 5


def _make_net(org, asn, **kwargs):
    net = Network.objects.create(
        org=org,
        asn=asn,
        name=f"net-{asn}",
        status="ok",
        updated=now,
    )
    # The rir_status_initial pre_save signal forces rir_status="pending" on
    # create, so set the desired RIR test state directly via update() (which
    # bypasses signals), mirroring the bulk_create approach used above.
    rir_fields = {
        field: kwargs[field]
        for field in ("rir_status", "rir_status_updated", "rir_status_notified")
        if field in kwargs
    }
    if rir_fields:
        Network.objects.filter(pk=net.pk).update(**rir_fields)
        net.refresh_from_db()
    return net


@override_settings(KEEP_RIR_STATUS=1)
@pytest.mark.django_db
def test_rir_status_default_keep_is_one_day():
    """
    GH #1942: with a 1-day deletion window, a network warned 2 days ago and
    still unassigned should be deleted.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _make_net(
            org,
            1234,
            rir_status="missing",
            rir_status_updated=now - timezone.timedelta(days=2),
            rir_status_notified=now - timezone.timedelta(days=2),
        )
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
        ):
            call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert net.status == "deleted"


@pytest.mark.django_db
def test_rir_status_flag_notifies_contacts(django_capture_on_commit_callbacks):
    """
    GH #1942: when a network is flagged (good -> bad) its contacts are warned
    and the network is NOT deleted on that same run (rir_status_notified gates
    deletion). Notifications fire on transaction commit.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _make_net(
            org,
            1234,
            rir_status="ok",
            rir_status_updated=now - timezone.timedelta(days=100),
        )
        NetworkContact.objects.create(
            network=net, role="Technical", email="tech@example.com", status="ok"
        )
        NetworkContact.objects.create(
            network=net, role="Policy", email="policy@example.com", status="ok"
        )

        mail.outbox = []
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
        ):
            with django_capture_on_commit_callbacks(execute=True):
                call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    # flagged, warned, but not yet deleted
    assert net.status == "ok"
    assert net.rir_status == "missing"
    assert net.rir_status_notified is not None

    assert len(mail.outbox) == 1
    recipients = set(mail.outbox[0].to)
    assert recipients == {"tech@example.com", "policy@example.com"}


@override_settings(RIR_STATUS_NOTIFY_ROLES=["technical"])
@pytest.mark.django_db
def test_rir_status_notify_roles_filter(django_capture_on_commit_callbacks):
    """
    GH #1942: only contacts whose role is in RIR_STATUS_NOTIFY_ROLES are warned.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _make_net(
            org,
            1234,
            rir_status="ok",
            rir_status_updated=now - timezone.timedelta(days=100),
        )
        NetworkContact.objects.create(
            network=net, role="Technical", email="tech@example.com", status="ok"
        )
        NetworkContact.objects.create(
            network=net, role="Sales", email="sales@example.com", status="ok"
        )

        mail.outbox = []
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
        ):
            with django_capture_on_commit_callbacks(execute=True):
                call_command("pdb_rir_status", asn=net.asn, commit=True)

    assert len(mail.outbox) == 1
    assert set(mail.outbox[0].to) == {"tech@example.com"}


@override_settings(RIR_STATUS_NOTIFY_ROLES=[])
@pytest.mark.django_db
def test_rir_status_notify_roles_empty_disables(django_capture_on_commit_callbacks):
    """
    GH #1942: an empty RIR_STATUS_NOTIFY_ROLES disables operator notifications,
    but the network is still flagged and gated for deletion.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _make_net(
            org,
            1234,
            rir_status="ok",
            rir_status_updated=now - timezone.timedelta(days=100),
        )
        NetworkContact.objects.create(
            network=net, role="Technical", email="tech@example.com", status="ok"
        )

        mail.outbox = []
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
        ):
            with django_capture_on_commit_callbacks(execute=True):
                call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert len(mail.outbox) == 0
    assert net.status == "ok"
    assert net.rir_status_notified is not None


@pytest.mark.django_db
def test_rir_status_legacy_flagged_not_deleted_until_notified(
    django_capture_on_commit_callbacks,
):
    """
    GH #1942: a network flagged before notifications existed (bad status,
    rir_status_notified is None) is warned and deferred rather than deleted on
    the first run, guaranteeing at least one warning.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _make_net(
            org,
            1234,
            rir_status="missing",
            rir_status_updated=now - timezone.timedelta(days=100),
            rir_status_notified=None,
        )
        NetworkContact.objects.create(
            network=net, role="NOC", email="noc@example.com", status="ok"
        )

        mail.outbox = []
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
        ):
            with django_capture_on_commit_callbacks(execute=True):
                call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    # deferred, not deleted; warned now
    assert net.status == "ok"
    assert net.rir_status_notified is not None
    assert len(mail.outbox) == 1
    assert set(mail.outbox[0].to) == {"noc@example.com"}


@pytest.mark.django_db
def test_rir_status_recovery_clears_notified():
    """
    GH #1942: when a network's RIR assignment recovers (bad -> good), the
    notification marker is cleared so a future flagging starts fresh.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _make_net(
            org,
            1234,
            rir_status="missing",
            rir_status_updated=now - timezone.timedelta(days=2),
            rir_status_notified=now - timezone.timedelta(days=2),
        )
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: "assigned"
        ):
            call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert net.status == "ok"
    assert net.rir_status == "assigned"
    assert net.rir_status_notified is None


@pytest.mark.django_db
def test_rir_status_notification_failure_does_not_block_flagging(
    django_capture_on_commit_callbacks,
):
    """
    GH #1942 regression: a failing notification (SMTP error / bad recipient)
    must not roll back the RIR status changes nor abort the run. Because
    notifications fire on commit and each send is isolated, the network is
    still recorded as flagged + notified, so it is not warned again next run.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _make_net(
            org,
            1234,
            rir_status="ok",
            rir_status_updated=now - timezone.timedelta(days=100),
        )
        NetworkContact.objects.create(
            network=net, role="Technical", email="tech@example.com", status="ok"
        )

        with (
            patch.object(
                RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
            ),
            patch(
                "peeringdb_server.management.commands.pdb_rir_status.mail_network_rir_status_flagged",
                side_effect=Exception("smtp boom"),
            ),
        ):
            with django_capture_on_commit_callbacks(execute=True):
                # the failing send must be swallowed, not propagated
                call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert net.status == "ok"
    assert net.rir_status == "missing"
    assert net.rir_status_notified is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "days, expected_phrase",
    [(1, "in 1 day"), (30, "in 30 days")],
)
def test_rir_status_notification_email_content(days, expected_phrase):
    """
    GH #1942: the operator notification renders the ASN, the network name, the
    correctly pluralized days-until-deletion, and a link to the network, and
    attaches an HTML alternative.
    """
    org = Organization.objects.create(name="test org")
    net = _make_net(org, 1234)

    mail.outbox = []
    mail_network_rir_status_flagged(net, ["tech@example.com"], days)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]

    assert msg.to == ["tech@example.com"]
    assert "AS1234" in msg.subject

    assert "AS1234" in msg.body
    assert net.name in msg.body
    assert expected_phrase in msg.body
    assert net.view_url in msg.body

    # an HTML alternative is attached
    assert any(
        content_type == "text/html" for _content, content_type in msg.alternatives
    )


@pytest.mark.django_db
def test_rir_status_notification_email_no_recipients_skipped():
    """
    GH #1942: the mailer is a no-op when there are no recipients.
    """
    org = Organization.objects.create(name="test org")
    net = _make_net(org, 1234)

    mail.outbox = []
    mail_network_rir_status_flagged(net, [], 1)

    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_rir_status_notification_per_run_cap(django_capture_on_commit_callbacks):
    """
    GH #1942: the legacy not-notified branch is not bounded by --max-changes,
    so --max-notifications caps how many networks are warned per run. The rest
    keep rir_status_notified unset and are handled on subsequent runs (this
    bounds the first-deploy burst against an existing flagged backlog).
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        for asn in (1001, 1002, 1003, 1004):
            net = _make_net(
                org,
                asn,
                rir_status="missing",
                rir_status_updated=now - timezone.timedelta(days=100),
                rir_status_notified=None,
            )
            NetworkContact.objects.create(
                network=net,
                role="Technical",
                email=f"poc-{asn}@example.com",
                status="ok",
            )

        mail.outbox = []
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
        ):
            with django_capture_on_commit_callbacks(execute=True):
                call_command("pdb_rir_status", commit=True, max_notifications=2)

    # only the cap's worth were notified this run; nothing deleted (all deferred)
    assert len(mail.outbox) == 2
    assert (
        Network.objects.filter(status="ok", rir_status_notified__isnull=False).count()
        == 2
    )
    assert (
        Network.objects.filter(status="ok", rir_status_notified__isnull=True).count()
        == 2
    )
    assert Network.objects.filter(status="deleted").count() == 0


@pytest.mark.django_db
def test_rir_status_per_run_cap_good_to_bad(django_capture_on_commit_callbacks):
    """
    GH #1942: the per-run cap also applies to the good->bad branch (it shares
    the networks_to_notify budget). A freshly-flagged network past the cap still
    has its rir_status flag saved, but keeps rir_status_notified unset (no email,
    not deleted) so it is warned on a later run.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        for asn in (2001, 2002):
            net = _make_net(
                org,
                asn,
                rir_status="ok",
                rir_status_updated=now - timezone.timedelta(days=100),
            )
            NetworkContact.objects.create(
                network=net,
                role="Technical",
                email=f"poc-{asn}@example.com",
                status="ok",
            )

        mail.outbox = []
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
        ):
            with django_capture_on_commit_callbacks(execute=True):
                call_command("pdb_rir_status", commit=True, max_notifications=1)

    # processed in ASN order: 2001 is under the cap, 2002 is past it
    notified = Network.objects.get(asn=2001)
    deferred = Network.objects.get(asn=2002)

    # both flagged ...
    assert notified.rir_status == "missing"
    assert deferred.rir_status == "missing"
    # ... but only the under-cap one is recorded as notified and emailed
    assert notified.rir_status_notified is not None
    assert deferred.rir_status_notified is None
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["poc-2001@example.com"]
    # nothing deleted (good->bad only flags)
    assert Network.objects.filter(status="deleted").count() == 0


@override_settings(RIR_STATUS_NOTIFY_ROLES=[""])
@pytest.mark.django_db
def test_rir_status_notify_roles_empty_string_disables():
    """
    GH #1942: a blank role entry -- as produced by an empty env var via
    _set_list, which yields [''] rather than [] -- is treated as no roles, so
    no contacts are returned.
    """
    org = Organization.objects.create(name="test org")
    net = _make_net(org, 1234)
    NetworkContact.objects.create(
        network=net, role="Technical", email="tech@example.com", status="ok"
    )

    assert net.rir_status_notify_contacts == []


@pytest.mark.django_db
def test_rir_status_notify_contacts_default_roles():
    """
    GH #1942: by default only the operational roles (Technical/NOC/Policy) are
    notified -- Sales/Public Relations/Abuse/Maintenance can't action a RIR
    registration issue and are excluded.
    """
    org = Organization.objects.create(name="test org")
    net = _make_net(org, 1234)

    notified = {
        "Technical": "tech@example.com",
        "NOC": "noc@example.com",
        "Policy": "policy@example.com",
    }
    excluded = {
        "Sales": "sales@example.com",
        "Public Relations": "pr@example.com",
        "Abuse": "abuse@example.com",
        "Maintenance": "maint@example.com",
    }
    for role, email in {**notified, **excluded}.items():
        NetworkContact.objects.create(network=net, role=role, email=email, status="ok")

    assert set(net.rir_status_notify_contacts) == set(notified.values())


@pytest.mark.django_db
def test_rir_status_reset_clears_notified():
    """
    GH #1942: --reset re-reads RIR status, bumps rir_status_updated, and clears
    rir_status_notified, resetting both the deletion and notification cycle.
    """
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _make_net(
            org,
            1234,
            rir_status="missing",
            rir_status_updated=now - timezone.timedelta(days=100),
            rir_status_notified=now - timezone.timedelta(days=100),
        )
        with patch.object(
            RIRAssignmentLookup, "get_status", side_effect=lambda asn: "assigned"
        ):
            call_command("pdb_rir_status", reset=True, commit=True)

    net.refresh_from_db()
    assert net.status == "ok"
    assert net.rir_status == "assigned"
    assert net.rir_status_notified is None
