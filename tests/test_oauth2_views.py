import json
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
import pytest
from django.core.signing import get_cookie_signer
from django.test import Client
from django.urls import reverse
from oauth2_provider.models import AccessToken, Application, RefreshToken
from oauth2_provider.settings import oauth2_settings
from oauthlib.oauth2.rfc6749.endpoints.authorization import AuthorizationEndpoint

from mainsite.oauth2.validators import OIDCValidator
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
def test_app_superuser_access(oauth2_apps):
    """Superusers bypass ownership checks across all ApplicationOwnerMixin views."""
    override_app_model()

    user_app, org_app, other_app = oauth2_apps

    superuser = User.objects.create_superuser(
        "superuser", "superuser@localhost", "superuser"
    )

    client = Client()
    client.force_login(superuser)

    # list: superuser sees every app, including ones from orgs they aren't in
    resp = client.get(reverse("oauth2_provider:list"))
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert user_app.name in content
    assert org_app.name in content
    assert other_app.name in content

    # detail: superuser can open any app's detail page (the original bug)
    for app in (user_app, org_app, other_app):
        resp = client.get(reverse("oauth2_provider:detail", args=(app.id,)))
        assert resp.status_code == 200

    # update GET: superuser can load the edit form for an unprovisioned org's app
    resp = client.get(reverse("oauth2_provider:update", args=(other_app.id,)))
    assert resp.status_code == 200

    # delete: superuser can delete an unprovisioned org's app
    resp = client.post(reverse("oauth2_provider:delete", args=(other_app.id,)))
    assert resp.status_code == 302
    assert not OAuthApplication.objects.filter(id=other_app.id).exists()

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


AUTHORIZE_CLIENT_ID = "client_id_user"
AUTHORIZE_CLIENT_SECRET = "client_secret_user"
AUTHORIZE_REDIRECT_URI = "https://example.com"


def authorize_at_endpoint(user, app_grant_type, response_type, scope, **extra_params):
    """
    Authorizes an RS256 app for a user whose login session has amr
    pwd,mfa and returns the client and the parameters of the redirect
    """

    app_fields = dict(
        user=user,
        name="User app",
        client_id=AUTHORIZE_CLIENT_ID,
        client_secret=AUTHORIZE_CLIENT_SECRET,
        redirect_uris=AUTHORIZE_REDIRECT_URI,
        skip_authorization=False,
        authorization_grant_type=app_grant_type,
        client_type=Application.CLIENT_CONFIDENTIAL,
        algorithm="RS256",
    )
    app = Application.objects.create(**app_fields)
    OAuthApplication.objects.create(id=app.id, **app_fields)

    client = Client()
    client.force_login(user)
    session = client.session
    session["amr"] = ["pwd", "mfa"]
    session["oauth_session"] = True
    session.save()
    cookie_signer = get_cookie_signer(salt="oauth_session")
    client.cookies["oauth_session"] = cookie_signer.sign(session.session_key)

    auth_url = reverse("oauth2_provider:authorize")
    auth_params = {
        "client_id": AUTHORIZE_CLIENT_ID,
        "response_type": response_type,
        "redirect_uri": AUTHORIZE_REDIRECT_URI,
        "scope": scope,
        "nonce": "nonce",
        "state": "state",
        **extra_params,
    }
    assert client.get(auth_url, auth_params).status_code == 200

    # the consent form posts back to the URL it was served from
    resp = client.post(
        f"{auth_url}?{urlencode(auth_params)}", {**auth_params, "allow": "Authorize"}
    )

    assert resp.status_code == 302
    assert resp.url.startswith(AUTHORIZE_REDIRECT_URI)
    return client, parse_qs(urlparse(resp.url).fragment)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "grant_type,response_type",
    [
        (Application.GRANT_IMPLICIT, "id_token token"),
        (Application.GRANT_IMPLICIT, "id_token"),
        (Application.GRANT_OPENID_HYBRID, "code id_token"),
        (Application.GRANT_OPENID_HYBRID, "code id_token token"),
    ],
)
def test_oauth_authorization_endpoint_oidc_amr(
    oauth2_org_admin_user, grant_type, response_type
):
    """
    Implicit and hybrid flows issue the ID token at the authorization endpoint,
    with amr taken from the login session (#490)
    """

    user, _, _ = oauth2_org_admin_user
    _, returned = authorize_at_endpoint(
        user, grant_type, response_type, "openid profile"
    )

    id_token_payload = expand_id_token(returned["id_token"][0])
    assert id_token_payload["amr"] == ["pwd", "mfa"]
    assert id_token_payload["nonce"] == "nonce"

    if "code" in returned:
        # the ID token from the code exchange carries the same amr, from the
        # grant: the relying party's backend has no session
        resp = Client().post(
            reverse("oauth2_provider:token"),
            {
                "grant_type": "authorization_code",
                "code": returned["code"][0],
                "redirect_uri": AUTHORIZE_REDIRECT_URI,
                "client_id": AUTHORIZE_CLIENT_ID,
                "client_secret": AUTHORIZE_CLIENT_SECRET,
            },
        )
        assert resp.status_code == 200
        assert expand_id_token(resp.json()["id_token"])["amr"] == ["pwd", "mfa"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "grant_type,response_type,scope",
    [
        (Application.GRANT_IMPLICIT, "id_token token", "openid profile"),
        (Application.GRANT_IMPLICIT, "token", "profile"),
        # oauthlib saves the access token before the grant, so there is no
        # grant to read amr from yet
        (Application.GRANT_OPENID_HYBRID, "code token", "openid profile"),
        (Application.GRANT_OPENID_HYBRID, "code id_token token", "openid profile"),
    ],
)
def test_oauth_authorization_endpoint_access_token_amr(
    oauth2_org_admin_user, grant_type, response_type, scope
):
    """
    An access token issued at the authorization endpoint records the amr of
    the login session (#490)
    """

    user, _, _ = oauth2_org_admin_user
    _, returned = authorize_at_endpoint(user, grant_type, response_type, scope)

    access_token_object = AccessToken.objects.get(token=returned["access_token"][0])
    assert access_token_object.access_token_info.amr == "pwd,mfa"


@pytest.mark.django_db
def test_oauth_authorization_endpoint_ignores_grant_type_param(oauth2_org_admin_user):
    """
    A grant_type in the authorization request's query string does not make it
    look like a token request (#490)
    """

    user, _, _ = oauth2_org_admin_user
    _, returned = authorize_at_endpoint(
        user,
        Application.GRANT_IMPLICIT,
        "id_token token",
        "openid profile",
        grant_type="implicit",
    )

    assert expand_id_token(returned["id_token"][0])["amr"] == ["pwd", "mfa"]
    access_token_object = AccessToken.objects.get(token=returned["access_token"][0])
    assert access_token_object.access_token_info.amr == "pwd,mfa"


@pytest.mark.django_db
def test_oauth_authorization_endpoint_amr_with_request_body(
    oauth2_org_admin_user, monkeypatch
):
    """
    amr still comes from the login session if django-oauth-toolkit passes a
    request body to oauthlib at the authorization endpoint, which it does not
    do today (#490)
    """

    original_authorize = AuthorizationEndpoint.create_authorization_response

    def authorize_with_body(self, uri, **kwargs):
        kwargs["body"] = "allow=Authorize"
        return original_authorize(self, uri, **kwargs)

    monkeypatch.setattr(
        AuthorizationEndpoint, "create_authorization_response", authorize_with_body
    )

    decoded_bodies = []
    original_finalize = OIDCValidator.finalize_id_token

    def finalize_id_token(self, id_token, token, token_handler, request):
        decoded_bodies.append(request.decoded_body)
        return original_finalize(self, id_token, token, token_handler, request)

    monkeypatch.setattr(OIDCValidator, "finalize_id_token", finalize_id_token)

    user, _, _ = oauth2_org_admin_user
    _, returned = authorize_at_endpoint(
        user, Application.GRANT_IMPLICIT, "id_token token", "openid profile"
    )

    assert decoded_bodies == [[("allow", "Authorize")]]
    assert expand_id_token(returned["id_token"][0])["amr"] == ["pwd", "mfa"]
    access_token_object = AccessToken.objects.get(token=returned["access_token"][0])
    assert access_token_object.access_token_info.amr == "pwd,mfa"


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
