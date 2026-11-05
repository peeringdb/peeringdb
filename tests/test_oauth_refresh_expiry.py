"""
OAuth refresh tokens expire OAUTH2_REFRESH_TOKEN_EXPIRE_SECONDS after their
last access token did, enforced when the client refreshes.
"""

import os
from datetime import timedelta

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, RefreshToken
from oauth2_provider.settings import oauth2_settings

from mainsite.settings import _set_option
from peeringdb_server.models import User

from .util import create_oauth_application, reset_group_ids

pytestmark = pytest.mark.django_db

CLIENT_ID = "refresh-expiry-client"
CLIENT_SECRET = "refresh-expiry-secret"
NINETY_DAYS = 90 * 24 * 60 * 60


@pytest.fixture
def app():
    reset_group_ids()
    user = User.objects.create_user(
        "refresh-expiry", "refresh-expiry@localhost", "refresh-expiry-pw", status="ok"
    )
    return create_oauth_application(user, CLIENT_ID, CLIENT_SECRET)


def issue_tokens(app, access_expired_days_ago):
    access_token = AccessToken.objects.create(
        user=app.user,
        application=app,
        token="refresh-expiry-access",
        expires=timezone.now() - timedelta(days=access_expired_days_ago),
        scope="profile",
    )
    RefreshToken.objects.create(
        user=app.user,
        application=app,
        token="refresh-expiry-refresh",
        access_token=access_token,
    )


def refresh():
    return Client().post(
        "/oauth2/token/",
        {
            "grant_type": "refresh_token",
            "refresh_token": "refresh-expiry-refresh",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )


@pytest.mark.parametrize(
    "env,expected", [(None, NINETY_DAYS), ("0", 0), ("3600", 3600)]
)
def test_setting_from_env(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("OAUTH2_REFRESH_TOKEN_EXPIRE_SECONDS", raising=False)
    else:
        monkeypatch.setenv("OAUTH2_REFRESH_TOKEN_EXPIRE_SECONDS", env)
    context = {}
    _set_option("OAUTH2_REFRESH_TOKEN_EXPIRE_SECONDS", NINETY_DAYS, context)
    assert context["OAUTH2_REFRESH_TOKEN_EXPIRE_SECONDS"] == expected


@pytest.mark.skipif(
    "OAUTH2_REFRESH_TOKEN_EXPIRE_SECONDS" in os.environ,
    reason="the environment overrides the default",
)
def test_default_reaches_oauth_toolkit():
    assert settings.OAUTH2_REFRESH_TOKEN_EXPIRE_SECONDS == NINETY_DAYS
    assert oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS == NINETY_DAYS


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "REFRESH_TOKEN_EXPIRE_SECONDS": NINETY_DAYS,
    }
)
def test_refresh_within_window(app):
    issue_tokens(app, access_expired_days_ago=89)
    response = refresh()
    assert response.status_code == 200
    assert response.json()["refresh_token"]


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "REFRESH_TOKEN_EXPIRE_SECONDS": NINETY_DAYS,
    }
)
def test_refresh_after_window_is_refused(app):
    issue_tokens(app, access_expired_days_ago=91)
    response = refresh()
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@override_settings(
    OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "REFRESH_TOKEN_EXPIRE_SECONDS": 0}
)
def test_zero_turns_expiry_off(app):
    issue_tokens(app, access_expired_days_ago=365)
    assert refresh().status_code == 200
