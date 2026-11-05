"""
Contact ids in nested poc_set lists (#513).

Where poc_set is rendered as a list of ids, it lists only the contacts the
caller may see. The api cache is shared by every caller, so its id lists
carry public contacts only.
"""

import json

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django_grainy.models import GroupPermission
from grainy.const import PERM_READ
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Network,
    NetworkContact,
    Organization,
    OrganizationAPIKey,
    User,
    UserAPIKey,
)

pytestmark = pytest.mark.django_db

# contacts each caller may see, by fixture key
VISIBLE = {
    "guest": {"public"},
    "authenticated": {"public", "users"},
    "member": {"public", "users", "private"},
    # the member's own user key, and a read-only key of the network's org
    "member_key": {"public", "users", "private"},
    "org_key": {"public", "users", "private"},
}


@pytest.fixture
def contact_data(db, settings):
    settings.API_CACHE_ENABLED = False
    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    settings.GUEST_GROUP_ID = guest_group.pk
    settings.USER_GROUP_ID = user_group.pk
    for group in (guest_group, user_group):
        GroupPermission.objects.create(
            group=group, namespace="peeringdb.organization", permission=0x01
        )
    GroupPermission.objects.create(
        group=guest_group,
        namespace="peeringdb.organization.*.network.*.poc_set.public",
        permission=0x01,
    )
    GroupPermission.objects.create(
        group=user_group,
        namespace="peeringdb.organization.*.network.*.poc_set.users",
        permission=0x01,
    )

    org = Organization.objects.create(name="Contact ids org", status="ok")
    net = Network.objects.create(
        name="Contact ids net", asn=63461, org=org, status="ok"
    )

    def poc(visible, slug, status="ok"):
        return NetworkContact.objects.create(
            network=net,
            visible=visible,
            role="Technical",
            status=status,
            name=f"Contact {slug}",
            phone="+12065550101",
            email=f"{slug}@example.invalid",
        )

    pocs = {
        "public": poc("Public", "public"),
        "users": poc("Users", "users"),
        "private": poc("Private", "private"),
        "deleted": poc("Public", "deleted", status="deleted"),
    }

    user = User.objects.create(username="contact-ids-user")
    user.groups.add(user_group)
    member = User.objects.create(username="contact-ids-member")
    member.groups.add(user_group)
    org.usergroup.user_set.add(member)

    _, member_key = UserAPIKey.objects.create_key(user=member, name="member key")
    org_api_key, org_key = OrganizationAPIKey.objects.create_key(
        org=org, name="org key", email="contact-ids-org-key@example.invalid"
    )
    org_api_key.grainy_permissions.add_permission(org.grainy_namespace, PERM_READ)

    return {
        "org": org,
        "net": net,
        "pocs": pocs,
        "user": user,
        "member": member,
        "keys": {"member_key": member_key, "org_key": org_key},
    }


def api_client(data, caller):
    client = APIClient()
    if caller == "authenticated":
        client.force_authenticate(user=data["user"])
    elif caller == "member":
        client.force_authenticate(user=data["member"])
    elif caller in data["keys"]:
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {data['keys'][caller]}")
    return client


def expected_ids(data, caller):
    return sorted(data["pocs"][key].id for key in VISIBLE[caller])


@pytest.mark.parametrize("caller", VISIBLE)
@pytest.mark.parametrize("url", ("/api/net/{net}?depth=1", "/api/net?depth=1&id={net}"))
def test_poc_set_ids_follow_visibility(contact_data, caller, url):
    resp = api_client(contact_data, caller).get(url.format(net=contact_data["net"].id))
    assert resp.status_code == 200, resp.content
    assert sorted(resp.json()["data"][0]["poc_set"]) == expected_ids(
        contact_data, caller
    )


@pytest.mark.parametrize("caller", VISIBLE)
def test_org_net_set_poc_set_ids_follow_visibility(contact_data, caller):
    org = contact_data["org"]
    resp = api_client(contact_data, caller).get(f"/api/org/{org.id}?depth=3")
    assert resp.status_code == 200, resp.content
    (net,) = resp.json()["data"][0]["net_set"]
    assert all(isinstance(poc, int) for poc in net["poc_set"])
    assert sorted(net["poc_set"]) == expected_ids(contact_data, caller)


@pytest.mark.parametrize("caller", VISIBLE)
def test_poc_set_objects_follow_visibility(contact_data, caller):
    net = contact_data["net"]
    resp = api_client(contact_data, caller).get(f"/api/net/{net.id}?depth=2")
    assert resp.status_code == 200, resp.content
    pocs = resp.json()["data"][0]["poc_set"]
    assert all(isinstance(poc, dict) for poc in pocs)
    assert sorted(poc["id"] for poc in pocs) == expected_ids(contact_data, caller)


def test_api_cache_poc_set_ids_public_only(contact_data, settings, tmp_path):
    User.objects.create(username="contact-ids-admin", is_superuser=True)
    settings.API_CACHE_LOG = str(tmp_path / "api-cache.log")
    call_command("pdb_api_cache", only="net", depths="1", output_dir=str(tmp_path))

    with open(tmp_path / "net-1.json") as fh:
        rows = json.load(fh)["data"]
    (row,) = [row for row in rows if row["id"] == contact_data["net"].id]
    assert row["poc_set"] == [contact_data["pocs"]["public"].id]


@pytest.fixture
def served_cache(contact_data, settings, tmp_path):
    User.objects.create(username="contact-ids-admin", is_superuser=True)
    settings.API_CACHE_LOG = str(tmp_path / "api-cache.log")
    settings.API_CACHE_ROOT = str(tmp_path)
    call_command("pdb_api_cache", only="net", depths="1,2", output_dir=str(tmp_path))
    settings.API_CACHE_ENABLED = True
    return contact_data


def net_row(resp, net):
    assert resp.status_code == 200, resp.content
    (row,) = [row for row in resp.json()["data"] if row["id"] == net.id]
    return row


@pytest.mark.parametrize("caller", VISIBLE)
def test_served_cache_poc_set_ids_public_only(served_cache, caller):
    net = served_cache["net"]
    client = api_client(served_cache, caller)
    public = [served_cache["pocs"]["public"].id]

    # unfiltered depth>0 lists are answered from the cache file
    assert net_row(client.get("/api/net?depth=1"), net)["poc_set"] == public

    # a filtered request is not, and lists what the caller may see
    uncached = net_row(client.get(f"/api/net?depth=1&id={net.id}"), net)
    assert sorted(uncached["poc_set"]) == expected_ids(served_cache, caller)


@pytest.mark.parametrize("caller", VISIBLE)
def test_served_cache_poc_set_objects_follow_visibility(served_cache, caller):
    net = served_cache["net"]
    row = net_row(api_client(served_cache, caller).get("/api/net?depth=2"), net)
    assert sorted(poc["id"] for poc in row["poc_set"]) == expected_ids(
        served_cache, caller
    )
