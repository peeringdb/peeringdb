from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.apps import apps
from django.contrib.auth import SESSION_KEY
from django.urls import resolve, reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from peeringdb_server.models import Organization, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def login_user(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() - timedelta(days=2)
    settings.MFA_FORCE_HARD_START = timezone.now() - timedelta(days=1)
    user = User.objects.create_user(
        "alternate-login",
        email="alternate@example.net",
        password="login-password-478",
        status="ok",
    )
    EmailAddress.objects.create(
        user=user, email=user.email, verified=True, primary=True
    )
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    return user


def test_allauth_password_login_cannot_bypass_required_passkey(
    client, login_user, settings
):
    org = Organization.objects.create(name="Required passkey", status="ok")
    org.set_org_flag(settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
    org.save()
    org.usergroup.user_set.add(login_user)
    response = client.post(
        reverse("account_login"),
        {"login": login_user.username, "password": "login-password-478"},
    )
    assert SESSION_KEY not in client.session
    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:login")


@pytest.mark.parametrize("method", ["get", "post"])
def test_allauth_login_redirects_to_application_flow(client, method):
    response = getattr(client, method)(reverse("account_login") + "?next=/profile")
    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:login") + "?next=/profile"
    assert SESSION_KEY not in client.session


@pytest.mark.parametrize(
    "path,next_url", [("/api-auth/login/", "/api/net"), ("/cp/login/", "/cp/")]
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_other_password_logins_redirect_to_application_flow(
    client, path, next_url, method
):
    response = getattr(client, method)(f"{path}?next={next_url}")
    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:login") + f"?next={next_url}"


@pytest.mark.parametrize("path", ["/api-auth/login/", "/cp/login/"])
def test_other_password_logins_do_not_authenticate(client, login_user, path):
    login_user.is_staff = True
    login_user.save()
    client.get(reverse("two_factor:login"))
    response = client.post(
        f"{path}?next=/",
        {"username": login_user.username, "password": "login-password-478"},
    )
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login"))
    assert SESSION_KEY not in client.session


@pytest.mark.parametrize(
    "path,target",
    [
        ("/accounts/password/reset/", "reset-password"),
        ("/accounts/password/change/", "user-profile"),
        ("/accounts/email/", "user-profile"),
    ],
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_allauth_routes_redirect_to_application_pages(client, path, target, method):
    response = getattr(client, method)(path)
    assert response.status_code == 302
    assert response["Location"] == reverse(target)


@pytest.mark.parametrize(
    "path",
    [
        "/accounts/signup/",
        "/accounts/logout/",
        "/accounts/inactive/",
        "/accounts/reauthenticate/",
        "/accounts/confirm-email/",
        "/accounts/password/set/",
        "/accounts/password/reset/done/",
        "/accounts/password/reset/key/1-set-password/",
        "/accounts/password/reset/key/done/",
        "/accounts/login/code/confirm/",
        "/accounts/3rdparty/",
        "/accounts/social/connections/",
        "/accounts/google/login/",
        "/accounts/google/login/callback/",
        "/accounts/facebook/login/",
        "/accounts/facebook/login/callback/",
    ],
)
def test_other_allauth_routes_are_gone(client, path):
    assert client.get(path).status_code == 404


def test_allauth_confirm_email_route_remains_available():
    match = resolve(reverse("account_confirm_email", kwargs={"key": "test-key"}))
    assert match.url_name == "account_confirm_email"
    assert match.func.__module__.startswith("allauth.")


def test_allauth_signup_creates_no_account(client):
    client.get(reverse("two_factor:login"))
    response = client.post(
        "/accounts/signup/",
        {
            "username": "allauth-signup",
            "email": "signup@example.net",
            "password1": "abc1234",
            "password2": "abc1234",
        },
    )
    assert response.status_code == 404
    assert not User.objects.filter(username="allauth-signup").exists()
    assert SESSION_KEY not in client.session


def test_allauth_email_management_adds_no_address(client, login_user):
    client.force_login(login_user)
    response = client.post(
        "/accounts/email/", {"email": "added@example.net", "action_add": ""}
    )
    assert response.status_code == 302
    assert not EmailAddress.objects.filter(email="added@example.net").exists()


def test_social_login_is_not_installed():
    assert not apps.is_installed("allauth.socialaccount")


def test_register_page_offers_no_social_login(client):
    response = client.get(reverse("register"))
    assert response.status_code == 200
    assert b"/accounts/google/" not in response.content
    assert b"/accounts/facebook/" not in response.content


@pytest.mark.parametrize("logged_in,target", [(False, "/login"), (True, "/verify")])
def test_allauth_email_confirmation_still_works(client, login_user, logged_in, target):
    address = EmailAddress.objects.create(
        user=login_user, email="confirm@example.net", verified=False
    )
    url = reverse(
        "account_confirm_email", kwargs={"key": EmailConfirmationHMAC(address).key}
    )
    if logged_in:
        client.force_login(login_user)
    assert client.get(url).status_code == 200
    response = client.post(url)
    assert response.status_code == 302
    assert response["Location"] == target
    address.refresh_from_db()
    assert address.verified
