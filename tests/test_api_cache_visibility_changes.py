"""
Visibility changes after the api cache was generated (#523).

Unfiltered lists are answered from cache files that carry each row's
visibility as of generation. Contacts and exchange LAN feed URLs hidden or
deleted afterwards must not be served from them until the next regeneration.
"""

import json
import os

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django_grainy.models import GroupPermission
from rest_framework.test import APIClient

from peeringdb_server.api_cache import CONTACT_CACHE_DEPTHS, IXLAN_CACHE_DEPTHS
from peeringdb_server.management.commands.pdb_api_cache import VIEWSETS
from peeringdb_server.models import (
    InternetExchange,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
    User,
)

pytestmark = pytest.mark.django_db

FEED_URL = "https://example.invalid/members.json"


@pytest.fixture
def cache_data(db, settings, tmp_path):
    settings.API_CACHE_ENABLED = False
    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    settings.GUEST_GROUP_ID = guest_group.pk
    settings.USER_GROUP_ID = user_group.pk
    for group, visible in ((guest_group, "public"), (user_group, "users")):
        GroupPermission.objects.create(
            group=group, namespace="peeringdb.organization", permission=0x01
        )
        GroupPermission.objects.create(
            group=group,
            namespace=f"peeringdb.organization.*.network.*.poc_set.{visible}",
            permission=0x01,
        )
        GroupPermission.objects.create(
            group=group,
            namespace=(
                "peeringdb.organization.*.internetexchange.*"
                f".ixf_ixp_member_list_url.{visible}"
            ),
            permission=0x01,
        )

    org = Organization.objects.create(name="Cache visibility org", status="ok")
    net = Network.objects.create(
        name="Cache visibility net", asn=63523, org=org, status="ok"
    )

    def poc(visible, slug):
        return NetworkContact.objects.create(
            network=net,
            visible=visible,
            role="Policy",
            status="ok",
            name=f"Contact {slug}",
            phone="+12065550101",
            email=f"{slug}@example.invalid",
        )

    pocs = {
        "unchanged": poc("Public", "unchanged"),
        "to_private": poc("Public", "to-private"),
        "to_users": poc("Public", "to-users"),
        "to_deleted": poc("Public", "to-deleted"),
        "to_public": poc("Private", "to-public"),
    }

    ix = InternetExchange.objects.create(
        name="Cache visibility IX", org=org, status="ok"
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = FEED_URL
    ixlan.ixf_ixp_member_list_url_visible = "Public"
    ixlan.save()

    # nests the network, and its contact ids, in ixlan-3
    NetworkIXLan.objects.create(
        network=net,
        ixlan=ixlan,
        asn=net.asn,
        speed=1000,
        ipaddr4="195.69.144.23",
        ipaddr6="2001:7f8:1::a506:3523:1",
        status="ok",
    )

    user = User.objects.create(username="cache-visibility-user")
    user.groups.add(user_group)
    User.objects.create(username="cache-visibility-admin", is_superuser=True)

    settings.API_CACHE_ROOT = str(tmp_path)
    settings.API_CACHE_LOG = str(tmp_path / "api-cache.log")
    call_command("pdb_api_cache", output_dir=str(tmp_path))
    settings.API_CACHE_ENABLED = True

    return {"org": org, "net": net, "ix": ix, "pocs": pocs, "user": user}


def change_after_generation(data):
    pocs = data["pocs"]
    for key, visible in (
        ("to_private", "Private"),
        ("to_users", "Users"),
        ("to_public", "Public"),
    ):
        pocs[key].visible = visible
        pocs[key].save()
    pocs["to_deleted"].delete()

    # the cached row still holds the address from before it was made public
    pocs["to_public"].email = "to-public-new@example.invalid"
    pocs["to_public"].save()

    ixlan = data["ix"].ixlan
    ixlan.ixf_ixp_member_list_url_visible = "Private"
    ixlan.save()


def cached_rows(client, url):
    resp = client.get(url)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    # only cached responses carry meta.generated
    assert "generated" in body["meta"], url
    return body["data"]


def poc_ids(data, *keys):
    return sorted(data["pocs"][key].id for key in keys)


def net_row(rows, net):
    (row,) = [row for row in rows if row["id"] == net.id]
    return row


@pytest.mark.parametrize("depth", (0, 2))
def test_poc_list_drops_hidden_and_deleted_contacts(cache_data, depth):
    change_after_generation(cache_data)
    rows = cached_rows(APIClient(), f"/api/poc?depth={depth}")
    assert sorted(row["id"] for row in rows) == poc_ids(cache_data, "unchanged")
    assert {row["visible"] for row in rows} == {"Public"}


def test_poc_list_follows_users_visibility(cache_data):
    change_after_generation(cache_data)
    client = APIClient()
    client.force_authenticate(user=cache_data["user"])
    rows = cached_rows(client, "/api/poc")
    assert sorted(row["id"] for row in rows) == poc_ids(
        cache_data, "unchanged", "to_users"
    )
    (to_users,) = [
        row for row in rows if row["id"] == cache_data["pocs"]["to_users"].id
    ]
    assert to_users["visible"] == "Users"


def test_net_depth_2_poc_set_drops_hidden_and_deleted_contacts(cache_data):
    change_after_generation(cache_data)
    row = net_row(cached_rows(APIClient(), "/api/net?depth=2"), cache_data["net"])
    assert sorted(poc["id"] for poc in row["poc_set"]) == poc_ids(
        cache_data, "unchanged"
    )


def test_poc_set_id_lists_drop_hidden_and_deleted_contacts(cache_data):
    change_after_generation(cache_data)
    client = APIClient()
    net = cache_data["net"]

    # id lists are public-only at generation (#513); a contact made public
    # afterwards appears with the next regeneration
    expected = poc_ids(cache_data, "unchanged")
    assert (
        sorted(net_row(cached_rows(client, "/api/net?depth=1"), net)["poc_set"])
        == expected
    )

    (org,) = [
        row
        for row in cached_rows(client, "/api/org?depth=3")
        if row["id"] == cache_data["org"].id
    ]
    assert sorted(net_row(org["net_set"], net)["poc_set"]) == expected

    (ixlan,) = [
        row
        for row in cached_rows(client, "/api/ixlan?depth=3")
        if row["id"] == cache_data["ix"].ixlan.id
    ]
    assert sorted(net_row(ixlan["net_set"], net)["poc_set"]) == expected


def test_contact_made_public_is_not_widened_from_cache(cache_data):
    """
    The cached row predates the change and was rendered with every field,
    so it stays hidden until the next regeneration.
    """
    change_after_generation(cache_data)
    to_public = cache_data["pocs"]["to_public"]

    for url in ("/api/poc", "/api/net?depth=2"):
        assert b"to-public@example.invalid" not in APIClient().get(url).content

    client = APIClient()
    client.force_authenticate(user=cache_data["user"])
    rows = cached_rows(client, "/api/poc")
    assert to_public.id not in [row["id"] for row in rows]


def test_feed_url_made_public_is_not_widened_from_cache(cache_data, tmp_path):
    ixlan = cache_data["ix"].ixlan
    ixlan.ixf_ixp_member_list_url = "https://example.invalid/private-members.json"
    ixlan.ixf_ixp_member_list_url_visible = "Private"
    ixlan.save()
    call_command("pdb_api_cache", only="ix,ixlan", output_dir=str(tmp_path))

    ixlan.ixf_ixp_member_list_url = FEED_URL
    ixlan.ixf_ixp_member_list_url_visible = "Public"
    ixlan.save()

    for url in ("/api/ixlan", "/api/ix?depth=2"):
        resp = APIClient().get(url)
        assert resp.status_code == 200, resp.content
        assert b"private-members" not in resp.content


@pytest.mark.parametrize("url", ("/api/ixlan", "/api/ixlan?depth=2", "/api/ix?depth=2"))
def test_hidden_feed_url_is_not_served(cache_data, url):
    ixlan_id = cache_data["ix"].ixlan.id
    client = APIClient()

    def ixlan_row():
        rows = cached_rows(client, url)
        if url.startswith("/api/ix?"):
            (ix,) = [row for row in rows if row["id"] == cache_data["ix"].id]
            rows = ix["ixlan_set"]
        (row,) = [row for row in rows if row["id"] == ixlan_id]
        return row

    assert ixlan_row()["ixf_ixp_member_list_url"] == FEED_URL

    change_after_generation(cache_data)
    row = ixlan_row()
    assert "ixf_ixp_member_list_url" not in row
    assert row["ixf_ixp_member_list_url_visible"] == "Private"


def test_unchanged_cache_is_served_as_generated(cache_data):
    rows = cached_rows(APIClient(), "/api/poc")
    assert sorted(row["id"] for row in rows) == poc_ids(
        cache_data, "unchanged", "to_private", "to_users", "to_deleted"
    )


def test_future_generation_date_uses_file_time(cache_data, settings, tmp_path):
    # --date records a generation time after the actual read
    call_command(
        "pdb_api_cache",
        only="poc",
        depths="0",
        date="20991231",
        output_dir=str(tmp_path),
    )
    change_after_generation(cache_data)
    rows = cached_rows(APIClient(), "/api/poc")
    assert sorted(row["id"] for row in rows) == poc_ids(cache_data, "unchanged")


def test_only_mapped_cache_files_embed_contacts_or_ixlans(cache_data, tmp_path):
    """
    Contacts and exchange LANs appear only in the files whose tag and depth
    the loader re-checks against the database.
    """

    def embeds(node, match):
        if isinstance(node, list):
            return any(embeds(item, match) for item in node)
        if isinstance(node, dict):
            return match(node) or any(embeds(v, match) for v in node.values())
        return False

    def is_contact(node):
        return ".poc_set." in node.get("_grainy", "") or bool(node.get("poc_set"))

    def is_ixlan(node):
        return "ixf_ixp_member_list_url_visible" in node

    for name in sorted(os.listdir(tmp_path)):
        if not name.endswith(".json"):
            continue
        tag, depth = name[: -len(".json")].rsplit("-", 1)
        with open(tmp_path / name) as fh:
            rows = json.load(fh)["data"]
        for mapping, match in (
            (CONTACT_CACHE_DEPTHS, is_contact),
            (IXLAN_CACHE_DEPTHS, is_ixlan),
        ):
            if embeds(rows, match):
                assert int(depth) >= mapping.get(tag, 4), name


@pytest.mark.parametrize("tag", VIEWSETS)
def test_no_cached_list_serves_hidden_contacts_or_feed_urls(cache_data, tag):
    change_after_generation(cache_data)
    hidden = [
        b"to-private@example.invalid",
        b"to-users@example.invalid",
        b"to-deleted@example.invalid",
        b"to-public@example.invalid",
        FEED_URL.encode(),
    ]
    public_ids = set(poc_ids(cache_data, "unchanged"))

    def poc_id_lists(node):
        if isinstance(node, list):
            for item in node:
                yield from poc_id_lists(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key == "poc_set" and value and isinstance(value[0], int):
                    yield value
                else:
                    yield from poc_id_lists(value)

    for depth in range(4):
        url = f"/api/{tag}?depth={depth}"
        resp = APIClient().get(url)
        assert resp.status_code == 200, resp.content
        assert "generated" in resp.json()["meta"], url
        for value in hidden:
            assert value not in resp.content, (url, value)
        for ids in poc_id_lists(resp.json()["data"]):
            assert set(ids) <= public_ids, url
