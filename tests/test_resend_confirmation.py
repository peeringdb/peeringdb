import itertools

import pytest
from allauth.account.models import EmailAddress
from django.test import Client, override_settings
from django_otp.plugins.otp_totp.models import TOTPDevice

from peeringdb_server.models import User

pytestmark = pytest.mark.django_db

# the view is rate limited per address, give every request its own
ADDRESSES = (f"192.0.2.{n}" for n in itertools.count(1))


@pytest.fixture
def user():
    user = User.objects.create_user(
        "resend-confirmation",
        email="primary@example.net",
        password="resend-password-478",
        status="ok",
    )
    EmailAddress.objects.create(
        user=user, email=user.email, verified=True, primary=True
    )
    EmailAddress.objects.create(user=user, email="Pending@example.net")
    # MFA enforcement would redirect a user without a second factor
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    return user


def resend(user, **data):
    client = Client(REMOTE_ADDR=next(ADDRESSES))
    client.force_login(user)
    return client.post("/resend_email_confirmation", data)


def test_resend_does_not_add_an_address(user, mailoutbox):
    response = resend(user, email="attacker@example.net")
    assert response.status_code == 400
    assert not EmailAddress.objects.filter(email="attacker@example.net").exists()
    assert not mailoutbox


def test_resend_refuses_a_verified_address(user, mailoutbox):
    response = resend(user, email="primary@example.net")
    assert response.status_code == 400
    assert EmailAddress.objects.get(email="primary@example.net").verified
    assert not mailoutbox


def test_resend_for_an_unverified_address_of_the_user(user, mailoutbox):
    response = resend(user, email="pending@EXAMPLE.net")
    assert response.status_code == 200
    assert user.emailaddress_set.count() == 2
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["Pending@example.net"]


def test_resend_without_email_uses_the_account_address(user, mailoutbox):
    EmailAddress.objects.filter(email=user.email).delete()
    response = resend(user)
    assert response.status_code == 200
    assert EmailAddress.objects.filter(user=user, email=user.email).exists()
    assert mailoutbox[0].to == [user.email]


def test_confirmation_link_is_built_from_base_url(user, mailoutbox, settings):
    settings.BASE_URL = "https://www.peeringdb.example"
    client = Client(REMOTE_ADDR=next(ADDRESSES), HTTP_HOST="other.example")
    client.force_login(user)
    with override_settings(ALLOWED_HOSTS=["other.example"]):
        response = client.post(
            "/resend_email_confirmation", {"email": "pending@example.net"}
        )
    assert response.status_code == 200
    body = mailoutbox[0].body
    assert "https://www.peeringdb.example/accounts/confirm-email/" in body
    assert "other.example" not in body


def test_confirmation_link_without_request_uses_base_url(user, mailoutbox, settings):
    settings.BASE_URL = "https://www.peeringdb.example"
    user.send_email_confirmation(email="Pending@example.net")
    assert "https://www.peeringdb.example/accounts/confirm-email/" in mailoutbox[0].body
