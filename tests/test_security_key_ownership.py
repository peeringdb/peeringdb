"""
A security key verifies only for the account it is registered to (#514).
"""

from datetime import timedelta

import pytest
from django.contrib.auth import SESSION_KEY
from django.urls import reverse
from django.utils import timezone
from django_otp import user_has_device

from peeringdb_server.models import User
from tests.webauthn_util import SoftAuthenticator

pytestmark = pytest.mark.django_db
PASSWORD = "key-ownership-password"


@pytest.fixture
def mfa_not_enforced(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=10)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=20)


@pytest.fixture
def victim(mfa_not_enforced):
    user = User.objects.create_user(
        "key-owner", password=PASSWORD, email="owner@example.net", status="ok"
    )
    key = SoftAuthenticator(b"victim-key")
    key.register(user)
    return user, key


@pytest.fixture
def other_key():
    user = User.objects.create_user(
        "key-other", password=PASSWORD, email="other@example.net", status="ok"
    )
    key = SoftAuthenticator(b"other-key")
    key.register(user)
    return key


def challenge(client, **data):
    response = client.post(reverse("security-keys-request-authentication"), data)
    assert response.status_code == 200
    return response.json()["challenge"]


def login_security_key_step(client, user, key):
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": PASSWORD,
        },
    )
    assert response.status_code == 200
    assert SESSION_KEY not in client.session
    return client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "security-key",
            "security-key-credential": key.assertion(
                challenge(client, username=user.username)
            ),
        },
    )


@pytest.mark.parametrize("own_key", [False, True])
def test_login_second_factor_requires_own_key(client, victim, other_key, own_key):
    user, user_key = victim
    login_security_key_step(client, user, user_key if own_key else other_key)
    assert (client.session.get(SESSION_KEY) == str(user.pk)) is own_key


@pytest.mark.parametrize("own_key", [False, True])
def test_disable_2fa_requires_own_key(client, victim, other_key, own_key):
    user, user_key = victim
    client.force_login(user)
    key = user_key if own_key else other_key
    response = client.post(
        reverse("two_factor:disable"),
        {
            "understand": "on",
            "credential": key.assertion(challenge(client)),
        },
    )
    assert (response.status_code == 302) is own_key
    assert user_has_device(user) is not own_key


@pytest.mark.parametrize("own_key", [False, True])
def test_key_removal_requires_own_key(client, victim, other_key, own_key):
    user, user_key = victim
    client.force_login(user)
    key = user_key if own_key else other_key
    response = client.post(
        "/security_keys/remove",
        {
            "id": user.webauthn_security_keys.get().id,
            "credential": key.assertion(challenge(client)),
        },
    )
    assert (response.status_code == 200) is own_key
    assert user.webauthn_security_keys.exists() is not own_key
