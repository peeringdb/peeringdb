from datetime import timedelta

import pytest
from django.contrib.auth import SESSION_KEY
from django.test import Client
from django.utils import timezone
from oauth2_provider.models import AccessToken

from peeringdb_server.models import User

pytestmark = pytest.mark.django_db
PASSWORD = "close-security-password"


@pytest.fixture
def close_user():
    return User.objects.create_user(
        username="close-security",
        email="close@example.net",
        password=PASSWORD,
        status="ok",
    )


def test_bearer_token_cannot_close_account_even_with_password(client, close_user):
    AccessToken.objects.create(
        user=close_user,
        token="close-security-token",
        scope="profile email",
        expires=timezone.now() + timedelta(hours=1),
    )
    response = client.post(
        "/profile/close",
        {"password": PASSWORD},
        HTTP_AUTHORIZATION="Bearer close-security-token",
    )
    assert response.status_code == 403
    assert SESSION_KEY not in client.session
    close_user.refresh_from_db()
    assert close_user.is_active
    assert close_user.email == "close@example.net"


def test_session_closure_requires_password(client, close_user):
    client.force_login(close_user)
    response = client.post("/profile/close", {"password": "wrong"})
    assert response.status_code == 400
    close_user.refresh_from_db()
    assert close_user.is_active
    response = client.post("/profile/close", {"password": PASSWORD})
    assert response.status_code == 200
    close_user.refresh_from_db()
    assert not close_user.is_active
    assert SESSION_KEY not in client.session


def test_session_closure_still_requires_csrf(close_user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(close_user)
    response = client.post("/profile/close", {"password": PASSWORD})
    assert response.status_code == 403
    close_user.refresh_from_db()
    assert close_user.is_active
