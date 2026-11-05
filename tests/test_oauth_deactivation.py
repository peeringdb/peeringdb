"""
OAuth tokens do not outlive the deactivation or closure of their account.
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from oauth2_provider.models import AccessToken, DeviceGrant, Grant, RefreshToken

from peeringdb_server.admin import UserPermission
from peeringdb_server.models import User

from .util import create_oauth_application, reset_group_ids

pytestmark = pytest.mark.django_db

CLIENT_ID = "deactivation-client"
CLIENT_SECRET = "deactivation-secret"


def create_user(username):
    return User.objects.create_user(
        username, f"{username}@localhost", "deactivation-pw", status="ok"
    )


def issue_tokens(user, app, name, scope="profile"):
    access_token = AccessToken.objects.create(
        user=user,
        application=app,
        token=f"{name}-access",
        expires=timezone.now() + timedelta(hours=1),
        scope=scope,
    )
    refresh_token = RefreshToken.objects.create(
        user=user,
        application=app,
        token=f"{name}-refresh",
        access_token=access_token,
    )
    Grant.objects.create(
        user=user,
        application=app,
        code=f"{name}-code",
        expires=timezone.now() + timedelta(minutes=1),
        redirect_uri="https://example.com",
        scope=scope,
    )
    DeviceGrant.objects.create(
        user=user,
        client_id=app.client_id,
        device_code=f"{name}-device",
        user_code=f"{name}-user-code",
        expires=timezone.now() + timedelta(minutes=10),
        status=DeviceGrant.AUTHORIZED,
    )
    return access_token, refresh_token


def assert_revoked(user, refresh_token):
    assert not AccessToken.objects.filter(user=user).exists()
    assert not Grant.objects.filter(user=user).exists()
    assert not DeviceGrant.objects.filter(user=user).exists()
    refresh_token.refresh_from_db()
    assert refresh_token.revoked is not None


def refresh(refresh_token):
    return Client().post(
        "/oauth2/token/",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )


@pytest.fixture
def user():
    reset_group_ids()
    return create_user("deactivation")


@pytest.fixture
def app(user):
    return create_oauth_application(user, CLIENT_ID, CLIENT_SECRET)


def test_deactivation_revokes_tokens(user, app):
    _, refresh_token = issue_tokens(user, app, "deactivate")
    response = Client().get(
        "/profile/v1", HTTP_AUTHORIZATION="Bearer deactivate-access"
    )
    assert response.status_code == 200

    user.is_active = False
    user.save()

    assert_revoked(user, refresh_token)
    response = Client().get(
        "/profile/v1", HTTP_AUTHORIZATION="Bearer deactivate-access"
    )
    assert response.status_code == 403
    assert refresh("deactivate-refresh").status_code == 400


def test_close_account_revokes_tokens(user, app):
    _, refresh_token = issue_tokens(user, app, "close")

    user.close_account()

    user.refresh_from_db()
    assert not user.is_active and user.email is None
    assert_revoked(user, refresh_token)
    response = Client().get("/profile/v1", HTTP_AUTHORIZATION="Bearer close-access")
    assert response.status_code == 403


def assert_stays_revoked_after_reactivation(user, access_token, refresh_token):
    user.refresh_from_db()
    user.is_active = True
    user.save()
    response = Client().get(
        "/profile/v1", HTTP_AUTHORIZATION=f"Bearer {access_token.token}"
    )
    assert response.status_code == 403
    assert refresh(refresh_token.token).status_code == 400


def test_proxy_deactivation_revokes_tokens(user, app):
    """
    pre_save is sent with the proxy class, so a receiver bound to User alone
    would miss this.
    """

    access_token, refresh_token = issue_tokens(user, app, "staff")

    user_permission = UserPermission.objects.get(pk=user.pk)
    user_permission.is_active = False
    user_permission.save()

    assert_revoked(user, refresh_token)
    assert_stays_revoked_after_reactivation(user, access_token, refresh_token)


def test_admin_deactivation_revokes_tokens(user, app):
    """
    Staff deactivate a user by unticking Active on the User Permission page.
    """

    access_token, refresh_token = issue_tokens(user, app, "staff")
    admin = User.objects.create_user(
        "deactivation-admin", "deactivation-admin@localhost", "admin-pw"
    )
    admin.is_superuser = admin.is_staff = True
    admin.save()
    # without a second factor the MFA middleware redirects staff
    TOTPDevice.objects.create(user=admin, name="phone", confirmed=True)
    client = Client()
    client.force_login(admin)

    # an unticked checkbox is left out of the post, so is_active is False
    response = client.post(
        reverse("admin:peeringdb_server_userpermission_change", args=[user.id]),
        {
            "affiliation_requests-TOTAL_FORMS": 0,
            "affiliation_requests-INITIAL_FORMS": 0,
            "affiliation_requests-MIN_NUM_FORMS": 0,
            "affiliation_requests-MAX_NUM_FORMS": 1000,
            "grainy_permissions-TOTAL_FORMS": 0,
            "grainy_permissions-INITIAL_FORMS": 0,
            "grainy_permissions-MIN_NUM_FORMS": 0,
            "grainy_permissions-MAX_NUM_FORMS": 1000,
            "_save": "Save",
        },
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert not user.is_active
    assert_revoked(user, refresh_token)
    assert_stays_revoked_after_reactivation(user, access_token, refresh_token)


def test_deactivation_leaves_other_users_tokens(user, app):
    other = create_user("deactivation-other")
    issue_tokens(other, app, "other")
    issue_tokens(user, app, "deactivate")

    user.is_active = False
    user.save()

    assert AccessToken.objects.filter(user=other).count() == 1
    assert Grant.objects.filter(user=other).count() == 1
    assert DeviceGrant.objects.filter(user=other).count() == 1
    assert RefreshToken.objects.get(user=other).revoked is None


def test_saving_active_user_keeps_tokens(user, app):
    _, refresh_token = issue_tokens(user, app, "active")

    user.first_name = "Changed"
    user.save()
    user.is_active = False
    # a save that does not write is_active does not deactivate anything
    user.save(update_fields=["first_name"])

    assert AccessToken.objects.filter(user=user).exists()
    refresh_token.refresh_from_db()
    assert refresh_token.revoked is None


def test_inactive_user_tokens_are_refused(user, app):
    """
    Tokens that never went through the deactivation signal, such as after a
    queryset update, are refused for an inactive user as well.
    """

    # openid, so userinfo would answer if the token were accepted
    issue_tokens(user, app, "bulk", scope="openid profile")
    User.objects.filter(pk=user.pk).update(is_active=False)

    client = Client()
    assert (
        client.get("/profile/v1", HTTP_AUTHORIZATION="Bearer bulk-access").status_code
        == 403
    )
    assert (
        client.get(
            "/oauth2/userinfo/", HTTP_AUTHORIZATION="Bearer bulk-access"
        ).status_code
        == 401
    )
    assert refresh("bulk-refresh").status_code == 400
    response = client.post(
        "/oauth2/token/",
        {
            "grant_type": "authorization_code",
            "code": "bulk-code",
            "redirect_uri": "https://example.com",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_active_user_can_refresh(user, app):
    issue_tokens(user, app, "control")
    response = refresh("control-refresh")
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_token_without_user_is_refused(app):
    """
    Client credentials tokens have no user.
    """

    AccessToken.objects.create(
        user=None,
        application=app,
        token="no-user-access",
        expires=timezone.now() + timedelta(hours=1),
        scope="openid profile",
    )
    client = Client()
    assert (
        client.get(
            "/profile/v1", HTTP_AUTHORIZATION="Bearer no-user-access"
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/oauth2/userinfo/", HTTP_AUTHORIZATION="Bearer no-user-access"
        ).status_code
        == 401
    )
