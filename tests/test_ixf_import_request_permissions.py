"""
Who may request an IX-F import on POST /api/ix/{id}/request_ixf_import (#2072).

The request changes the exchange, so it needs update permission on it.
A granular update permission on the exchange is enough, create
permission alone is not. Granular permissions carry read as well, as the
org admin views always add it.

The route sets its own permission classes, so the write blocks of the
other API routes are tested here too.
"""

import base64
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone
from django_grainy.models import GroupPermission
from django_otp.plugins.otp_totp.models import TOTPDevice
from grainy.const import PERM_CREATE, PERM_READ, PERM_UPDATE
from rest_framework.test import APIClient

from peeringdb_server.models import (
    InternetExchange,
    IXLanPrefix,
    Organization,
    OrganizationAPIKey,
    User,
    UserAPIKey,
)

pytestmark = pytest.mark.django_db

PASSWORD = "ixf-request-password"


@pytest.fixture
def import_data(settings):
    settings.API_CACHE_ENABLED = False
    # basic auth is only accepted before the MFA hard start
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=10)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=20)
    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    settings.GUEST_GROUP_ID = guest_group.pk
    settings.USER_GROUP_ID = user_group.pk
    for group in (guest_group, user_group):
        GroupPermission.objects.create(
            group=group, namespace="peeringdb.organization", permission=PERM_READ
        )

    org = Organization.objects.create(name="IX-F request org", status="ok")
    ix = InternetExchange.objects.create(name="IX-F request IX", org=org, status="ok")
    other_ix = InternetExchange.objects.create(
        name="IX-F request other IX", org=org, status="ok"
    )
    for each, prefix in ((ix, "198.51.100.0/24"), (other_ix, "203.0.113.0/24")):
        IXLanPrefix.objects.create(
            ixlan=each.ixlan, status="ok", prefix=prefix, protocol="IPv4"
        )

    users = {}
    for name, perms in (
        ("updater", PERM_READ | PERM_UPDATE),
        ("creator", PERM_READ | PERM_CREATE),
        ("reader", None),
        ("admin", None),
        ("mfa", PERM_READ | PERM_UPDATE),
        ("deactivated", PERM_READ | PERM_UPDATE),
    ):
        user = User.objects.create(username=f"ixf-request-{name}")
        user.set_password(PASSWORD)
        user.save()
        user.groups.add(user_group)
        user.set_verified()
        if perms:
            user.grainy_permissions.add_permission(ix.grainy_namespace, perms)
        users[name] = user
    org.admin_usergroup.user_set.add(users["admin"])
    TOTPDevice.objects.create(user=users["mfa"], name="default")

    keys = {}
    for name, perms in (
        ("org_key_updater", PERM_READ | PERM_UPDATE),
        ("org_key_reader", None),
    ):
        org_api_key, key = OrganizationAPIKey.objects.create_key(
            org=org, name=name, email=f"{name}@example.invalid"
        )
        org_api_key.grainy_permissions.add_permission(org.grainy_namespace, PERM_READ)
        if perms:
            org_api_key.grainy_permissions.add_permission(ix.grainy_namespace, perms)
        keys[name] = key

    for name, user in (
        ("user_key_updater", users["updater"]),
        ("user_key_deactivated", users["deactivated"]),
    ):
        _, keys[name] = UserAPIKey.objects.create_key(user=user, name=name)

    # the key stays active, only its user is deactivated
    users["deactivated"].is_active = False
    users["deactivated"].save()

    return {"ix": ix, "other_ix": other_ix, "users": users, "keys": keys}


def client_for(data, caller):
    client = APIClient()
    if caller == "anonymous":
        return client
    if caller in data["keys"]:
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {data['keys'][caller]}")
    elif caller.startswith("basic_"):
        username = data["users"][caller.removeprefix("basic_")].username
        token = base64.b64encode(f"{username}:{PASSWORD}".encode()).decode()
        client.credentials(HTTP_AUTHORIZATION=f"Basic {token}")
    else:
        client.force_authenticate(user=data["users"][caller])
    return client


def request_import(client, ix):
    return client.post(f"/api/ix/{ix.id}/request_ixf_import", {}, format="json")


@pytest.mark.parametrize(
    "caller,requester",
    [
        ("updater", "updater"),
        ("admin", "admin"),
        ("basic_updater", "updater"),
        ("org_key_updater", None),
        # a user api key doesn't record its user as the requester yet, so
        # the requester isn't checked for it
        ("user_key_updater", "unchecked"),
    ],
)
def test_request_ixf_import_with_update_permission(import_data, caller, requester):
    ix = import_data["ix"]
    client = client_for(import_data, caller)

    resp = request_import(client, ix)
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"][0]["ixf_import_request_status"] == "queued"

    ix.refresh_from_db()
    assert ix.ixf_import_request is not None
    assert ix.ixf_import_request_status == "queued"
    if requester is None:
        assert ix.ixf_import_request_user is None
    elif requester != "unchecked":
        assert ix.ixf_import_request_user == import_data["users"][requester]

    # the throttle is reached, not a permission error
    assert request_import(client, ix).status_code == 429


@pytest.mark.parametrize(
    "caller,status_code",
    [
        ("creator", 403),
        ("reader", 403),
        # neither of DRF's authenticators knows an api key, so a refused
        # key or guest gets 401
        ("org_key_reader", 401),
        ("anonymous", 401),
        # refused by BasicAuthMFABlockWrite
        ("basic_mfa", 403),
        # refused by InactiveKeyBlock
        ("user_key_deactivated", 403),
    ],
)
def test_request_ixf_import_without_update_permission(import_data, caller, status_code):
    ix = import_data["ix"]

    resp = request_import(client_for(import_data, caller), ix)
    assert resp.status_code == status_code, resp.content

    ix.refresh_from_db()
    assert ix.ixf_import_request is None


def test_request_ixf_import_update_permission_is_per_exchange(import_data):
    other_ix = import_data["other_ix"]

    resp = request_import(client_for(import_data, "updater"), other_ix)
    assert resp.status_code == 403, resp.content

    other_ix.refresh_from_db()
    assert other_ix.ixf_import_request is None


def test_request_ixf_import_throttle_keys_on_client_address(import_data, settings):
    """
    A caller without a DRF user, like a user api key, is throttled per
    client address, the entry the trusted proxy appended to
    X-Forwarded-For (#531)
    """
    settings.NUM_PROXIES = 1
    ix = import_data["ix"]
    client = client_for(import_data, "user_key_updater")

    def request_from(xff):
        return client.post(
            f"/api/ix/{ix.id}/request_ixf_import",
            {},
            format="json",
            HTTP_X_FORWARDED_FOR=xff,
        )

    assert request_from("203.0.113.9").status_code == 200

    for xff in (
        "192.0.2.1, 203.0.113.9",
        "192.0.2.2, 203.0.113.9",
        "192.0.2.1, 192.0.2.77, 203.0.113.9",
    ):
        assert request_from(xff).status_code == 429, xff

    # another client address has its own slot
    assert request_from("203.0.113.10").status_code == 200
