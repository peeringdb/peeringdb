"""
Tests for HS256 OAuth applications (#2055).

Client secrets are stored hashed, so HS256 ID tokens cannot be signed: HS256 is
neither offered on the application form nor advertised in discovery, remaining
HS256 applications get an OAuth error instead of a 500, and pdb_oauth_hs256
lists, migrates and/or notifies them.

Applications without OIDC support that request the openid scope get an
invalid_scope error instead of a 500 (#490).
"""

import base64
import json
from datetime import timedelta
from io import StringIO
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.signing import get_cookie_signer
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import (
    AccessToken,
    Application,
    Grant,
    IDToken,
    RefreshToken,
)
from oauth2_provider.settings import oauth2_settings

from mainsite.oauth2.validators import OIDCValidator, hs256_signing_unavailable
from peeringdb_server.models import OAuthApplication, Organization, User
from tests.util import reset_group_ids

pytestmark = pytest.mark.django_db

CLIENT_ID = "client_id_hs256"
CLIENT_SECRET = "client_secret_hs256"
REDIRECT_URI = "https://example.com"


@pytest.fixture
def pdb_app_model():
    previous = oauth2_settings.APPLICATION_MODEL
    oauth2_settings.APPLICATION_MODEL = "peeringdb_server.OAuthApplication"
    yield
    oauth2_settings.APPLICATION_MODEL = previous


@pytest.fixture
def org_admin():
    reset_group_ids()
    user = User.objects.create_user("owner", "owner@example.com", "owner")
    org = Organization.objects.create(name="Test Org 001", status="ok")
    org.admin_usergroup.user_set.add(user)
    return user, org


def app_fields(**kwargs):
    fields = {
        "name": "HS256 app",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": REDIRECT_URI,
        "skip_authorization": False,
        "authorization_grant_type": Application.GRANT_AUTHORIZATION_CODE,
        "client_type": Application.CLIENT_CONFIDENTIAL,
        "algorithm": Application.HS256_ALGORITHM,
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
        "algorithm": "",
    }
    data.update(kwargs)
    return data


def unsigned_jwt(claims):
    def b64(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=")

    return b".".join(
        [b64({"alg": "HS256", "typ": "JWT"}), b64(claims), b"sig"]
    ).decode()


# discovery


@pytest.mark.parametrize(
    "path",
    ["/.well-known/openid-configuration", "/oauth2/.well-known/openid-configuration"],
)
def test_oidc_discovery_omits_hs256(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.json()["id_token_signing_alg_values_supported"] == ["RS256"]
    assert resp["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize(
    "path,key",
    [
        ("/.well-known/openid-configuration", "id_token_signing_alg_values_supported"),
        ("/.well-known/oauth-authorization-server", "signing_algorithms_supported"),
    ],
)
def test_discovery_without_rsa_key_advertises_nothing(client, monkeypatch, path, key):
    monkeypatch.setattr(oauth2_settings, "OIDC_RSA_PRIVATE_KEY", "")
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.json()[key] == []


# application form


def test_registration_does_not_offer_hs256(pdb_app_model, org_admin):
    user, _ = org_admin
    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:register")

    content = client.get(url).content.decode()
    assert 'value="RS256"' in content
    assert 'value="HS256"' not in content

    resp = client.post(url, form_data(algorithm="HS256"))
    assert resp.status_code == 200
    assert not OAuthApplication.objects.filter(name="Form app").exists()


def test_update_hs256_app_must_switch(pdb_app_model, org_admin):
    user, _ = org_admin
    app = OAuthApplication.objects.create(
        user=user, **app_fields(client_id="client_id_form")
    )
    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:update", args=(app.id,))

    # the current value stays selected so an unrelated edit can't drop OIDC
    content = client.get(url).content.decode()
    assert '<option value="HS256" selected>' in content

    resp = client.post(url, form_data(algorithm="HS256"))
    assert resp.status_code == 200
    assert "HS256 is no longer supported" in resp.content.decode()
    app.refresh_from_db()
    assert app.algorithm == "HS256"

    resp = client.post(url, form_data(algorithm="RS256"))
    assert resp.status_code == 302
    app.refresh_from_db()
    assert app.algorithm == "RS256"


# token endpoint and validator


def oauth_session_login(client, user):
    client.force_login(user)
    session = client.session
    session["amr"] = ["pwd"]
    session["oauth_session"] = True
    session.save()
    client.cookies["oauth_session"] = get_cookie_signer(salt="oauth_session").sign(
        session.session_key
    )


def authorization_code(client, user, scope="openid profile"):
    oauth_session_login(client, user)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": scope,
    }
    auth_url = reverse("oauth2_provider:authorize")
    assert client.get(auth_url, params).status_code == 200
    resp = client.post(auth_url, {**params, "allow": "Authorize"})
    assert resp.status_code == 302
    return parse_qs(urlparse(resp.url).query)["code"][0]


def token_request(client, code):
    return client.post(
        reverse("oauth2_provider:token"),
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )


# an app that cannot sign ID tokens: HS256 with a hashed secret (#2055), or no
# OIDC support at all (#490)
UNSIGNABLE_APPS = pytest.mark.parametrize(
    "algorithm,error,description",
    [
        (Application.HS256_ALGORITHM, "unauthorized_client", "HS256"),
        (
            Application.NO_ALGORITHM,
            "invalid_scope",
            "does not support OpenID Connect",
        ),
    ],
    ids=["hs256", "no_oidc"],
)


@UNSIGNABLE_APPS
def test_token_unsignable_app_gets_oauth_error(
    org_admin, algorithm, error, description
):
    user, _ = org_admin
    create_dual_app(user=user, algorithm=algorithm)
    client = Client()
    code = authorization_code(client, user)

    resp = token_request(client, code)

    assert resp.status_code == 400
    assert resp["Content-Type"] == "application/json"
    assert resp["Cache-Control"] == "no-store"
    data = resp.json()
    assert data["error"] == error
    assert description in data["error_description"]
    assert not AccessToken.objects.exists()
    assert not IDToken.objects.exists()


def test_token_no_oidc_app_without_openid_succeeds(org_admin):
    user, _ = org_admin
    create_dual_app(user=user, algorithm=Application.NO_ALGORITHM)
    client = Client()
    code = authorization_code(client, user, scope="profile")

    resp = token_request(client, code)

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "id_token" not in data


@UNSIGNABLE_APPS
@pytest.mark.parametrize(
    "grant_type,response_type",
    [
        (Application.GRANT_IMPLICIT, "id_token token"),
        (Application.GRANT_OPENID_HYBRID, "code id_token"),
    ],
)
def test_authorize_unsignable_app_redirects_error(
    org_admin, grant_type, response_type, algorithm, error, description
):
    user, _ = org_admin
    create_dual_app(user=user, authorization_grant_type=grant_type, algorithm=algorithm)
    client = Client()
    oauth_session_login(client, user)
    params = {
        "client_id": CLIENT_ID,
        "response_type": response_type,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile",
        "nonce": "nonce",
        "state": "state",
    }
    auth_url = reverse("oauth2_provider:authorize")
    assert client.get(auth_url, params).status_code == 200

    resp = client.post(auth_url, {**params, "allow": "Authorize"})

    assert resp.status_code == 302
    location = urlparse(resp.url)
    assert resp.url.startswith(REDIRECT_URI)
    returned = {**parse_qs(location.query), **parse_qs(location.fragment)}
    assert returned["error"] == [error]
    assert returned["state"] == ["state"]
    assert not AccessToken.objects.exists()
    assert not Grant.objects.exists()
    assert not IDToken.objects.exists()


@UNSIGNABLE_APPS
def test_refresh_unsignable_app_gets_oauth_error(
    org_admin, algorithm, error, description
):
    # a no-OIDC app can hold openid tokens if it was switched after they were
    # issued
    user, _ = org_admin
    app = create_dual_app(user=user, algorithm=algorithm)
    access = AccessToken.objects.create(
        user=user,
        application=app,
        token="access_unsignable",
        expires=timezone.now() + timedelta(hours=1),
        scope="openid profile",
    )
    refresh = RefreshToken.objects.create(
        user=user, application=app, token="refresh_unsignable", access_token=access
    )

    resp = Client().post(
        reverse("oauth2_provider:token"),
        {
            "grant_type": "refresh_token",
            "refresh_token": "refresh_unsignable",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == error
    # the refresh token was not rotated and is still usable
    refresh.refresh_from_db()
    assert refresh.revoked is None
    assert list(AccessToken.objects.values_list("token", flat=True)) == [
        "access_unsignable"
    ]
    assert not IDToken.objects.exists()


def test_id_token_key_lookup_skips_hs256_app(org_admin):
    # #2022 also overrides the audience lookup; this fails if a merge of the
    # two keeps only the other definition
    user, _ = org_admin
    Application.objects.create(user=user, **app_fields())

    key = OIDCValidator()._get_key_for_token(unsigned_jwt({"aud": CLIENT_ID}))

    assert key is None


def test_hs256_signing_unavailable(org_admin):
    user, _ = org_admin
    hashed = Application.objects.create(user=user, **app_fields())
    plaintext = Application.objects.create(
        user=user, hash_client_secret=False, **app_fields(client_id="plaintext")
    )
    rs256 = Application.objects.create(
        user=user, **app_fields(client_id="rs256", algorithm="RS256")
    )

    assert hs256_signing_unavailable(hashed)
    assert not hs256_signing_unavailable(plaintext)
    assert not hs256_signing_unavailable(rs256)


def test_hs256_id_token_is_invalid_not_error(org_admin):
    user, _ = org_admin
    Application.objects.create(user=user, **app_fields())
    validator = OIDCValidator()
    token = unsigned_jwt({"aud": CLIENT_ID, "jti": "x"})

    assert validator._get_client_by_audience([CLIENT_ID]) is None
    assert validator.validate_id_token(token, ["openid"], request=None) is False


# pdb_oauth_hs256


@pytest.fixture
def hs256_apps(pdb_app_model, org_admin):
    admin, org = org_admin
    owner = User.objects.create_user("user_owner", "user_owner@example.com", "x")
    org_app = OAuthApplication.objects.create(
        org=org, **app_fields(name="Org & app", client_id="org_app")
    )
    user_app = OAuthApplication.objects.create(
        user=owner, **app_fields(name="User app", client_id="user_app")
    )
    rs256_app = OAuthApplication.objects.create(
        user=owner,
        **app_fields(name="RS app", client_id="rs_app", algorithm="RS256"),
    )
    return org_app, user_app, rs256_app


def algorithms(apps):
    return [OAuthApplication.objects.get(id=app.id).algorithm for app in apps]


@override_settings(MAIL_DEBUG=False)
def test_command_dry_run_changes_nothing(
    hs256_apps, django_capture_on_commit_callbacks
):
    out = StringIO()
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_oauth_hs256", "--migrate", "--notify", stdout=out)

    assert algorithms(hs256_apps) == ["HS256", "HS256", "RS256"]
    assert mail.outbox == []
    output = out.getvalue()
    assert "Org & app" in output and "User app" in output
    assert "RS app" not in output
    assert "2 HS256 OAuth application(s)" in output


@override_settings(MAIL_DEBUG=False)
def test_command_migrate(hs256_apps, django_capture_on_commit_callbacks):
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_oauth_hs256", "--migrate", "--commit", stdout=StringIO())

    assert algorithms(hs256_apps) == ["RS256", "RS256", "RS256"]
    assert mail.outbox == []


@override_settings(MAIL_DEBUG=False)
def test_command_notify(hs256_apps, django_capture_on_commit_callbacks):
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command("pdb_oauth_hs256", "--notify", "--commit", stdout=StringIO())

    assert algorithms(hs256_apps) == ["HS256", "HS256", "RS256"]
    recipients = sorted(email.to[0] for email in mail.outbox)
    assert recipients == ["owner@example.com", "user_owner@example.com"]
    for email in mail.outbox:
        assert "Until the application is switched to RS256" in email.body
    org_mail = next(e for e in mail.outbox if e.to == ["owner@example.com"])
    assert '"Org & app"' in org_mail.body


@override_settings(MAIL_DEBUG=False)
def test_command_migrate_and_notify(hs256_apps, django_capture_on_commit_callbacks):
    mail.outbox = []
    with django_capture_on_commit_callbacks(execute=True):
        call_command(
            "pdb_oauth_hs256", "--migrate", "--notify", "--commit", stdout=StringIO()
        )

    assert algorithms(hs256_apps) == ["RS256", "RS256", "RS256"]
    assert len(mail.outbox) == 2
    for email in mail.outbox:
        assert "We have switched the application to RS256" in email.body


def test_command_migrate_needs_rsa_key(hs256_apps, monkeypatch):
    monkeypatch.setattr(oauth2_settings, "OIDC_RSA_PRIVATE_KEY", "")
    with pytest.raises(CommandError):
        call_command("pdb_oauth_hs256", "--migrate", "--commit", stdout=StringIO())
    assert algorithms(hs256_apps) == ["HS256", "HS256", "RS256"]


@override_settings(MAIL_DEBUG=False)
def test_command_skips_hs256_app_that_can_sign(hs256_apps):
    _, user_app, _ = hs256_apps
    plaintext = OAuthApplication.objects.create(
        user=user_app.user,
        hash_client_secret=False,
        **app_fields(name="Plaintext app", client_id="plaintext_app"),
    )
    out = StringIO()
    mail.outbox = []
    call_command("pdb_oauth_hs256", "--migrate", "--notify", "--commit", stdout=out)

    assert algorithms([plaintext]) == ["HS256"]
    assert "skipped" in out.getvalue()
    assert "2 HS256 OAuth application(s)" in out.getvalue()
    assert len(mail.outbox) == 2


@override_settings(MAIL_DEBUG=False)
def test_command_failed_send_continues_and_reports(hs256_apps, monkeypatch):
    original = User.email_user

    def email_user(user, *args, **kwargs):
        if user.email == "owner@example.com":
            raise OSError("smtp down")
        return original(user, *args, **kwargs)

    monkeypatch.setattr(User, "email_user", email_user)
    mail.outbox = []
    org_app = hs256_apps[0]
    with pytest.raises(
        CommandError,
        match=rf"Not notified.*application\(s\) {org_app.id}\b.*left on HS256.*/cp",
    ):
        call_command(
            "pdb_oauth_hs256", "--migrate", "--notify", "--commit", stdout=StringIO()
        )

    # the run went on: the other owner was mailed and only that app switched
    assert algorithms(hs256_apps) == ["HS256", "RS256", "RS256"]
    assert [email.to for email in mail.outbox] == [["user_owner@example.com"]]


@override_settings(MAIL_DEBUG=False)
def test_command_does_not_switch_unnotifiable_app(hs256_apps):
    _, user_app, _ = hs256_apps
    User.objects.filter(id=user_app.user_id).update(email="")
    mail.outbox = []

    with pytest.raises(
        CommandError, match=rf"Not notified.*application\(s\) {user_app.id}\b"
    ):
        call_command(
            "pdb_oauth_hs256", "--migrate", "--notify", "--commit", stdout=StringIO()
        )

    assert algorithms(hs256_apps) == ["RS256", "HS256", "RS256"]
    assert [email.to for email in mail.outbox] == [["owner@example.com"]]

    # a re-run still finds it
    out = StringIO()
    call_command("pdb_oauth_hs256", stdout=out)
    assert "User app" in out.getvalue()
    assert "1 HS256 OAuth application(s)" in out.getvalue()


def test_command_dry_run_lists_unnotifiable_app(hs256_apps):
    _, user_app, _ = hs256_apps
    User.objects.filter(id=user_app.user_id).update(email="")
    out = StringIO()

    # a preview must not fail, it says what would happen
    call_command("pdb_oauth_hs256", "--migrate", "--notify", stdout=out)

    output = out.getvalue()
    assert (
        f"Would not be notified (no active owner with an email address): application(s) {user_app.id}."
        in output
    )
    assert "They would stay on HS256." in output
    assert algorithms(hs256_apps) == ["HS256", "HS256", "RS256"]


@override_settings(MAIL_DEBUG=False)
def test_command_partial_send_failure(hs256_apps, monkeypatch):
    org_app = hs256_apps[0]
    second_admin = User.objects.create_user("admin2", "admin2@example.com", "x")
    org_app.org.admin_usergroup.user_set.add(second_admin)
    original = User.email_user

    def email_user(user, *args, **kwargs):
        if user.email == "owner@example.com":
            raise OSError("smtp down")
        return original(user, *args, **kwargs)

    monkeypatch.setattr(User, "email_user", email_user)
    mail.outbox = []
    with pytest.raises(CommandError) as excinfo:
        call_command(
            "pdb_oauth_hs256", "--migrate", "--notify", "--commit", stdout=StringIO()
        )

    # the other admin was mailed, so the app was switched and a re-run won't
    # find it: the missed admin has to be contacted by hand
    message = str(excinfo.value)
    assert (
        f"these sends failed: application {org_app.id} -> owner@example.com" in message
    )
    assert "contact these owners by hand" in message
    assert "Not notified" not in message
    assert algorithms(hs256_apps) == ["RS256", "RS256", "RS256"]


@override_settings(MAIL_DEBUG=False)
def test_command_notify_only_unnotifiable_app(hs256_apps):
    _, user_app, _ = hs256_apps
    User.objects.filter(id=user_app.user_id).update(email="")
    mail.outbox = []

    # nothing is switched without --migrate, so a re-run would mail everyone
    with pytest.raises(
        CommandError, match="a re-run mails every owner again"
    ) as excinfo:
        call_command("pdb_oauth_hs256", "--notify", "--commit", stdout=StringIO())

    assert f"application(s) {user_app.id}." in str(excinfo.value)
    assert "and re-run" not in str(excinfo.value)
    assert algorithms(hs256_apps) == ["HS256", "HS256", "RS256"]
