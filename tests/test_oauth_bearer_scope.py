"""
OAuth access tokens are only accepted by /profile/v1 and the /oauth2/
endpoints, and never act as a logged-in session elsewhere.
"""

import re
from datetime import timedelta

import pytest
from django.test import Client, RequestFactory
from django.utils import timezone
from oauth2_provider.models import AccessToken, Grant

from peeringdb_server.middleware import ERR_BEARER_API, get_auth_identity
from peeringdb_server.models import Organization, User, UserAPIKey

from .util import create_oauth_application, reset_group_ids

pytestmark = pytest.mark.django_db

TOKEN = "bearer-scope-token"
BEARER = f"Bearer {TOKEN}"


@pytest.fixture
def org_admin():
    reset_group_ids()
    user = User.objects.create_user(
        "bearer-scope", "bearer-scope@localhost", "bearer-scope-pw", status="ok"
    )
    org = Organization.objects.create(name="Bearer Scope Org", status="ok")
    org.admin_usergroup.user_set.add(user)
    # no application: authenticating a token needs none, see test_middleware
    AccessToken.objects.create(
        user=user,
        token=TOKEN,
        expires=timezone.now() + timedelta(hours=1),
        scope="openid profile",
    )
    return user, org


def login_page_csrf(client):
    """
    An anonymous visit to the login page establishes a session that holds a
    CSRF secret, and returns the matching token.
    """

    page = client.get("/account/login/").content.decode()
    assert "sessionid" in client.cookies
    return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)


def test_profile_scope_token_cannot_add_user_key(org_admin):
    user, _ = org_admin
    client = Client(enforce_csrf_checks=True)
    csrf = login_page_csrf(client)

    response = client.post(
        "/user_keys/add",
        {"name": "bearer", "readonly": "false"},
        HTTP_AUTHORIZATION=BEARER,
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert response.status_code in (302, 401, 403)
    assert not UserAPIKey.objects.filter(user=user).exists()


@pytest.mark.parametrize(
    "path",
    [
        "/org_admin/users",
        "/org_admin/user_permissions",
        "/org_admin/key_permissions",
    ],
)
def test_profile_scope_token_cannot_read_org_admin_views(org_admin, path):
    user, org = org_admin
    response = Client().get(path, {"org_id": org.id}, HTTP_AUTHORIZATION=BEARER)
    assert response.status_code != 200
    assert user.email not in response.content.decode()


def test_profile_scope_token_cannot_affiliate(org_admin):
    client = Client(enforce_csrf_checks=True)
    csrf = login_page_csrf(client)

    response = client.post(
        "/affiliate-to-org",
        {"org": "Other Org"},
        HTTP_AUTHORIZATION=BEARER,
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert response.status_code in (302, 401, 403)


@pytest.mark.parametrize(
    "path", ["/oauth2/applications/", "/oauth2/authorized_tokens/"]
)
def test_profile_scope_token_cannot_manage_oauth(org_admin, path):
    response = Client().get(path, HTTP_AUTHORIZATION=BEARER)
    assert response.status_code == 302
    assert "/account/login/" in response.url


def test_profile_scope_token_cannot_authorize(org_admin):
    user, _ = org_admin
    create_oauth_application(user, "bearer-scope-client", "bearer-scope-secret")
    client = Client(enforce_csrf_checks=True)
    csrf = login_page_csrf(client)
    params = {
        "client_id": "bearer-scope-client",
        "response_type": "code",
        "redirect_uri": "https://example.com",
        "scope": "openid profile email networks",
    }

    response = client.get("/oauth2/authorize/", params, HTTP_AUTHORIZATION=BEARER)
    assert response.status_code == 302
    assert "/account/login/" in response.url

    response = client.post(
        "/oauth2/authorize/",
        {**params, "allow": "Authorize"},
        HTTP_AUTHORIZATION=BEARER,
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 302
    assert "/account/login/" in response.url
    assert not Grant.objects.exists()


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_refuses_bearer_token(org_admin, method):
    response = getattr(Client(), method)("/api/net", HTTP_AUTHORIZATION=BEARER)
    assert response.status_code == 401
    assert response.json()["meta"]["error"] == ERR_BEARER_API


def test_profile_v1_accepts_bearer_token(org_admin):
    user, _ = org_admin
    response = Client().get("/profile/v1", HTTP_AUTHORIZATION=BEARER)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    # the token has no email scope
    assert "email" not in data


def test_profile_v1_requires_profile_scope(org_admin):
    user, _ = org_admin
    AccessToken.objects.create(
        user=user,
        token="bearer-scope-email-only",
        expires=timezone.now() + timedelta(hours=1),
        scope="email",
    )
    response = Client().get(
        "/profile/v1", HTTP_AUTHORIZATION="Bearer bearer-scope-email-only"
    )
    assert response.status_code == 403


def test_userinfo_accepts_bearer_token(org_admin):
    user, _ = org_admin
    response = Client().get("/oauth2/userinfo/", HTTP_AUTHORIZATION=BEARER)
    assert response.status_code == 200
    assert response.json()["id"] == user.id


def test_responses_vary_on_authorization(org_admin):
    response = Client().get("/profile/v1", HTTP_AUTHORIZATION=BEARER)
    vary = {v.strip().lower() for v in response.get("Vary", "").split(",")}
    assert "authorization" in vary


@pytest.mark.parametrize(
    "header",
    [
        BEARER,
        f"bearer\t{TOKEN}",
        f" Bearer {TOKEN}",
        f"BEARER  {TOKEN} ",
        # rejected by every parser, the token still must not show
        f"Bearer {TOKEN} extra",
        f"Bearer {TOKEN}, Bearer {TOKEN}",
        f"Token {TOKEN}",
        TOKEN,
    ],
)
def test_negative_cache_identity_omits_token(header):
    request = RequestFactory().get("/api/net", HTTP_AUTHORIZATION=header)
    identity = get_auth_identity(request)
    assert identity.startswith("hashed__")
    assert TOKEN not in identity


def test_negative_cache_identity_keeps_public_parts():
    for header, identity in (
        ("Basic Ym9iOnNlY3JldA==", "user__bob"),
        ("Api-Key abcd1234.secret", "key__abcd1234"),
    ):
        request = RequestFactory().get("/api/net", HTTP_AUTHORIZATION=header)
        assert get_auth_identity(request) == identity
