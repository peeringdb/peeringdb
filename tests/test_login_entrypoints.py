from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
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
    "name,kwargs",
    [
        ("account_email", {}),
        ("account_confirm_email", {"key": "test-key"}),
        ("socialaccount_connections", {}),
        ("google_callback", {}),
        ("facebook_callback", {}),
    ],
)
def test_other_allauth_routes_remain_available(name, kwargs):
    match = resolve(reverse(name, kwargs=kwargs))
    assert match.url_name == name
    assert match.func.__module__.startswith("allauth.")
