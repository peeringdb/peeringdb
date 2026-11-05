"""
Creating a user API key and changing a security key's passkey login need the
current password (#514).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from peeringdb_server.models import User, UserAPIKey
from tests.webauthn_util import SoftAuthenticator

pytestmark = pytest.mark.django_db
PASSWORD = "key-reauth-password"


@pytest.fixture
def user(client, settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=10)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=20)
    user = User.objects.create_user(
        "key-reauth", password=PASSWORD, email="reauth@example.net", status="ok"
    )
    client.force_login(user)
    return user


def add_key(client, **data):
    return client.post(
        "/user_keys/add", {"name": "reauth", "readonly": "false", **data}
    )


def toggle(client, key, **data):
    return client.post(
        "/security_keys/update-security-key",
        {"id": key.id, "passkey_login": "true", **data},
    )


@pytest.mark.parametrize(
    "password,status", [(None, 400), ("wrong", 401), (PASSWORD, 200)]
)
def test_user_api_key_creation_requires_password(client, user, password, status):
    data = {"password": password} if password else {}
    response = add_key(client, **data)
    assert response.status_code == status
    assert UserAPIKey.objects.filter(user=user).exists() is (status == 200)
    if status == 200:
        assert response.json()["key"]


@pytest.mark.parametrize(
    "password,status", [(None, 400), ("wrong", 401), (PASSWORD, 200)]
)
def test_passkey_login_toggle_requires_password(client, user, password, status):
    key = SoftAuthenticator(b"toggle").register(user)
    data = {"password": password} if password else {}
    response = toggle(client, key, **data)
    assert response.status_code == status
    key.refresh_from_db()
    assert key.passkey_login is (status == 200)


def test_password_retry_is_not_replayed_from_negative_cache(client, user, settings):
    settings.NEGATIVE_CACHE_ENABLED = True
    key = SoftAuthenticator(b"retry").register(user)

    assert add_key(client, password="wrong").status_code == 401
    response = add_key(client, password=PASSWORD)
    assert response.status_code == 200
    assert response.headers.get("X-Cached-Response") is None

    assert toggle(client, key, password="wrong").status_code == 401
    response = toggle(client, key, password=PASSWORD)
    assert response.status_code == 200
    assert response.headers.get("X-Cached-Response") is None


def test_anonymous_toggle_is_sent_to_login(client):
    response = client.post(
        "/security_keys/update-security-key",
        {"id": 1, "passkey_login": "true", "password": "anything"},
    )
    assert response.status_code == 302
