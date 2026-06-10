import io
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from peeringdb_server.deskpro import APIClient, APIError
from peeringdb_server.deskpro import MockAPIClient as DeskProClient
from peeringdb_server.models import DeskProTicket, Group, User


class PartialCreateMockAPIClient(DeskProClient):
    """
    Mock client where creating the ticket itself succeeds (so deskpro_id /
    deskpro_ref get assigned on the instance) but the follow-up POST to
    tickets/{id}/messages fails. Used to exercise the partial-create path
    in pdb_deskpro_publish (#1948).
    """

    def create(self, endpoint, param):
        if endpoint == "tickets":
            self.ticket_count += 1
            return {"ref": "PARTIAL-REF", "id": 4242}
        # the messages POST (or anything else) blows up after the ticket
        # was already created on the DeskPro side
        raise APIError(
            "API error posting ticket message.",
            {"error": "API error posting ticket message.", "code": "mock-error"},
        )


@pytest.fixture
def admin_user():
    guest_group, _ = Group.objects.get_or_create(name="guest")
    user_group, _ = Group.objects.get_or_create(name="user")

    print(f"Guest: {guest_group} {guest_group.id} ")
    print(f"User: {user_group} {user_group.id} ")

    admin_user = User.objects.create_user("admin", "admin@localhost")
    admin_user.is_superuser = True
    admin_user.is_staff = True
    admin_user.save()
    admin_user.set_password("admin")
    admin_user.save()
    return admin_user


@pytest.mark.django_db
def test_deskpro_person_noname(admin_user):
    deskpro_client = DeskProClient("", "")

    payload = deskpro_client.update_person_payload(
        {"primary_email": admin_user.email}, admin_user, admin_user.email
    )

    assert payload.get("name") == admin_user.username


@pytest.mark.django_db
def test_deskpro_person_email(admin_user):
    deskpro_client = DeskProClient("", "")

    admin_user.first_name = "Django"
    admin_user.last_name = "User"
    admin_user.save()

    payload = deskpro_client.update_person_payload(
        {"primary_email": admin_user.email}, None, admin_user.email
    )

    assert payload.get("name") == admin_user.email


@pytest.mark.django_db
def test_deskpro_person(admin_user):
    deskpro_client = DeskProClient("", "")

    admin_user.first_name = "Django"
    admin_user.last_name = "User"
    admin_user.save()

    payload = deskpro_client.update_person_payload(
        {"primary_email": admin_user.email}, admin_user, admin_user.email
    )

    assert payload.get("name") == "Django User"


@pytest.mark.django_db
@override_settings(DESKPRO_AUTO_CLOSE_STATUSES=["awaiting_agent"])
def test_close_ticket_resolves_when_status_in_set():
    """
    close_ticket resolves a ticket whose current DeskPro status is in
    DESKPRO_AUTO_CLOSE_STATUSES (#1948).
    """
    client = APIClient("", "")
    client.get = MagicMock(return_value={"ticket_status": "awaiting_agent"})
    client.update = MagicMock(return_value={})

    result = client.close_ticket(123)

    assert result is True
    client.update.assert_called_once_with("tickets/123", {"status": "resolved"})


@pytest.mark.django_db
@override_settings(DESKPRO_AUTO_CLOSE_STATUSES=["awaiting_agent"])
def test_close_ticket_skips_when_status_not_in_set():
    """
    close_ticket does NOT resolve a ticket whose current status is outside
    the configured set (e.g. an agent already moved it to awaiting_user).
    """
    client = APIClient("", "")
    client.get = MagicMock(return_value={"ticket_status": "awaiting_user"})
    client.update = MagicMock(return_value={})

    result = client.close_ticket(123)

    assert result is False
    client.update.assert_not_called()


@pytest.mark.django_db
@override_settings(DESKPRO_AUTO_CLOSE_STATUSES=["awaiting_agent", "awaiting_user"])
def test_close_ticket_honors_configurable_status_set():
    """
    The set of auto-close statuses is configurable; a status that is only
    eligible because it was added to the setting is resolved.
    """
    client = APIClient("", "")
    client.get = MagicMock(return_value={"ticket_status": "awaiting_user"})
    client.update = MagicMock(return_value={})

    result = client.close_ticket(123)

    assert result is True
    client.update.assert_called_once_with("tickets/123", {"status": "resolved"})


@pytest.mark.django_db
def test_close_ticket_skips_when_ticket_missing():
    """
    close_ticket bails out gracefully if the ticket can't be fetched.
    """
    client = APIClient("", "")
    client.get = MagicMock(return_value={})
    client.update = MagicMock(return_value={})

    result = client.close_ticket(123)

    assert result is False
    client.update.assert_not_called()


@pytest.mark.django_db
def test_deskpro_publish_processes_close_requests():
    """
    pdb_deskpro_publish should process tickets flagged with
    close_requested=True, call close_ticket and stamp `closed` (#1948).
    """
    mock_client = DeskProClient("", "")

    ticket = DeskProTicket.objects.create(
        subject="test close",
        body="",
        user=None,
        email="test@example.com",
        deskpro_id=55,
        deskpro_ref="REF-55",
        close_requested=True,
    )

    out = io.StringIO()
    with patch("peeringdb_server.deskpro.APIClient", return_value=mock_client):
        call_command("pdb_deskpro_publish", stdout=out)

    ticket.refresh_from_db()

    assert 55 in mock_client.closed_tickets
    assert ticket.closed is not None


@pytest.mark.django_db
def test_deskpro_publish_drops_unpublished_close_requests():
    """
    A close request on a ticket that was never published (no deskpro_id)
    is dropped: there is nothing to close on the DeskPro side, so the local
    row is deleted and no create/close call is made (#1948).
    """
    mock_client = DeskProClient("", "")

    ticket = DeskProTicket.objects.create(
        subject="test close unpublished",
        body="",
        user=None,
        email="test@example.com",
        deskpro_id=None,
        close_requested=True,
    )
    ticket_id = ticket.id

    out = io.StringIO()
    with patch("peeringdb_server.deskpro.APIClient", return_value=mock_client):
        call_command("pdb_deskpro_publish", stdout=out)

    # not published (excluded from the create pass) and not closed via API
    assert mock_client.ticket_count == 0
    assert mock_client.closed_tickets == []
    # local row dropped by the close pass
    assert not DeskProTicket.objects.filter(id=ticket_id).exists()


@pytest.mark.django_db
def test_deskpro_publish_skips_close_requested_when_creating():
    """
    The create pass must not publish a ticket already flagged for close —
    the related object was deleted before it was ever sent (#1948).
    """
    mock_client = DeskProClient("", "")

    DeskProTicket.objects.create(
        subject="flagged before publish",
        body="",
        user=None,
        email="test@example.com",
        deskpro_id=None,
        close_requested=True,
    )

    out = io.StringIO()
    with patch("peeringdb_server.deskpro.APIClient", return_value=mock_client):
        call_command("pdb_deskpro_publish", stdout=out)

    assert mock_client.ticket_count == 0


@pytest.mark.django_db
@override_settings(MAIL_DEBUG=True)
def test_deskpro_publish_preserves_deskpro_id_on_partial_create():
    """
    If create_ticket creates the ticket on DeskPro (assigning deskpro_id /
    deskpro_ref) but a later call fails, the error branch must still persist
    deskpro_id / deskpro_ref. Otherwise the local row looks unpublished and a
    later close request would drop it, orphaning the real DeskPro ticket
    (#1948).
    """
    mock_client = PartialCreateMockAPIClient("", "")

    ticket = DeskProTicket.objects.create(
        subject="partial create",
        body="body",
        user=None,
        email="test@example.com",
        deskpro_id=None,
    )

    out = io.StringIO()
    with patch("peeringdb_server.deskpro.APIClient", return_value=mock_client):
        call_command("pdb_deskpro_publish", stdout=out)

    ticket.refresh_from_db()

    # ticket was created on DeskPro before the message POST failed
    assert mock_client.ticket_count == 1
    # the partial-create result is preserved locally
    assert ticket.deskpro_id == 4242
    assert ticket.deskpro_ref == "PARTIAL-REF"
    # and it is marked failed/published, so the create pass won't retry it
    assert ticket.published is not None
    assert "[FAILED]" in ticket.subject
