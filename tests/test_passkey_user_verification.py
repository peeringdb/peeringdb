"""
Passkey login and passkey registration require user verification; the
security key second factor does not (#514).
"""

from datetime import timedelta

import pytest
from django.contrib.auth import SESSION_KEY
from django.urls import reverse
from django.utils import timezone
from django_security_keys.models import SecurityKey

from peeringdb_server.models import User
from tests.webauthn_util import SoftAuthenticator

pytestmark = pytest.mark.django_db
PASSWORD = "passkey-uv-password"


@pytest.fixture
def user(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=10)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=20)
    return User.objects.create_user(
        "passkey-uv", password=PASSWORD, email="uv@example.net", status="ok"
    )


def authentication_options(client, **data):
    response = client.post(reverse("security-keys-request-authentication"), data)
    assert response.status_code == 200
    return response.json()


def registration_options(client, passkey):
    url = reverse("security-keys-request-registration")
    if passkey:
        url += "?passkey=1"
    response = client.post(url, {"password": PASSWORD})
    assert response.status_code == 200
    return response.json()


def test_passkey_login_options_require_user_verification(client):
    options = authentication_options(client, for_login=1)
    assert options["userVerification"] == "required"


def test_second_factor_options_keep_preferred(client, user):
    SoftAuthenticator(b"second-factor").register(user)
    client.force_login(user)
    options = authentication_options(client)
    assert options["userVerification"] == "preferred"
    assert options["allowCredentials"]


@pytest.mark.parametrize("user_verified", [False, True])
def test_passkey_login_requires_user_verification(client, user, user_verified):
    key = SoftAuthenticator(b"passkey-login")
    key.register(user, passkey_login=True)
    client.get(reverse("two_factor:login"))
    options = authentication_options(client, for_login=1)
    response = client.post(
        reverse("two_factor:login"),
        {
            "credential": key.assertion(
                options["challenge"], user_verified=user_verified, user=user
            )
        },
    )
    assert (client.session.get(SESSION_KEY) == str(user.pk)) is user_verified
    if not user_verified:
        assert response.status_code == 200
        assert b"asks for your PIN or biometric" in response.content


@pytest.mark.parametrize("passkey", [False, True])
def test_registration_options_request_user_verification_for_passkeys(
    client, user, passkey
):
    client.force_login(user)
    selection = registration_options(client, passkey).get("authenticatorSelection", {})
    assert (selection.get("userVerification") == "required") is passkey


@pytest.mark.parametrize(
    "passkey_login,user_verified,accepted",
    [
        (True, False, False),
        (True, True, True),
        (False, False, True),
    ],
)
def test_passkey_registration_requires_user_verification(
    client, user, passkey_login, user_verified, accepted
):
    client.force_login(user)
    options = registration_options(client, passkey_login)
    key = SoftAuthenticator(b"new-key")
    response = client.post(
        "/security_keys/add",
        {
            "password": PASSWORD,
            "name": "new key",
            "passkey_login": "true" if passkey_login else "false",
            "credential": key.attestation(
                options["challenge"], user_verified=user_verified
            ),
        },
    )
    assert (response.status_code == 200) is accepted
    assert SecurityKey.objects.filter(user=user).exists() is accepted
    if not accepted:
        assert response.status_code == 400
        assert "PIN or biometric" in response.json()["non_field_errors"][0]


def test_stale_registration_challenge_is_a_400(client, user):
    """
    Options requested again (e.g. in a second tab) replace the challenge; the
    first registration attempt is rejected, not an error page.
    """

    client.force_login(user)
    stale = registration_options(client, False)["challenge"]
    registration_options(client, False)
    response = client.post(
        "/security_keys/add",
        {
            "password": PASSWORD,
            "name": "stale",
            "passkey_login": "false",
            "credential": SoftAuthenticator(b"stale-key").attestation(stale),
        },
    )
    assert response.status_code == 400
    assert response.json()["non_field_errors"]
    assert not SecurityKey.objects.filter(user=user).exists()
