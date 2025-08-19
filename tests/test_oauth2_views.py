import json

import jwt
import pytest
from django.core.signing import get_cookie_signer
from django.test import Client
from django.urls import reverse
from oauth2_provider.models import AccessToken, Application, RefreshToken
from oauth2_provider.settings import oauth2_settings

from peeringdb_server.models import OAuthApplication, Organization, User
from tests.util import reset_group_ids


def override_app_model():
    oauth2_settings.APPLICATION_MODEL = "peeringdb_server.OAuthApplication"


def restore_app_model():
    oauth2_settings.APPLICATION_MODEL = "oauth2_provider.Application"


@pytest.fixture
def oauth2_org_admin_user():
    reset_group_ids()
    user = User.objects.create_user("test", "test", "test@localhost")
    org = Organization.objects.create(name="Test Org 001", status="ok")
    org.admin_usergroup.user_set.add(user)

    org_other = Organization.objects.create(name="Unprovisioned org", status="ok")

    return user, org, org_other


@pytest.fixture
def oauth2_apps(oauth2_org_admin_user):
    user, org, org_other = oauth2_org_admin_user

    user_app = OAuthApplication.objects.create(
        user=user,
        name="User app",
        client_id="client_id_user",
        client_secret="client_secret_user",
    )

    org_app = OAuthApplication.objects.create(
        org=org,
        name="Org app",
        client_id="client_id_org",
        client_secret="client_secret_org",
    )

    other_app = OAuthApplication.objects.create(
        org=org_other,
        name="Unprovisioned app",
        client_id="client_id_other",
        client_secret="client_secret_other",
    )

    return user_app, org_app, other_app


@pytest.mark.django_db
def test_app_list(oauth2_apps):
    override_app_model()

    user_app, org_app, other_app = oauth2_apps
    user = user_app.user

    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:list")

    resp = client.get(url)

    content = resp.content.decode("utf-8")

    assert resp.status_code == 200
    assert org_app.name in content
    assert user_app.name in content
    assert other_app.name not in content
    assert org_app.org.name in content

    # test that oauth app is listed in org admin view as well

    resp = client.get(f"/org/{org_app.org.id}/")
    content = resp.content.decode("utf-8")

    assert org_app.name in content
    assert other_app.name not in content
    assert user_app.name not in content

    restore_app_model()


@pytest.mark.django_db
def test_app_detail(oauth2_apps):
    override_app_model()

    def check_cache_headers(resp):
        assert resp.has_header("Cache-Control")
        cache_control_header = resp.headers.get("Cache-Control")
        assert "max-age=0" in cache_control_header
        assert "no-cache" in cache_control_header
        assert "no-store" in cache_control_header
        assert "must-revalidate" in cache_control_header
        assert "private" in cache_control_header

    user_app, org_app, other_app = oauth2_apps
    user = user_app.user

    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:list")

    # detail user owned app

    url = reverse("oauth2_provider:detail", args=(user_app.id,))
    resp = client.get(url)

    assert resp.status_code == 200
    check_cache_headers(resp)

    # detail org owned app

    url = reverse("oauth2_provider:detail", args=(org_app.id,))
    resp = client.get(url)

    assert resp.status_code == 200
    assert f"{org_app.org.name}'s management" in resp.content.decode("utf-8")
    check_cache_headers(resp)

    # detail unprovisioned org owned app (prohibited)

    url = reverse("oauth2_provider:detail", args=(other_app.id,))
    resp = client.get(url)

    assert resp.status_code == 404

    restore_app_model()


@pytest.mark.django_db
def test_app_delete(oauth2_apps):
    override_app_model()

    user_app, org_app, other_app = oauth2_apps
    user = user_app.user

    client = Client()
    client.force_login(user)

    # delete user owned app

    url = reverse("oauth2_provider:delete", args=(user_app.id,))
    resp = client.post(url)

    assert resp.status_code == 302
    assert not OAuthApplication.objects.filter(id=user_app.id).exists()

    # delete org owned app

    url = reverse("oauth2_provider:delete", args=(org_app.id,))
    resp = client.post(url)

    assert resp.status_code == 302
    assert not OAuthApplication.objects.filter(id=org_app.id).exists()

    # delete unprovisioned org owned app (prohibited)

    url = reverse("oauth2_provider:delete", args=(other_app.id,))
    resp = client.post(url)

    assert resp.status_code == 404
    assert OAuthApplication.objects.filter(id=other_app.id).exists()

    restore_app_model()


@pytest.mark.django_db
def test_app_registration_and_update(oauth2_org_admin_user):
    override_app_model()

    user, org, org_other = oauth2_org_admin_user

    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:register")

    # TEST CREATE

    resp = client.get(url, follow=True)

    assert resp.status_code == 200

    content = resp.content.decode("utf-8")

    assert f'<option value="{org.id}">{org.name}</option>' in content
    assert f'<option value="{org_other.id}">{org_other.name}</option>' not in content

    # test submitting user owned oauth app

    form_data = {
        "name": "User app",
        "client_id": "client_id",
        "client_secret": "client_secret",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(user=user, name="User app").exists()

    # test submitting org owner oauth app

    form_data = {
        "org": org.id,
        "name": "Org app",
        "client_id": "client_idB",
        "client_secret": "client_secretB",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(
        user__isnull=True, org=org, name="Org app"
    ).exists()

    # test permissions

    form_data = {
        "org": org_other.id,
        "name": "Org other app",
        "client_id": "client_idC",
        "client_secret": "client_secretC",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 200
    assert "That choice is not one of the available choices" in resp.content.decode(
        "utf-8"
    )
    assert not OAuthApplication.objects.filter(org=org_other).exists()

    # TEST UPDATE

    app = org.oauth_applications.first()

    url = reverse("oauth2_provider:update", args=(app.id,))

    resp = client.get(url, follow=True)

    assert resp.status_code == 200

    content = resp.content.decode("utf-8")

    assert f'<option value="{org.id}" selected>{org.name}</option>' in content
    assert f'<option value="{org_other.id}">{org_other.name}</option>' not in content

    form_data = {
        "org": org.id,
        "name": "Updated name",
        "client_id": "client_idB",
        "client_secret": "client_secretB",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(
        user__isnull=True, org=org, name="Updated name"
    ).exists()

    # test permissions

    form_data = {
        "org": org_other.id,
        "name": "Updated name",
        "client_id": "client_idB",
        "client_secret": "client_secretB",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 200
    assert "That choice is not one of the available choices" in resp.content.decode(
        "utf-8"
    )
    assert not OAuthApplication.objects.filter(org=org_other).exists()

    # test promote

    user_app = OAuthApplication.objects.filter(user=user, name="User app").first()
    url = reverse("oauth2_provider:update", args=(user_app.id,))

    form_data = {
        "org": org.id,
        "name": "Promoted app",
        "client_id": "client_id",
        "client_secret": "client_secret",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    print(resp.content.decode("utf-8"))

    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(
        user__isnull=True, org=org, id=user_app.id
    ).exists()

    restore_app_model()


@pytest.mark.django_db
def test_oauth_authorization_process(oauth2_org_admin_user):
    user, _, _ = oauth2_org_admin_user

    CLIENT_ID = "client_id_user"
    CLIENT_SECRET = "client_secret_user"
    REDIRECT_URIS = "https://example.com"
    SCOPES = "email profile networks"

    # Due to us swapping to our own OAuthApplication model, in order for the tests
    # to work we need to create the application in both the oauth2_provider and
    # peeringdb_server tables
    #
    # This is odd, and there is probably some way to avoid this, but from looking
    # at the oauth2_provider code, its not immediately clear how.

    user_app = Application.objects.create(
        user=user,
        name="User app",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uris=REDIRECT_URIS,
        skip_authorization=False,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        client_type=Application.CLIENT_CONFIDENTIAL,
    )

    user_app = OAuthApplication.objects.create(
        id=user_app.id,
        user=user,
        name="User app",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uris=REDIRECT_URIS,
        skip_authorization=False,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        client_type=Application.CLIENT_CONFIDENTIAL,
    )

    user = user_app.user
    client = Client()

    # Log in the user
    client.force_login(user)

    # Set the oauth_session cookie
    session = client.session
    session["oauth_session"] = True
    session.save()
    cookie_signer = get_cookie_signer(salt="oauth_session")
    signed_session_cookie = cookie_signer.sign(session.session_key)
    client.cookies["oauth_session"] = signed_session_cookie

    # Test the authorization request
    auth_url = reverse("oauth2_provider:authorize")
    auth_params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URIS,
        "scope": SCOPES,
        "state": "random_state",
    }
    resp = client.get(auth_url, auth_params)
    assert resp.status_code == 200
    assert "Application requires the following permissions" in resp.content.decode(
        "utf-8"
    )

    # Test the authorization grant
    auth_data = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URIS,
        "scope": SCOPES,
        "allow": "Authorize",
    }
    resp = client.post(auth_url, auth_data)
    assert resp.status_code == 302
    assert resp.url.startswith(REDIRECT_URIS)
    auth_code = resp.url.split("code=")[1]

    # Test the token exchange
    token_url = reverse("oauth2_provider:token")
    token_data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URIS,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = client.post(token_url, token_data)
    assert resp.status_code == 200
    token_data = resp.json()
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]

    # Test the token refresh
    refresh_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = client.post(token_url, refresh_data)
    assert resp.status_code == 200
    refresh_data = resp.json()
    new_access_token = refresh_data["access_token"]
    assert new_access_token != access_token

    # Test error scenarios
    # Invalid client_id
    invalid_client_data = token_data.copy()
    invalid_client_data["client_id"] = "invalid_client_id"
    resp = client.post(token_url, invalid_client_data)
    assert resp.status_code == 400

    # Invalid client_secret
    invalid_secret_data = token_data.copy()
    invalid_secret_data["client_secret"] = "invalid_client_secret"
    resp = client.post(token_url, invalid_secret_data)
    assert resp.status_code == 400

    # Clean up
    AccessToken.objects.all().delete()
    RefreshToken.objects.all().delete()


@pytest.mark.django_db
def test_oauth_authorization_process_amr(oauth2_org_admin_user):
    user, _, _ = oauth2_org_admin_user

    CLIENT_ID = "client_id_user"
    CLIENT_SECRET = "client_secret_user"
    REDIRECT_URIS = "https://example.com"
    SCOPES = "email profile networks"

    # Due to us swapping to our own OAuthApplication model, in order for the tests
    # to work we need to create the application in both the oauth2_provider and
    # peeringdb_server tables
    #
    # This is odd, and there is probably some way to avoid this, but from looking
    # at the oauth2_provider code, its not immediately clear how.

    user_app = Application.objects.create(
        user=user,
        name="User app",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uris=REDIRECT_URIS,
        skip_authorization=False,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        client_type=Application.CLIENT_CONFIDENTIAL,
    )

    user_app = OAuthApplication.objects.create(
        id=user_app.id,
        user=user,
        name="User app",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uris=REDIRECT_URIS,
        skip_authorization=False,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        client_type=Application.CLIENT_CONFIDENTIAL,
    )

    user = user_app.user
    client = Client()

    # Log in the user
    client.force_login(user)

    # Set the oauth_session cookie
    session = client.session
    session["amr"] = ["pwd"]
    session["oauth_session"] = True
    session.save()
    cookie_signer = get_cookie_signer(salt="oauth_session")
    signed_session_cookie = cookie_signer.sign(session.session_key)
    client.cookies["oauth_session"] = signed_session_cookie

    # Test the authorization request
    auth_url = reverse("oauth2_provider:authorize")
    auth_params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URIS,
        "scope": SCOPES,
        "state": "random_state",
    }
    resp = client.get(auth_url, auth_params)
    assert resp.status_code == 200
    assert "Application requires the following permissions" in resp.content.decode(
        "utf-8"
    )

    # Test the authorization grant
    auth_data = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URIS,
        "scope": SCOPES,
        "allow": "Authorize",
    }
    resp = client.post(auth_url, auth_data)
    assert resp.status_code == 302
    assert resp.url.startswith(REDIRECT_URIS)
    auth_code = resp.url.split("code=")[1]

    # Test the token exchange
    token_url = reverse("oauth2_provider:token")
    token_data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URIS,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = client.post(token_url, token_data)
    assert resp.status_code == 200
    token_data = resp.json()
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]

    access_token_object = AccessToken.objects.get(token=access_token)
    assert access_token_object.access_token_info.amr == "pwd"

    # Test the token refresh
    refresh_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = client.post(token_url, refresh_data)
    assert resp.status_code == 200
    refresh_data = resp.json()
    new_access_token = refresh_data["access_token"]
    assert new_access_token != access_token

    # Test error scenarios
    # Invalid client_id
    invalid_client_data = token_data.copy()
    invalid_client_data["client_id"] = "invalid_client_id"
    resp = client.post(token_url, invalid_client_data)
    assert resp.status_code == 400

    # Invalid client_secret
    invalid_secret_data = token_data.copy()
    invalid_secret_data["client_secret"] = "invalid_client_secret"
    resp = client.post(token_url, invalid_secret_data)
    assert resp.status_code == 400

    # Clean up
    AccessToken.objects.all().delete()
    RefreshToken.objects.all().delete()


@pytest.mark.django_db
def test_oauth_authorization_process_oidc_amr(oauth2_org_admin_user):
    user, _, _ = oauth2_org_admin_user

    CLIENT_ID = "client_id_user"
    CLIENT_SECRET = "client_secret_user"
    REDIRECT_URIS = "https://example.com"
    SCOPES = "openid email profile networks"

    # Due to us swapping to our own OAuthApplication model, in order for the tests
    # to work we need to create the application in both the oauth2_provider and
    # peeringdb_server tables
    #
    # This is odd, and there is probably some way to avoid this, but from looking
    # at the oauth2_provider code, its not immediately clear how.

    user_app = Application.objects.create(
        user=user,
        name="User app",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uris=REDIRECT_URIS,
        skip_authorization=False,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        client_type=Application.CLIENT_CONFIDENTIAL,
        algorithm="RS256",
    )

    user_app = OAuthApplication.objects.create(
        id=user_app.id,
        user=user,
        name="User app",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uris=REDIRECT_URIS,
        skip_authorization=False,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        client_type=Application.CLIENT_CONFIDENTIAL,
        algorithm="RS256",
    )

    user = user_app.user
    client = Client()

    # Log in the user
    client.force_login(user)

    # Set the oauth_session cookie
    session = client.session
    session["amr"] = ["pwd"]
    session["oauth_session"] = True
    session.save()
    cookie_signer = get_cookie_signer(salt="oauth_session")
    signed_session_cookie = cookie_signer.sign(session.session_key)
    client.cookies["oauth_session"] = signed_session_cookie

    # Test the authorization request
    auth_url = reverse("oauth2_provider:authorize")
    auth_params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URIS,
        "scope": SCOPES,
        "state": "random_state",
    }
    resp = client.get(auth_url, auth_params)
    assert resp.status_code == 200
    assert "Application requires the following permissions" in resp.content.decode(
        "utf-8"
    )

    # Test the authorization grant
    auth_data = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URIS,
        "scope": SCOPES,
        "allow": "Authorize",
    }
    resp = client.post(auth_url, auth_data)
    assert resp.status_code == 302
    assert resp.url.startswith(REDIRECT_URIS)
    auth_code = resp.url.split("code=")[1]

    # Test the token exchange
    token_url = reverse("oauth2_provider:token")
    token_data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URIS,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = client.post(token_url, token_data)
    assert resp.status_code == 200
    token_data = resp.json()
    access_token = token_data["access_token"]
    id_token = token_data["id_token"]
    assert id_token is not None

    id_token_payload = expand_id_token(id_token)
    assert id_token_payload["amr"] == ["pwd"]

    access_token_object = AccessToken.objects.get(token=access_token)
    assert access_token_object.access_token_info.amr == "pwd"


def expand_id_token(id_token):
    parts = id_token.split(".")
    payload = jwt.utils.base64url_decode(parts[1]).decode("utf-8")
    payload_json = json.loads(payload)
    return payload_json


@pytest.mark.django_db
class TestOAuthAuthorizationAMR:
    def setup_oauth_app(self, user, client_id_suffix, amr_description):
        """Helper method to create OAuth application for testing"""
        client_id = f"client_id_{client_id_suffix}"
        client_secret = f"client_secret_{client_id_suffix}"
        redirect_uris = "https://example.com"

        # Base Application object
        app = Application.objects.create(
            user=user,
            name=f"User app {amr_description}",
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=redirect_uris,
            skip_authorization=False,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            client_type=Application.CLIENT_CONFIDENTIAL,
        )

        # Extended OAuthApplication object
        oauth_app = OAuthApplication.objects.create(
            id=app.id,
            user=user,
            name=f"User app {amr_description}",
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=redirect_uris,
            skip_authorization=False,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            client_type=Application.CLIENT_CONFIDENTIAL,
        )

        return oauth_app, client_id, client_secret, redirect_uris

    def perform_oauth_flow(
        self, user, amr_values, client_id, client_secret, redirect_uris
    ):
        """
        Helper method to perform the complete OAuth flow with specific AMR values

        Args:
            user: The user performing the authorization
            amr_values: List of AMR values to set in the session
            client_id: OAuth client ID
            client_secret: OAuth client secret
            redirect_uris: Redirect URIs

        Returns:
            tuple: (access_token, profile_data)
        """
        client = Client()
        client.force_login(user)

        # Set session data
        session = client.session
        session["amr"] = amr_values
        session["oauth_session"] = True
        session.save()

        # Set up OAuth session cookie
        cookie_signer = get_cookie_signer(salt="oauth_session")
        signed_session_cookie = cookie_signer.sign(session.session_key)
        client.cookies["oauth_session"] = signed_session_cookie

        # Authorization request
        auth_url = reverse("oauth2_provider:authorize")
        scopes = "email profile networks amr"
        auth_params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uris,
            "scope": scopes,
            "state": "random_state",
        }
        resp = client.get(auth_url, auth_params)
        assert resp.status_code == 200
        assert "Application requires the following permissions" in resp.content.decode(
            "utf-8"
        )

        # User authorization
        auth_data = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uris,
            "scope": scopes,
            "allow": "Authorize",
        }
        resp = client.post(auth_url, auth_data)
        assert resp.status_code == 302
        assert resp.url.startswith(redirect_uris)
        auth_code = resp.url.split("code=")[1].split("&")[0]

        # Token exchange
        token_url = reverse("oauth2_provider:token")
        token_data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uris,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        resp = client.post(token_url, token_data)
        assert resp.status_code == 200
        token_response = resp.json()
        access_token = token_response["access_token"]

        # Verify token info contains correct AMR
        access_token_object = AccessToken.objects.get(token=access_token)
        expected_amr_string = ",".join(amr_values)
        assert access_token_object.access_token_info.amr == expected_amr_string

        # Verify profile endpoint returns correct AMR
        profile_url = reverse("profile-v1")
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = client.get(profile_url, **headers)
        assert resp.status_code == 200
        profile_data = resp.json()

        assert "amr" in profile_data
        assert profile_data["amr"] == amr_values

        return access_token, profile_data

    def cleanup(self, oauth_app):
        """Clean up test data"""
        AccessToken.objects.all().delete()
        RefreshToken.objects.all().delete()
        oauth_app.delete()

    def test_oauth_authorization_pwd_only(self, oauth2_org_admin_user):
        """Test OAuth authorization with password authentication only"""
        user, _, _ = oauth2_org_admin_user
        amr_values = ["pwd"]

        oauth_app, client_id, client_secret, redirect_uris = self.setup_oauth_app(
            user, "pwd_only", "Password only test"
        )

        try:
            self.perform_oauth_flow(
                user, amr_values, client_id, client_secret, redirect_uris
            )
        finally:
            self.cleanup(oauth_app)

    def test_oauth_authorization_pwd_mfa_otp(self, oauth2_org_admin_user):
        """Test OAuth authorization with Password + OTP authentication"""
        user, _, _ = oauth2_org_admin_user
        amr_values = ["pwd", "mfa", "otp"]

        oauth_app, client_id, client_secret, redirect_uris = self.setup_oauth_app(
            user, "pwd_mfa_otp", "Password + MFA + OTP test"
        )

        try:
            self.perform_oauth_flow(
                user, amr_values, client_id, client_secret, redirect_uris
            )
        finally:
            self.cleanup(oauth_app)

    def test_oauth_authorization_pwd_mfa_security_key(self, oauth2_org_admin_user):
        """Test OAuth authorization with Password + Security Key authentication"""
        user, _, _ = oauth2_org_admin_user
        amr_values = ["pwd", "mfa", "swk"]

        oauth_app, client_id, client_secret, redirect_uris = self.setup_oauth_app(
            user, "pwd_mfa_swk", "Password + MFA + Security Key test"
        )

        try:
            self.perform_oauth_flow(
                user, amr_values, client_id, client_secret, redirect_uris
            )
        finally:
            self.cleanup(oauth_app)

    def test_oauth_authorization_passkey_otp(self, oauth2_org_admin_user):
        """Test OAuth authorization with Passkey + OTP authentication"""
        user, _, _ = oauth2_org_admin_user
        amr_values = ["mfa", "swk", "otp"]

        oauth_app, client_id, client_secret, redirect_uris = self.setup_oauth_app(
            user, "passkey_otp", "Passkey + OTP test"
        )

        try:
            self.perform_oauth_flow(
                user, amr_values, client_id, client_secret, redirect_uris
            )
        finally:
            self.cleanup(oauth_app)

    def test_oauth_authorization_security_key_only(self, oauth2_org_admin_user):
        """Test OAuth authorization with Security Key authentication only"""
        user, _, _ = oauth2_org_admin_user
        amr_values = ["swk"]

        oauth_app, client_id, client_secret, redirect_uris = self.setup_oauth_app(
            user, "security_key_only", "Security Key only test"
        )

        try:
            self.perform_oauth_flow(
                user, amr_values, client_id, client_secret, redirect_uris
            )
        finally:
            self.cleanup(oauth_app)
