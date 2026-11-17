"""
Password login asks for every WebAuthn key of the account as the second
factor, passkeys included (#549). The passkey login path is unchanged.
"""

from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import SESSION_KEY
from django.urls import reverse
from django.utils import timezone

from peeringdb_server.models import User
from tests.webauthn_util import SoftAuthenticator, b64url

pytestmark = pytest.mark.django_db
PASSWORD = "security-key-step-password-549"


@pytest.fixture
def mfa_enforced(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() - timedelta(days=2)
    settings.MFA_FORCE_HARD_START = timezone.now() - timedelta(days=1)


def make_user(name):
    user = User.objects.create_user(
        name, email=f"{name}@example.net", password=PASSWORD, status="ok"
    )
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=True
    )
    return user


def password_login(client, user):
    return client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": PASSWORD,
        },
    )


def second_factor_challenge(client):
    # what the security-key step's script (init_two_factor) requests
    response = client.post(reverse("security-keys-request-authentication"), {})
    assert response.status_code == 200
    return response.json()


def security_key_step(client, credential):
    return client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "security-key",
            "security-key-credential": credential,
        },
    )


@pytest.mark.parametrize("passkey_login", [True, False])
def test_password_login_asks_for_the_account_key(client, mfa_enforced, passkey_login):
    user = make_user("key-step")
    key = SoftAuthenticator(b"key-step")
    key.register(user, passkey_login=passkey_login)

    response = password_login(client, user)
    assert response.status_code == 200
    assert SESSION_KEY not in client.session
    assert response.context["wizard"]["steps"].current == "security-key"

    options = second_factor_challenge(client)
    assert [c["id"] for c in options["allowCredentials"]] == [b64url(b"key-step")]

    # possession is the second factor here; no user verification needed
    response = security_key_step(
        client, key.assertion(options["challenge"], user_verified=False)
    )
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["amr"] == ["pwd", "swk", "mfa"]
    assert client.get(reverse("user-profile")).status_code == 200


def test_password_login_rejects_another_accounts_key(client, mfa_enforced):
    user = make_user("key-step-owner")
    SoftAuthenticator(b"own-passkey").register(user, passkey_login=True)
    other_key = SoftAuthenticator(b"other-passkey")
    other_key.register(make_user("key-step-other"), passkey_login=True)

    password_login(client, user)
    options = second_factor_challenge(client)
    response = security_key_step(client, other_key.assertion(options["challenge"]))
    assert response.status_code == 200
    assert SESSION_KEY not in client.session


def test_passkey_login_path_unchanged(client, mfa_enforced):
    user = make_user("key-step-passkey")
    key = SoftAuthenticator(b"passkey-path")
    key.register(user, passkey_login=True)

    client.get(reverse("two_factor:login"))
    response = client.post(
        reverse("security-keys-request-authentication"), {"for_login": 1}
    )
    response = client.post(
        reverse("two_factor:login"),
        {
            "credential": key.assertion(
                response.json()["challenge"], user_verified=True, user=user
            )
        },
    )
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["amr"] == ["swk"]
