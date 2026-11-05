"""
Tests for the refused resource owner password credentials grant (#519).

The token endpoint refuses the password grant without checking the
credentials, tokens of applications registered with it are refused, the
application form no longer offers it and the server metadata no longer
advertises it.
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import authenticate
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, RefreshToken
from oauth2_provider.settings import oauth2_settings

from mainsite.oauth2.validators import OIDCValidator
from peeringdb_server.models import OAuthApplication, Organization, User
from tests.util import reset_group_ids

pytestmark = pytest.mark.django_db

CLIENT_ID = "client_id_password"
CLIENT_SECRET = "client_secret_password"
REDIRECT_URI = "https://example.com"
USERNAME = "owner"
PASSWORD = "owner-password"


@pytest.fixture
def pdb_app_model():
    previous = oauth2_settings.APPLICATION_MODEL
    oauth2_settings.APPLICATION_MODEL = "peeringdb_server.OAuthApplication"
    yield
    oauth2_settings.APPLICATION_MODEL = previous


@pytest.fixture
def org_admin():
    reset_group_ids()
    user = User.objects.create_user(USERNAME, "owner@example.com", PASSWORD)
    org = Organization.objects.create(name="Test Org 001", status="ok")
    org.admin_usergroup.user_set.add(user)
    return user, org


def app_fields(**kwargs):
    fields = {
        "name": "Password app",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": REDIRECT_URI,
        "authorization_grant_type": Application.GRANT_PASSWORD,
        "client_type": Application.CLIENT_CONFIDENTIAL,
        "algorithm": Application.RS256_ALGORITHM,
    }
    fields.update(kwargs)
    return fields


def create_dual_app(**kwargs):
    # tokens reference oauth2_provider.Application in the test settings, so the
    # app has to exist in both tables with the same id (see test_oauth2_views)
    app = Application.objects.create(**app_fields(**kwargs))
    OAuthApplication.objects.create(id=app.id, **app_fields(**kwargs))
    return app


def form_data(**kwargs):
    data = {
        "name": "Form app",
        "client_id": "client_id_form",
        "client_secret": "client_secret_form",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": REDIRECT_URI,
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "RS256",
    }
    data.update(kwargs)
    return data


def password_token_request(password):
    return Client().post(
        reverse("oauth2_provider:token"),
        {
            "grant_type": "password",
            "username": USERNAME,
            "password": password,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )


# token endpoint


@pytest.mark.parametrize(
    "grant_type",
    [Application.GRANT_PASSWORD, Application.GRANT_AUTHORIZATION_CODE],
)
def test_token_password_grant_refused(org_admin, grant_type):
    user, _ = org_admin
    create_dual_app(user=user, authorization_grant_type=grant_type)

    with mock.patch(
        "oauth2_provider.oauth2_validators.authenticate", wraps=authenticate
    ) as spy:
        right = password_token_request(PASSWORD)
        wrong = password_token_request("wrong-password")

    # the credentials are never checked, so the response can't tell them apart
    spy.assert_not_called()
    for resp in (right, wrong):
        assert resp.status_code == 400
        assert resp["Content-Type"] == "application/json"
        assert resp["Cache-Control"] == "no-store"
        assert resp.json()["error"] == "unsupported_grant_type"
    assert right.json() == wrong.json()
    assert not AccessToken.objects.exists()


def test_validate_grant_type_refuses_password(org_admin):
    user, _ = org_admin
    app = Application.objects.create(
        user=user,
        **app_fields(
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        ),
    )
    password_app = Application.objects.create(
        user=user, **app_fields(client_id="client_id_password_2")
    )
    validator = OIDCValidator()

    request = mock.Mock(client=password_app)
    assert not validator.validate_grant_type(
        password_app.client_id, "password", password_app, request
    )

    request = mock.Mock(client=app)
    assert validator.validate_grant_type(
        app.client_id, "authorization_code", app, request
    )


# tokens issued before the grant was refused

GRANT_TYPES = pytest.mark.parametrize(
    "grant_type,refused",
    [
        (Application.GRANT_PASSWORD, True),
        (Application.GRANT_AUTHORIZATION_CODE, False),
    ],
    ids=["password", "authorization_code"],
)


def issue_tokens(user, app):
    access = AccessToken.objects.create(
        user=user,
        application=app,
        token="access_password",
        expires=timezone.now() + timedelta(hours=1),
        scope="openid profile",
    )
    refresh = RefreshToken.objects.create(
        user=user, application=app, token="refresh_password", access_token=access
    )
    return access, refresh


@GRANT_TYPES
def test_refresh_password_grant_app_refused(org_admin, grant_type, refused):
    user, _ = org_admin
    app = create_dual_app(user=user, authorization_grant_type=grant_type)
    _, refresh = issue_tokens(user, app)

    resp = Client().post(
        reverse("oauth2_provider:token"),
        {
            "grant_type": "refresh_token",
            "refresh_token": "refresh_password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )

    refresh.refresh_from_db()
    if refused:
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"
        assert refresh.revoked is None
        assert AccessToken.objects.count() == 1
    else:
        assert resp.status_code == 200
        assert refresh.revoked is not None


@GRANT_TYPES
@pytest.mark.parametrize("path", ["/profile/v1", "/oauth2/userinfo/"])
def test_bearer_password_grant_app_refused(org_admin, grant_type, refused, path):
    user, _ = org_admin
    app = create_dual_app(user=user, authorization_grant_type=grant_type)
    issue_tokens(user, app)

    resp = Client().get(path, HTTP_AUTHORIZATION="Bearer access_password")

    if refused:
        unknown = Client().get(path, HTTP_AUTHORIZATION="Bearer access_unknown")
        assert resp.status_code in (401, 403)
        assert resp.status_code == unknown.status_code
    else:
        assert resp.status_code == 200
        assert resp.json()["id"] == user.id


# application form


def test_registration_does_not_offer_password_grant(pdb_app_model, org_admin):
    user, _ = org_admin
    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:register")

    content = client.get(url).content.decode()
    assert 'value="authorization-code"' in content
    assert 'value="password"' not in content

    resp = client.post(url, form_data(authorization_grant_type="password"))
    assert resp.status_code == 200
    assert not OAuthApplication.objects.filter(name="Form app").exists()

    resp = client.post(url, form_data())
    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(name="Form app").exists()


def test_update_password_grant_app_must_switch(pdb_app_model, org_admin):
    user, _ = org_admin
    app = OAuthApplication.objects.create(
        user=user, **app_fields(client_id="client_id_form")
    )
    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:update", args=(app.id,))

    # the current value stays selected so an unrelated edit can't switch it
    content = client.get(url).content.decode()
    assert '<option value="password" selected>' in content

    resp = client.post(url, form_data(authorization_grant_type="password"))
    assert resp.status_code == 200
    assert "password-based grant is no longer supported" in resp.content.decode()
    app.refresh_from_db()
    assert app.authorization_grant_type == "password"

    resp = client.post(url, form_data())
    assert resp.status_code == 302
    app.refresh_from_db()
    assert app.authorization_grant_type == "authorization-code"


# server metadata


# django-oauth-toolkit serves the /oauth2/ location itself
@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server",
        "/oauth2/.well-known/oauth-authorization-server",
    ],
)
def test_metadata_does_not_advertise_password_grant(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    grant_types = resp.json()["grant_types_supported"]
    assert "authorization_code" in grant_types
    assert "password" not in grant_types
