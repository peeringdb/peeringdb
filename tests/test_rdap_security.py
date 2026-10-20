import io
import json
from pathlib import Path

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory
from reversion.models import Version

from peeringdb_server import settings as pdb_settings
from peeringdb_server.inet import RdapAsn, RdapLookup
from peeringdb_server.models import (
    Network,
    Organization,
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
