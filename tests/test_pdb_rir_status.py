from unittest.mock import MagicMock, patch

import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rdap.assignment import RIRAssignmentLookup
from rdap.exceptions import RdapNotFoundError

from peeringdb_server.inet import RdapInvalidRange
from peeringdb_server.mail import mail_network_rir_status_flagged
from peeringdb_server.models import Network, NetworkContact, Organization

try:
    from rdap.exceptions import RdapBootstrapError
except ImportError:  # rdap without the GH #2001 bootstrap-miss split
    RdapBootstrapError = None

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
# the RDAP recheck (GH #2001) is exercised separately below; these cases test
# the RIR-data/timer gate, so keep the pre-recheck behaviour
@override_settings(RIR_STATUS_VERIFY_BEFORE_DELETE=False)
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


@override_settings(KEEP_RIR_STATUS=90, RIR_STATUS_VERIFY_BEFORE_DELETE=False)
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


@override_settings(KEEP_RIR_STATUS=1, RIR_STATUS_VERIFY_BEFORE_DELETE=False)
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


def _eligible_for_deletion(org, asn):
    """A network past every RIR-data/timer deletion gate (unassigned, warned,
    window elapsed) -- so only the GH #2001 RDAP recheck decides its fate."""
    return _make_net(
        org,
        asn,
        rir_status="missing",
        rir_status_updated=now - timezone.timedelta(days=2),
        rir_status_notified=now - timezone.timedelta(days=2),
    )


@override_settings(KEEP_RIR_STATUS=1)
@pytest.mark.django_db
def test_rir_status_skips_delete_when_rdap_still_resolves():
    """
    GH #2001: a network eligible for deletion per RIR data must NOT be deleted
    if a live RDAP lookup still resolves the ASN -- this is the guard against
    deletions driven by stale/partial RIR delegated-stats data.
    """
    mock_rdap = MagicMock()
    mock_rdap.get_asn.return_value = MagicMock()  # ASN still exists in RDAP
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _eligible_for_deletion(org, 219272)
        with (
            patch.object(
                RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
            ),
            patch(
                "peeringdb_server.management.commands.pdb_rir_status.RdapLookup",
                return_value=mock_rdap,
            ),
        ):
            call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert net.status == "ok"
    assert net.rir_status == "missing"
    mock_rdap.get_asn.assert_called_once_with(219272)


@override_settings(KEEP_RIR_STATUS=1)
@pytest.mark.django_db
def test_rir_status_deletes_when_rdap_confirms_gone():
    """
    GH #2001: when live RDAP positively reports the ASN as not found, the
    reclaim is confirmed and the network is deleted as before.
    """
    mock_rdap = MagicMock()
    mock_rdap.get_asn.side_effect = RdapNotFoundError()
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _eligible_for_deletion(org, 1234)
        with (
            patch.object(
                RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
            ),
            patch(
                "peeringdb_server.management.commands.pdb_rir_status.RdapLookup",
                return_value=mock_rdap,
            ),
        ):
            call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert net.status == "deleted"


@override_settings(KEEP_RIR_STATUS=1)
@pytest.mark.django_db
def test_rir_status_defers_delete_when_rdap_lookup_errors():
    """
    GH #2001: if the RDAP recheck itself errors (network/rate-limit), the
    reclaim is unverified, so deletion is deferred rather than risking removal
    of a live network on transient failure.
    """
    mock_rdap = MagicMock()
    mock_rdap.get_asn.side_effect = Exception("rdap unreachable")
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _eligible_for_deletion(org, 1234)
        with (
            patch.object(
                RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
            ),
            patch(
                "peeringdb_server.management.commands.pdb_rir_status.RdapLookup",
                return_value=mock_rdap,
            ),
        ):
            call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert net.status == "ok"


@override_settings(KEEP_RIR_STATUS=1)
@pytest.mark.django_db
def test_rir_status_deletes_bogon_asn_when_rdap_reports_invalid_range():
    """
    GH #2001: a private/reserved (bogon) ASN can never be a valid RIR
    assignment, so RdapInvalidRange is treated as a confirmed reclaim and the
    network is deleted -- not deferred forever.
    """
    mock_rdap = MagicMock()
    mock_rdap.get_asn.side_effect = RdapInvalidRange()
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _eligible_for_deletion(org, 64512)
        with (
            patch.object(
                RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
            ),
            patch(
                "peeringdb_server.management.commands.pdb_rir_status.RdapLookup",
                return_value=mock_rdap,
            ),
        ):
            call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert net.status == "deleted"


@override_settings(KEEP_RIR_STATUS=1)
@pytest.mark.django_db
@pytest.mark.skipif(
    RdapBootstrapError is None,
    reason="requires rdap with the GH #2001 RdapBootstrapError split",
)
def test_rir_status_defers_delete_on_rdap_bootstrap_miss():
    """
    GH #2001: a bootstrap miss (RDAP resolved no service, so no registry query
    happened) must NOT be treated as confirmation the ASN is gone. A freshly
    assigned block can lag bootstrap the same way it lags the RIR snapshot, so
    the two sources are not independent -- defer instead of deleting.
    """
    mock_rdap = MagicMock()
    mock_rdap.get_asn.side_effect = RdapBootstrapError("no service for asn")
    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        net = _eligible_for_deletion(org, 219273)
        with (
            patch.object(
                RIRAssignmentLookup, "get_status", side_effect=lambda asn: None
            ),
            patch(
                "peeringdb_server.management.commands.pdb_rir_status.RdapLookup",
                return_value=mock_rdap,
            ),
        ):
            call_command("pdb_rir_status", asn=net.asn, commit=True)

    net.refresh_from_db()
    assert net.status == "ok"
    assert net.rir_status == "missing"


@override_settings(KEEP_RIR_STATUS=1)
@pytest.mark.django_db
def test_rir_status_recheck_only_at_delete_gate():
    """
    GH #2001 guard: the live RDAP recheck must fire ONLY for networks actually
    at the delete gate -- not for good->bad, not-yet-notified, or recovering
    networks. Guards against a future refactor calling RDAP for every net.
    """
    mock_rdap = MagicMock()
    mock_rdap.get_asn.return_value = MagicMock()  # ASN exists -> defer, no delete

    # 3001 good->bad, 3002 bad->bad not yet notified, 3003 bad->good recovery,
    # 3004 bad->bad notified + window elapsed (the only one at the delete gate)
    rir_status_map = {3001: None, 3002: None, 3003: "allocated", 3004: None}

    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        _make_net(
            org,
            3001,
            rir_status="ok",
            rir_status_updated=now - timezone.timedelta(days=5),
            rir_status_notified=None,
        )
        _make_net(
            org,
            3002,
            rir_status="missing",
            rir_status_updated=now - timezone.timedelta(days=5),
            rir_status_notified=None,
        )
        _make_net(
            org,
            3003,
            rir_status="missing",
            rir_status_updated=now - timezone.timedelta(days=5),
            rir_status_notified=now - timezone.timedelta(days=5),
        )
        _eligible_for_deletion(org, 3004)

        with (
            patch.object(
                RIRAssignmentLookup,
                "get_status",
                side_effect=lambda asn: rir_status_map.get(asn),
            ),
            patch(
                "peeringdb_server.management.commands.pdb_rir_status.RdapLookup",
                return_value=mock_rdap,
            ),
        ):
            call_command("pdb_rir_status", commit=True)

    # RDAP consulted for exactly the one net at the delete gate, nobody else
    mock_rdap.get_asn.assert_called_once_with(3004)


@override_settings(KEEP_RIR_STATUS=1)
@pytest.mark.django_db
def test_rir_status_multi_net_delete_defer_recover_in_one_run():
    """
    GH #2001: eligible networks are handled independently within one run -- one
    deleted (RDAP confirms gone), one deferred (RDAP still resolves), one
    recovered (RIR data now ok) -- with no cross-contamination.
    """

    def rdap_get_asn(asn):
        if asn == 4001:
            raise RdapNotFoundError()  # confirmed gone -> delete
        return MagicMock()  # 4002 still resolves -> defer

    mock_rdap = MagicMock()
    mock_rdap.get_asn.side_effect = rdap_get_asn

    rir_status_map = {4001: None, 4002: None, 4003: "allocated"}

    with patch.object(
        RIRAssignmentLookup, "load_data", side_effect=lambda data_path, cache_days: None
    ):
        org = Organization.objects.create(name="test org")
        n1 = _eligible_for_deletion(org, 4001)
        n2 = _eligible_for_deletion(org, 4002)
        n3 = _make_net(
            org,
            4003,
            rir_status="missing",
            rir_status_updated=now - timezone.timedelta(days=2),
            rir_status_notified=now - timezone.timedelta(days=2),
        )

        with (
            patch.object(
                RIRAssignmentLookup,
                "get_status",
                side_effect=lambda asn: rir_status_map.get(asn),
            ),
            patch(
                "peeringdb_server.management.commands.pdb_rir_status.RdapLookup",
                return_value=mock_rdap,
            ),
        ):
            call_command("pdb_rir_status", commit=True)

    n1.refresh_from_db()
    n2.refresh_from_db()
    n3.refresh_from_db()
    assert n1.status == "deleted"  # RDAP confirmed gone
    assert n2.status == "ok"  # RDAP resolved -> deferred
    assert n2.rir_status == "missing"
    assert n3.status == "ok"  # recovered
    assert n3.rir_status == "allocated"
    assert n3.rir_status_notified is None  # recovery clears the marker


@override_settings(MAIL_DEBUG=False)
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


@override_settings(RIR_STATUS_NOTIFY_ROLES=["technical"], MAIL_DEBUG=False)
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


@override_settings(MAIL_DEBUG=True)
@pytest.mark.django_db
def test_rir_status_mail_debug_suppresses_email(django_capture_on_commit_callbacks):
    """
    GH #1942: with MAIL_DEBUG set (non-prod envs), no removal email is put on the
    wire, but the network is still flagged and marked notified.
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


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_rir_status_mute_notifications(django_capture_on_commit_callbacks):
    """
    GH #1942: --mute-notifications runs the full flagging/deletion logic (network
    still flagged and marked notified) but sends no removal emails, even with
    MAIL_DEBUG off.
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
                call_command(
                    "pdb_rir_status",
                    asn=net.asn,
                    commit=True,
                    mute_notifications=True,
                )

    net.refresh_from_db()
    assert len(mail.outbox) == 0
    assert net.status == "ok"
    assert net.rir_status_notified is not None


@override_settings(MAIL_DEBUG=False)
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


@override_settings(MAIL_DEBUG=False)
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


@override_settings(MAIL_DEBUG=False)
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


@override_settings(MAIL_DEBUG=False)
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
