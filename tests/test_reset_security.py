from unittest.mock import patch

import pytest
from allauth.account.models import EmailAddress
from allauth.account.signals import password_changed, password_reset, password_set
from django.test import RequestFactory

from peeringdb_server import models, views
from tests.util import mock_csrf_session

OLD_PASSWORD = "original-password-478"
NEW_PASSWORD = "replacement-password-478"

pytestmark = pytest.mark.django_db


@pytest.fixture
def reset_user():
    user = models.User.objects.create_user(
        username="reset-security", email="old@example.net", password=OLD_PASSWORD
    )
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=True
    )
    return user


def submit(view, user, data):
    request = RequestFactory().post("/", data)
    mock_csrf_session(request)
    request.user = user
    return view(request)


def redeem(user, token):
    return submit(
        views.view_password_reset,
        user,
        {
            "target": user.pk,
            "token": token,
            "password": NEW_PASSWORD,
            "password_v": NEW_PASSWORD,
        },
    )


@pytest.mark.parametrize("pending", [False, True])
def test_password_change_revokes_pending_reset(reset_user, pending):
    token = reset_user.password_reset_initiate()[0] if pending else None
    response = submit(
        views.view_password_change,
        reset_user,
        {
            "password_c": OLD_PASSWORD,
            "password": NEW_PASSWORD,
            "password_v": NEW_PASSWORD,
        },
    )
    assert response.status_code == 200
    assert not models.UserPasswordReset.objects.filter(user=reset_user).exists()
    reset_user.refresh_from_db()
    assert reset_user.check_password(NEW_PASSWORD)
    if token:
        assert redeem(reset_user, token).status_code == 400


@pytest.mark.parametrize(
    "current,new,confirmation",
    [
        ("incorrect", NEW_PASSWORD, NEW_PASSWORD),
        (OLD_PASSWORD, "short", "short"),
        (OLD_PASSWORD, NEW_PASSWORD, "mismatch"),
    ],
)
def test_failed_change_keeps_reset_valid(reset_user, current, new, confirmation):
    token, _ = reset_user.password_reset_initiate()
    response = submit(
        views.view_password_change,
        reset_user,
        {"password_c": current, "password": new, "password_v": confirmation},
    )
    assert response.status_code == 400
    assert models.UserPasswordReset.objects.get(user=reset_user).match(token)
    reset_user.refresh_from_db()
    assert reset_user.check_password(OLD_PASSWORD)


def test_ordinary_reset_consumes_token_and_new_reset_works(reset_user):
    token, _ = reset_user.password_reset_initiate()
    assert redeem(reset_user, token).status_code == 200
    assert redeem(reset_user, token).status_code == 400
    reset_user.refresh_from_db()
    assert reset_user.check_password(NEW_PASSWORD)
    fresh, _ = reset_user.password_reset_initiate()
    assert fresh != token
    assert redeem(reset_user, fresh).status_code == 200


@pytest.mark.parametrize("route", ["add_primary", "set_primary", "model_save"])
def test_primary_email_change_revokes_old_mailbox_reset(reset_user, route):
    token, _ = reset_user.password_reset_initiate()
    if route == "add_primary":
        response = submit(
            views.profile_add_email,
            reset_user,
            {
                "password": OLD_PASSWORD,
                "email": "new@example.net",
                "primary": "true",
            },
        )
        assert response.status_code == 200
    elif route == "set_primary":
        email = EmailAddress.objects.create(
            user=reset_user, email="new@example.net", verified=True
        )
        response = submit(
            views.profile_set_primary_email, reset_user, {"email": email.email}
        )
        assert response.status_code == 200
    else:
        reset_user.email = "new@example.net"
        reset_user.save(update_fields=["email"])
    reset_user.refresh_from_db()
    assert reset_user.email == "new@example.net"
    assert not models.UserPasswordReset.objects.filter(user=reset_user).exists()
    assert redeem(reset_user, token).status_code == 400
    fresh, _ = reset_user.password_reset_initiate()
    assert redeem(reset_user, fresh).status_code == 200


def test_secondary_email_and_unrelated_user_save_keep_reset(reset_user):
    token, _ = reset_user.password_reset_initiate()
    response = submit(
        views.profile_add_email,
        reset_user,
        {
            "password": OLD_PASSWORD,
            "email": "secondary@example.net",
            "primary": "false",
        },
    )
    assert response.status_code == 200
    response = submit(
        views.profile_delete_email, reset_user, {"email": "secondary@example.net"}
    )
    assert response.status_code == 200
    reset_user.first_name = "Changed"
    reset_user.save()
    assert models.UserPasswordReset.objects.get(user=reset_user).match(token)


def test_unsaved_email_does_not_revoke_reset(reset_user):
    token, _ = reset_user.password_reset_initiate()
    reset_user.email = "not-saved@example.net"
    reset_user.first_name = "Changed"
    reset_user.save(update_fields=["first_name"])
    assert models.UserPasswordReset.objects.get(user=reset_user).match(token)


@pytest.mark.parametrize("email", ["OLD@example.net", "óld@example.net"])
def test_primary_change_uses_exact_address_comparison(reset_user, email):
    token, _ = reset_user.password_reset_initiate()
    reset_user.email = email
    reset_user.save(update_fields=["email"])
    assert not models.UserPasswordReset.objects.filter(user=reset_user).exists()
    assert redeem(reset_user, token).status_code == 400


@pytest.mark.parametrize("signal", [password_changed, password_reset, password_set])
def test_allauth_password_revocation_retains_user_database_alias(reset_user, signal):
    reset_user.password_reset_initiate()
    user = models.User.objects.using("read").get(pk=reset_user.pk)
    assert user._state.db == "read"
    manager = models.UserPasswordReset.objects
    # The test read alias mirrors default; observe alias selection as well as deletion.
    with patch.object(manager, "using", wraps=manager.using) as using:
        signal.send(sender=models.User, request=RequestFactory().post("/"), user=user)
    using.assert_called_once_with("read")
    assert not manager.filter(user=reset_user).exists()
