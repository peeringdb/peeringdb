import json
from pathlib import Path

import pytest
from allauth.account.models import EmailAddress
from django.conf import settings as dj_settings
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from grainy.const import PERM_CRUD
from rest_framework.test import APIClient

from peeringdb_server import deskpro
from peeringdb_server.inet import RdapAsn, RdapLookup
from peeringdb_server.models import (
    DeskProTicket,
    Network,
    Organization,
    OrganizationAPIKey,
    User,
    VerificationQueueItem,
)

pytestmark = pytest.mark.django_db

KEY_EMAIL = "noc@third-party.example"


@pytest.fixture
def org_key(settings):
    settings.USER_GROUP_ID = Group.objects.get_or_create(name="user")[0].pk
    settings.GUEST_GROUP_ID = Group.objects.get_or_create(name="guest")[0].pk
    org = Organization.objects.create(name="Org key ticket org", status="ok")
    key, secret = OrganizationAPIKey.objects.create_key(
        org=org, name="Automation", email=KEY_EMAIL
    )
    key.grainy_permissions.add_permission(org.grainy_namespace, PERM_CRUD)
    key.secret = secret
    return key


@pytest.fixture
def org_key_request(org_key, monkeypatch):
    monkeypatch.setattr(deskpro, "get_user_from_request", lambda request: None)
    monkeypatch.setattr(deskpro, "get_org_key_from_request", lambda request: org_key)
    return RequestFactory().post("/api/net")


UNVERIFIED_NOTICE = "UNVERIFIED REQUESTER"


def assert_key_requester(ticket, org_key, verified=False):
    """
    The key email is the requester so support can reply, the body names the
    org and key, and an unverified key email is flagged at the top.
    """
    assert ticket.user is None
    assert ticket.email == org_key.email
    assert ticket.email != dj_settings.DEFAULT_FROM_EMAIL
    assert org_key.prefix in ticket.body
    assert org_key.org.name in ticket.body
    if verified:
        assert UNVERIFIED_NOTICE not in ticket.body
    else:
        assert ticket.body.startswith(UNVERIFIED_NOTICE)
        assert org_key.email in ticket.body.split("\n")[0]


def test_org_key_asnauto_ticket_uses_key_requester(org_key, settings, monkeypatch):
    settings.TICKET_CREATION_ASNAUTO = True
    user = User.objects.create_user("key-admin", "neteng@20c.com", "pw")
    EmailAddress.objects.create(user=user, email="neteng@20c.com", verified=True)
    org_key.org.admin_usergroup.user_set.add(user)
    org_key.email = "neteng@20c.com"
    org_key.save()
    data = json.loads(
        (Path(__file__).parent / "data/api/rdap_override.json").read_text()
    )
    rdap = RdapAsn(data)
    monkeypatch.setattr(RdapLookup, "get_asn", lambda self, asn: rdap)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + org_key.secret)
    response = client.post(
        "/api/net",
        {
            "org_id": org_key.org.pk,
            "asn": 63311,
            "name": "Org key ticket network",
            "website": "https://www.example.com",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    ticket = DeskProTicket.objects.get(subject__contains="[ASNAUTO]")
    assert_key_requester(ticket, org_key, verified=True)
    assert "verified email address of an administrator" in ticket.body


def test_org_key_rdap_error_ticket_uses_key_requester(org_key, org_key_request):
    deskpro.ticket_queue_rdap_error(org_key_request, 63311, Exception("timeout"))

    ticket = DeskProTicket.objects.get(subject__contains="[RDAP_ERR]")
    assert_key_requester(ticket, org_key)
    assert KEY_EMAIL not in ticket.subject
    assert org_key.prefix in ticket.subject


def test_org_key_deletion_prevented_ticket_uses_key_requester(org_key, org_key_request):
    net = Network.objects.create(
        org=org_key.org, asn=63311, name="Undeletable", status="ok"
    )
    net.not_deletable_reason = "test reason"

    deskpro.ticket_queue_deletion_prevented(org_key_request, net)

    ticket = DeskProTicket.objects.get()
    assert_key_requester(ticket, org_key)


def test_org_key_vq_ticket_uses_key_requester(org_key):
    net = Network.objects.create(
        org=org_key.org, asn=63311, name="Pending network", status="pending"
    )
    # notified=True keeps the post_save notify signal from running its own
    # (live) RDAP lookup, the ticket is queued explicitly below
    vqi = VerificationQueueItem.objects.create(
        content_type=ContentType.objects.get_for_model(Network),
        object_id=net.id,
        org_key=org_key,
        notified=True,
    )

    deskpro.ticket_queue_vqi_notify(vqi, None)

    assert_key_requester(vqi.deskpro_ticket, org_key)


@pytest.mark.parametrize("group", ["usergroup", "admin_usergroup"])
def test_org_key_ticket_verified_org_user_email(org_key, org_key_request, group):
    """
    A key email that is a verified address of a member or admin of the key's
    org is not flagged
    """
    user = User.objects.create_user("key-user", "Noc@Third-Party.example", "pw")
    EmailAddress.objects.create(
        user=user, email="Noc@Third-Party.example", verified=True
    )
    getattr(org_key.org, group).user_set.add(user)

    deskpro.ticket_queue_rdap_error(org_key_request, 63311, Exception("timeout"))

    assert_key_requester(DeskProTicket.objects.get(), org_key, verified=True)


@pytest.mark.parametrize(
    "email_verified,in_org,is_active",
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ],
    ids=["unverified-address", "user-of-another-org", "inactive-user"],
)
def test_org_key_ticket_flags_unverified_requester(
    org_key, org_key_request, email_verified, in_org, is_active
):
    """
    The key email is flagged unless it is a verified address of an active
    user of the key's org
    """
    user = User.objects.create_user("key-user", KEY_EMAIL, "pw", is_active=is_active)
    EmailAddress.objects.create(user=user, email=KEY_EMAIL, verified=email_verified)
    if in_org:
        org_key.org.usergroup.user_set.add(user)
    else:
        other = Organization.objects.create(name="Other org", status="ok")
        other.admin_usergroup.user_set.add(user)

    deskpro.ticket_queue_rdap_error(org_key_request, 63311, Exception("timeout"))

    assert_key_requester(DeskProTicket.objects.get(), org_key)


def test_org_key_ticket_flags_accent_variant(org_key, org_key_request):
    """
    A member's verified address that only matches the key email under an
    accent-insensitive collation does not count
    """
    org_key.email = "jose@third-party.example"
    org_key.save()
    user = User.objects.create_user("key-user", "josé@third-party.example", "pw")
    EmailAddress.objects.create(
        user=user, email="josé@third-party.example", verified=True
    )
    org_key.org.usergroup.user_set.add(user)

    deskpro.ticket_queue_rdap_error(org_key_request, 63311, Exception("timeout"))

    assert_key_requester(DeskProTicket.objects.get(), org_key)
