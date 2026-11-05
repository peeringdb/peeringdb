import time
from urllib.parse import urlencode

import pytest
from django.contrib.auth import SESSION_KEY
from django.core.signing import get_cookie_signer
from django.test import Client
from django.urls import resolve, reverse
from oauth2_provider.models import Application, get_device_grant_model

from peeringdb_server.models import OAuthApplication, User
from peeringdb_server.oauth_views import DeviceConfirmView, DeviceUserCodeView
from peeringdb_server.views import is_oauth_authorize

from .util import create_oauth_application, oauth_login_marker, reset_group_ids

pytestmark = pytest.mark.django_db

PASSWORD = "oauth-login-marker"
CLIENT_ID = "oauth-login-marker"
AUTHORIZE_PARAMS = {
    "client_id": CLIENT_ID,
    "response_type": "code",
    "redirect_uri": "https://example.com",
    "scope": "profile",
    "state": "state",
}
CONSENT = "Application requires the following permissions"


@pytest.fixture
def user():
    reset_group_ids()
    user = User.objects.create_user(
        "oauth-login-marker", "marker@localhost", PASSWORD, status="ok"
    )
    create_oauth_application(user, CLIENT_ID, "oauth-login-marker-secret")
    return user


def authorize(client):
    return client.get(reverse("oauth2_provider:authorize"), AUTHORIZE_PARAMS)


def logged_in_client(user, marker=None):
    client = Client()
    client.force_login(user)
    if marker is not None:
        session = client.session
        session["oauth_login"] = marker
        session.save()
    return client


def test_wizard_login_for_authorize_sets_marker(user):
    client = Client()
    authorize_url = (
        f"{reverse('oauth2_provider:authorize')}?{urlencode(AUTHORIZE_PARAMS)}"
    )
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": PASSWORD,
            "next": authorize_url,
        },
    )
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    marker = client.session["oauth_login"]
    assert marker["user_id"] == user.pk
    assert time.time() - marker["at"] < 60
    assert "oauth_session" not in client.cookies

    assert CONSENT in authorize(client).content.decode()


def test_wizard_login_elsewhere_sets_no_marker(user):
    client = Client()
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": PASSWORD,
            "next": "/",
        },
    )
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert "oauth_login" not in client.session

    response = authorize(client)
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login"))


def test_recent_marker_shows_consent(user):
    response = authorize(logged_in_client(user, oauth_login_marker(user)))
    assert response.status_code == 200
    assert CONSENT in response.content.decode()


@pytest.mark.parametrize(
    "marker",
    [
        None,
        True,
        {"user_id": None, "at": None},
        {"at": time.time()},
    ],
    ids=["missing", "legacy", "empty", "no-user"],
)
def test_invalid_marker_redirects_to_login(user, marker):
    response = authorize(logged_in_client(user, marker))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login"))


def test_expired_marker_redirects_to_login(user, settings):
    stale = time.time() - settings.OAUTH_COOKIE_MAX_AGE - 1
    response = authorize(logged_in_client(user, oauth_login_marker(user, at=stale)))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login"))


def test_marker_of_another_user_redirects_to_login(user):
    other = User.objects.create_user("oauth-login-other", "other@localhost", PASSWORD)
    response = authorize(logged_in_client(user, oauth_login_marker(other)))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login"))


def test_signed_cookie_alone_is_not_accepted(user):
    client = logged_in_client(user)
    client.cookies["oauth_session"] = get_cookie_signer(salt="oauth_session").sign(
        user.username
    )
    response = authorize(client)
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login"))


def test_logout_clears_marker(user):
    client = logged_in_client(user, oauth_login_marker(user))
    client.logout()
    client.force_login(user)
    assert "oauth_login" not in client.session
    assert authorize(client).status_code == 302


def wizard_login(client, user, next):
    return client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": PASSWORD,
            "next": next,
        },
    )


def test_stale_marker_relogin_refreshes_marker(user, settings):
    stale = time.time() - settings.OAUTH_COOKIE_MAX_AGE - 1
    client = logged_in_client(user, oauth_login_marker(user, at=stale))

    response = authorize(client)
    assert response.status_code == 302
    login_url = response["Location"]
    assert login_url.startswith(reverse("two_factor:login"))

    # the wizard is shown to the logged in user for the authorize url
    assert client.get(login_url).status_code == 200

    authorize_url = (
        f"{reverse('oauth2_provider:authorize')}?{urlencode(AUTHORIZE_PARAMS)}"
    )
    response = wizard_login(client, user, authorize_url)
    assert response.status_code == 302
    assert response["Location"] == authorize_url
    marker = client.session["oauth_login"]
    assert marker["user_id"] == user.pk
    assert marker["at"] > stale + settings.OAUTH_COOKIE_MAX_AGE

    response = authorize(client)
    assert response.status_code == 200
    assert CONSENT in response.content.decode()


# device authorization flow (RFC 8628)

DEVICE_CLIENT_ID = "oauth-login-marker-device"
FORM = "application/x-www-form-urlencoded"


@pytest.fixture
def user_code(user):
    fields = dict(
        user=user,
        name=DEVICE_CLIENT_ID,
        client_id=DEVICE_CLIENT_ID,
        client_secret="",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_DEVICE_CODE,
        redirect_uris="https://example.com",
    )
    app = Application.objects.create(**fields)
    OAuthApplication.objects.create(id=app.id, **fields)
    response = Client().post(
        reverse("oauth2_provider:device-authorization"),
        urlencode({"client_id": DEVICE_CLIENT_ID, "scope": "profile"}),
        content_type=FORM,
    )
    assert response.status_code == 200
    return response.json()["user_code"]


def device_urls(user_code):
    return (
        reverse("oauth2_provider:device"),
        reverse(
            "oauth2_provider:device-confirm",
            kwargs={"client_id": DEVICE_CLIENT_ID, "user_code": user_code},
        ),
    )


def device_grant_status(user_code):
    return get_device_grant_model().objects.get(user_code=user_code).status


def test_device_routes_are_shadowed(user_code):
    device_url, confirm_url = device_urls(user_code)
    assert resolve(device_url).func.view_class is DeviceUserCodeView
    assert resolve(confirm_url).func.view_class is DeviceConfirmView


@pytest.mark.parametrize(
    "stale", [False, True], ids=["missing-marker", "expired-marker"]
)
def test_device_consent_requires_recent_login(user, user_code, settings, stale):
    marker = None
    if stale:
        marker = oauth_login_marker(
            user, at=time.time() - settings.OAUTH_COOKIE_MAX_AGE - 1
        )
    client = logged_in_client(user, marker)
    device_url, confirm_url = device_urls(user_code)

    for response in (
        client.get(device_url),
        client.post(device_url, {"user_code": user_code}),
        client.get(confirm_url),
        client.post(confirm_url, {"action": "accept"}),
    ):
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("two_factor:login"))

    assert device_grant_status(user_code) == "authorization-pending"


def test_device_consent_with_recent_login(user, user_code):
    client = logged_in_client(user, oauth_login_marker(user))
    device_url, confirm_url = device_urls(user_code)

    assert client.get(device_url).status_code == 200
    response = client.post(device_url, {"user_code": user_code})
    assert response.status_code == 302
    assert response["Location"] == confirm_url
    response = client.post(confirm_url, {"action": "accept"})
    assert response.status_code == 302
    assert device_grant_status(user_code) == "authorized"


def test_wizard_login_for_device_sets_marker(user, user_code):
    client = Client()
    device_url = f"{reverse('oauth2_provider:device')}?user_code={user_code}"
    response = wizard_login(client, user, device_url)
    assert response.status_code == 302
    assert response["Location"] == device_url
    assert client.session["oauth_login"]["user_id"] == user.pk
    assert client.get(device_url).status_code == 200


# `next` must stay on this site

OFF_SITE_NEXT = [
    "https://evil.example/oauth2/authorize/?client_id=x",
    "//evil.example/oauth2/device/",
    "https://evil.example/oauth2/device-confirm/abc/def",
    "http://testserver.evil.example/oauth2/authorize/",
    "///evil.example/oauth2/authorize/",
    "/\\evil.example/oauth2/authorize/",
]
MALFORMED_NEXT = ["http://[", "//[bad/oauth2/device/", "https://[::1/oauth2/authorize/"]


@pytest.mark.parametrize("url", OFF_SITE_NEXT + MALFORMED_NEXT)
def test_is_oauth_authorize_refuses_off_site_and_malformed(url):
    assert not is_oauth_authorize(url)


@pytest.mark.parametrize(
    "url",
    [
        "/oauth2/authorize/?client_id=x",
        "/oauth2/device/",
        "/oauth2/device/?user_code=ABC",
        "/oauth2/device-confirm/abc/def",
    ],
)
def test_is_oauth_authorize_local_consent_pages(url):
    assert is_oauth_authorize(url)


@pytest.mark.parametrize("next", OFF_SITE_NEXT + MALFORMED_NEXT)
def test_wizard_login_with_off_site_next_lands_on_site(user, next):
    client = Client()
    response = wizard_login(client, user, next)
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert client.session[SESSION_KEY] == str(user.pk)
    assert "oauth_login" not in client.session


@pytest.mark.parametrize("next", OFF_SITE_NEXT + MALFORMED_NEXT)
def test_login_page_with_off_site_next(user, next):
    login_url = f"{reverse('two_factor:login')}?{urlencode({'next': next})}"
    assert Client().get(login_url).status_code == 200

    response = logged_in_client(user).get(login_url)
    assert response.status_code == 302
    assert response["Location"] == "/"
