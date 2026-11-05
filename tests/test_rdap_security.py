import io
import json
from pathlib import Path

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory
from grainy.const import PERM_CRUD
from rest_framework.test import APIClient
from reversion.models import Version

from peeringdb_server import settings as pdb_settings
from peeringdb_server.api_key_views import manage_key_update
from peeringdb_server.inet import RdapAsn, RdapLookup
from peeringdb_server.models import (
    DeskProTicket,
    Network,
    Organization,
    OrganizationAPIKey,
    User,
    UserOrgAffiliationRequest,
)
from peeringdb_server.views import view_affiliate_to_org

from .util import mock_csrf_session

pytestmark = pytest.mark.django_db


@pytest.fixture
def rdap_owner(settings, monkeypatch):
    settings.USER_GROUP_ID = Group.objects.get_or_create(name="user")[0].pk
    settings.GUEST_GROUP_ID = Group.objects.get_or_create(name="guest")[0].pk
    settings.AUTO_UNDELETE_NETWORK = True
    monkeypatch.setattr(pdb_settings, "AUTO_APPROVE_AFFILIATION", False)
    user = User.objects.create_user("rdap-owner", "neteng@20c.com", "owner-password")
    data = json.loads(
        (Path(__file__).parent / "data/api/rdap_override.json").read_text()
    )
    rdap = RdapAsn(data)
    monkeypatch.setattr(RdapLookup, "get_asn", lambda self, asn: rdap)
    return user, rdap


def set_email_case(user, case):
    if case == "missing":
        return False
    if case == "other-user":
        other = User.objects.create_user("other-owner", "other@example.net")
        EmailAddress.objects.create(user=other, email=user.email, verified=True)
        return False
    secondary = case.startswith("secondary")
    if secondary:
        user.email = "unverified-primary@example.net"
        user.save()
        EmailAddress.objects.create(user=user, email=user.email, primary=True)
    verified = case.endswith("verified") and not case.endswith("unverified")
    EmailAddress.objects.create(
        user=user, email="NetEng@20c.com", primary=not secondary, verified=verified
    )
    return verified


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "primary-unverified",
        "primary-verified",
        "secondary-unverified",
        "secondary-verified",
        "other-user",
    ],
)
def test_rdap_requires_ownership_of_matching_email(rdap_owner, case):
    user, rdap = rdap_owner
    expected = set_email_case(user, case)
    assert user.validate_rdap_relationship(rdap) is expected


def test_verified_unrelated_address_does_not_validate_primary(rdap_owner):
    user, rdap = rdap_owner
    EmailAddress.objects.create(user=user, email=user.email, primary=True)
    EmailAddress.objects.create(user=user, email="unrelated@example.net", verified=True)
    assert not user.validate_rdap_relationship(rdap)


@pytest.mark.parametrize("path", ["new", "unowned", "undelete"])
@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "primary-unverified",
        "primary-verified",
        "secondary-unverified",
        "secondary-verified",
    ],
)
def test_affiliation_auto_approval_requires_verified_match(rdap_owner, path, case):
    user, _ = rdap_owner
    expected = set_email_case(user, case)
    network = None
    if path != "new":
        org = Organization.objects.create(name="Existing RDAP org", status="ok")
        network = Network.objects.create(
            org=org,
            name="Existing RDAP network",
            asn=63311,
            status="deleted" if path == "undelete" else "ok",
        )
        old_org_id = org.pk
    request = RequestFactory().post("/affiliate-to-org", {"asn": 63311})
    request.user = user
    mock_csrf_session(request)
    response = view_affiliate_to_org(request)
    assert response.status_code == 200
    network = Network.objects.get(asn=63311)
    if expected:
        assert user.is_org_admin(network.org)
        assert not user.affiliation_requests.exists()
        assert network.status == "ok"
        if path == "undelete":
            assert network.org_id != old_org_id
    else:
        assert not user.groups.filter(name__endswith=".admin").exists()
        assert user.affiliation_requests.filter(
            status="denied" if path == "undelete" else "pending"
        ).exists()
        if path == "undelete":
            assert network.status == "deleted"
            assert network.org_id == old_org_id


def test_verified_match_does_not_bypass_existing_org_admin(rdap_owner):
    user, _ = rdap_owner
    set_email_case(user, "primary-verified")
    org = Organization.objects.create(name="Already owned", status="ok")
    owner = User.objects.create_user("existing-admin", "admin@example.net")
    org.admin_usergroup.user_set.add(owner)
    Network.objects.create(org=org, name="Owned network", asn=63311, status="ok")
    affiliation = UserOrgAffiliationRequest.objects.create(
        user=user, org=org, asn=63311
    )
    assert affiliation.status == "pending"
    assert not user.is_org_admin(org)
    assert not user.is_org_member(org)


def post_new_asn_affiliation(user):
    request = RequestFactory().post("/affiliate-to-org", {"asn": 63311})
    request.user = user
    mock_csrf_session(request)
    return view_affiliate_to_org(request)


@pytest.mark.parametrize("auto_approve", [False, True])
@pytest.mark.parametrize("org_name", ["20C, LLC", "20c, llc"])
def test_new_asn_rdap_name_match_respects_org_admins(
    rdap_owner, settings, mailoutbox, monkeypatch, org_name, auto_approve
):
    settings.MAIL_DEBUG = False
    monkeypatch.setattr(pdb_settings, "AUTO_APPROVE_AFFILIATION", auto_approve)
    user, _ = rdap_owner
    set_email_case(user, "primary-verified")
    # matched by RDAP registrant name ("20C, LLC"), case-insensitively by the
    # db collation, and already managed
    org = Organization.objects.create(name=org_name, status="ok")
    owner = User.objects.create_user("existing-admin", "admin@example.net")
    org.admin_usergroup.user_set.add(owner)

    assert post_new_asn_affiliation(user).status_code == 200

    affiliation = user.affiliation_requests.get()
    assert affiliation.status == "pending"
    assert affiliation.org_id == org.pk
    assert not user.is_org_member(org)
    assert not user.is_org_admin(org)
    assert [m.to for m in mailoutbox] == [[owner.email]]
    # the network itself is created from RDAP data by design
    assert Network.objects.get(asn=63311).org_id == org.pk


def test_new_asn_rdap_name_match_enforces_restrict_user_emails(rdap_owner):
    user, _ = rdap_owner
    set_email_case(user, "primary-verified")
    org = Organization.objects.create(
        name="20C, LLC",
        status="ok",
        restrict_user_emails=True,
        email_domains="example.net",
    )
    owner = User.objects.create_user("existing-admin", "admin@example.net")
    org.admin_usergroup.user_set.add(owner)

    assert post_new_asn_affiliation(user).status_code == 200

    assert user.affiliation_requests.get().status == "denied"
    assert not user.is_org_member(org)


def test_new_asn_rdap_name_match_existing_member_is_approved(
    rdap_owner, settings, mailoutbox
):
    settings.MAIL_DEBUG = False
    user, _ = rdap_owner
    set_email_case(user, "primary-verified")
    org = Organization.objects.create(name="20C, LLC", status="ok")
    owner = User.objects.create_user("existing-admin", "admin@example.net")
    org.admin_usergroup.user_set.add(owner)
    org.usergroup.user_set.add(user)

    assert post_new_asn_affiliation(user).status_code == 200

    assert user.is_org_member(org)
    assert not user.is_org_admin(org)
    assert not user.affiliation_requests.exists()
    assert not DeskProTicket.objects.exists()
    assert not mailoutbox


def test_new_asn_rdap_name_match_unowned_org_still_auto_approves(rdap_owner):
    user, _ = rdap_owner
    set_email_case(user, "primary-verified")
    org = Organization.objects.create(name="20C, LLC", status="ok")

    assert post_new_asn_affiliation(user).status_code == 200

    assert user.is_org_admin(org)
    assert not user.affiliation_requests.exists()


def test_rdap_audit_is_read_only_and_preserves_uncertainty(rdap_owner):
    user, _ = rdap_owner
    set_email_case(user, "primary-verified")
    org = Organization.objects.create(name="Audit org", status="ok")
    Network.objects.create(org=org, name="Audit network", asn=63311, status="ok")
    UserOrgAffiliationRequest.objects.create(user=user, org=org, asn=63311)
    assert user.is_org_admin(org)
    other = User.objects.create_user("untracked-admin", "untracked@example.net")
    org.admin_usergroup.user_set.add(other)
    # Verification now cannot tell an auditor whether it was verified at approval.
    user.emailaddress_set.update(verified=False)
    output = io.StringIO()
    queries = []

    def record(execute, sql, params, many, context):
        queries.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(record):
        call_command("pdb_rdap_ownership_audit", stdout=output)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[0]["approval_method"] == "not_recorded"
    assert rows[0]["email_verification_at_approval"] == "not_recorded"
    approval = next(row for row in rows if row["type"] == "approval_snapshot")
    assert approval["org_id"] == org.pk
    assert approval["user_id"] == user.pk
    assert approval["user_is_org_admin_now"]
    assert not approval["user_has_verified_email_now"]
    assert Version.objects.filter(pk=approval["version_id"]).exists()
    untracked = next(
        row
        for row in rows
        if row["type"] == "current_admin" and row["user_id"] == other.pk
    )
    assert not untracked["has_retained_approval_snapshot"]
    assert rows[-1]["current_admin_memberships"] == 2
    assert rows[-1]["current_admins_without_approval_snapshot"] == 1
    assert queries
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in queries)
    assert user.email not in output.getvalue()
    assert org.name not in output.getvalue()


@pytest.fixture
def org_key_client(rdap_owner):
    user, rdap = rdap_owner
    org = Organization.objects.create(name="Org key RDAP org", status="ok")
    org_key, secret = OrganizationAPIKey.objects.create_key(
        org=org, name="Automation", email="neteng@20c.com"
    )
    org_key.grainy_permissions.add_permission(org.grainy_namespace, PERM_CRUD)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + secret)
    return client, org, org_key, user


def post_network(client, org):
    return client.post(
        "/api/net",
        {
            "org_id": org.pk,
            "asn": 63311,
            "name": "Org key RDAP network",
            "website": "https://www.example.com",
        },
        format="json",
    )


@pytest.mark.parametrize(
    "case,expected",
    [
        ("no-address", False),
        ("unverified-admin", False),
        ("verified-member", False),
        ("verified-inactive-admin", False),
        ("verified-other-org-admin", False),
        ("verified-admin", True),
    ],
)
def test_org_key_rdap_requires_verified_admin_email(org_key_client, case, expected):
    client, org, org_key, user = org_key_client
    if case != "no-address":
        EmailAddress.objects.create(
            user=user, email="NetEng@20c.com", verified=case != "unverified-admin"
        )
    if case == "verified-member":
        org.usergroup.user_set.add(user)
    elif case == "verified-other-org-admin":
        other = Organization.objects.create(name="Other org", status="ok")
        other.admin_usergroup.user_set.add(user)
    elif case != "no-address":
        org.admin_usergroup.user_set.add(user)
    if case == "verified-inactive-admin":
        user.is_active = False
        user.save()

    response = post_network(client, org)

    if expected:
        assert response.status_code == 201, response.content
        assert Network.objects.get(asn=63311).status == "ok"
    else:
        assert response.status_code == 400, response.content
        assert not Network.objects.filter(asn=63311).exists()
        assert "verified email address of an administrator" in str(response.json())


@pytest.mark.parametrize("email", ["néteng@20c.com", "neteng@20ç.com"])
def test_org_key_rdap_ignores_lookalike_admin_email(org_key_client, email):
    client, org, org_key, user = org_key_client
    # a different mailbox that accent-insensitive collations treat as equal
    EmailAddress.objects.create(user=user, email=email, verified=True)
    org.admin_usergroup.user_set.add(user)

    response = post_network(client, org)

    assert response.status_code == 400, response.content
    assert not Network.objects.filter(asn=63311).exists()


def test_org_key_email_update_does_not_rearm_rdap(org_key_client):
    client, org, org_key, user = org_key_client
    EmailAddress.objects.create(user=user, email="admin@example.net", verified=True)
    org.admin_usergroup.user_set.add(user)
    org_key.email = "admin@example.net"
    org_key.save()

    # an org admin points the key at the RDAP contact
    request = RequestFactory().post(
        "/org_admin/manage_key/update",
        {
            "org_id": org.pk,
            "prefix": org_key.prefix,
            "name": org_key.name,
            "email": "neteng@20c.com",
        },
    )
    request.user = user
    assert manage_key_update(request).status_code == 200
    org_key.refresh_from_db()
    assert org_key.email == "neteng@20c.com"

    response = post_network(client, org)

    assert response.status_code == 400, response.content
    assert not Network.objects.filter(asn=63311).exists()
