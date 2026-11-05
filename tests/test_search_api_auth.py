"""
/api/search accepts only API key credentials (#513).

Bearer tokens are refused for every /api/ path by PDBPermissionMiddleware;
any other Authorization scheme is answered like a request without a key.
"""

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from peeringdb_server import rest
from peeringdb_server.middleware import ERR_BEARER_API
from peeringdb_server.models import (
    Organization,
    OrganizationAPIKey,
    User,
    UserAPIKey,
)

pytestmark = pytest.mark.django_db

SEARCH = "/api/search?q=search-auth"

# bad keys are refused by PDBPermissionMiddleware before the view runs
INVALID_KEY_STATUS = 401


@pytest.fixture
def search_keys(db, settings, monkeypatch):
    # the search itself needs elasticsearch, which these checks do not
    monkeypatch.setattr(rest, "perform_search", lambda *args, **kwargs: {"net": []})

    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    settings.GUEST_GROUP_ID = guest_group.pk
    settings.USER_GROUP_ID = user_group.pk

    user = User.objects.create_user(username="search-auth-user", password="x" * 16)
    user.groups.add(user_group)
    _, user_key = UserAPIKey.objects.create_key(user=user, name="search auth key")

    org = Organization.objects.create(name="Search auth org", status="ok")
    org.admin_usergroup.user_set.add(user)
    _, org_key = OrganizationAPIKey.objects.create_key(
        name="search auth org key", org=org, email="search-auth@example.invalid"
    )
    return {"user": user_key, "org": org_key}


def search(authorization=None):
    headers = {}
    if authorization is not None:
        headers["HTTP_AUTHORIZATION"] = authorization
    return APIClient().get(SEARCH, **headers)


def test_search_without_key(search_keys):
    resp = search()
    assert resp.status_code == 401
    assert "No API key provided" in resp.json()["error"]


@pytest.mark.parametrize(
    "authorization",
    ("Token not-a-key", "Foo bar", "Token {org}"),
)
def test_search_rejects_other_schemes(search_keys, authorization):
    resp = search(authorization.format(**search_keys))
    assert resp.status_code == 401, resp.content
    assert resp.json() == search().json()


@pytest.mark.parametrize("authorization", ("Bearer not-a-key", "Bearer {user}"))
def test_search_rejects_bearer(search_keys, authorization):
    resp = search(authorization.format(**search_keys))
    assert resp.status_code == 401, resp.content
    assert resp.json()["meta"]["error"] == ERR_BEARER_API


def test_search_rejects_invalid_key(search_keys):
    resp = search("Api-Key not-a-key")
    assert resp.status_code == INVALID_KEY_STATUS, resp.content
    assert resp.json()["meta"]["error"] == "Invalid API key"


def test_search_rejects_inactive_key(search_keys):
    api_key = UserAPIKey.objects.get_from_key(search_keys["user"])
    api_key.status = "inactive"
    api_key.save()
    resp = search(f"Api-Key {search_keys['user']}")
    assert resp.status_code == INVALID_KEY_STATUS, resp.content
    assert resp.json()["meta"]["error"] == "Inactive API key"


@pytest.mark.parametrize("key", ("user", "org"))
@pytest.mark.parametrize("scheme", ("Api-Key", "api-key"))
def test_search_accepts_api_key(search_keys, key, scheme):
    resp = search(f"{scheme} {search_keys[key]}")
    assert resp.status_code == 200, resp.content
    assert resp.json() == {"net": []}
