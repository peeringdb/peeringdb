"""
Security key authentication options never name a user's credentials to a
client that has not verified that user's first factor (#514).
"""

from datetime import timedelta

import pytest
from django.contrib.auth import SESSION_KEY
from django.urls import reverse
from django.utils import timezone

from peeringdb_server.models import Organization, User
from tests.webauthn_util import SoftAuthenticator, b64url

pytestmark = pytest.mark.django_db
PASSWORD = "key-options-password"


@pytest.fixture
def users(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=10)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=20)
    keys = {}
    for name in ("options-a", "options-b"):
        user = User.objects.create_user(
            name, password=PASSWORD, email=f"{name}@example.net", status="ok"
        )
        key = SoftAuthenticator(name.encode())
        key.register(user)
        keys[name] = (user, b64url(key.credential_id))
    return keys


def options(client, **data):
    return client.post(reverse("security-keys-request-authentication"), data)


def credential_ids(response):
    assert response.status_code == 200
    return [c["id"] for c in response.json()["allowCredentials"]]


def test_anonymous_username_lookup_is_refused(client, users):
    known = options(client, username="options-a")
    unknown = options(client, username="no-such-user")
    assert known.status_code == unknown.status_code == 400
    assert known.json() == unknown.json()


def test_passkey_login_options_name_no_credentials(client, users):
    response = options(client, for_login=1, username="options-a")
    assert response.status_code == 200
    assert "allowCredentials" not in response.json() or not credential_ids(response)


def test_login_second_factor_uses_wizard_user(client, users):
    user, credential_id = users["options-a"]
    client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": PASSWORD,
        },
    )
    assert credential_ids(options(client)) == [credential_id]
    assert credential_ids(options(client, username="options-b")) == [credential_id]


def test_wrong_password_does_not_unlock_options(client, users):
    client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": "options-a",
            "auth-password": "wrong",
        },
    )
    assert options(client, username="options-a").status_code == 400


def test_logged_in_user_gets_own_credentials(client, users):
    user, credential_id = users["options-a"]
    client.force_login(user)
    assert credential_ids(options(client, username="options-b")) == [credential_id]


def test_login_with_both_flags_is_refused(client, users):
    response = options(client, for_login=1, ignore_credential_filter=1)
    assert response.status_code == 400


def test_wizard_user_comes_before_signed_in_user(client, users):
    # e.g. an OAuth authorize login while another account is signed in
    signed_in, _ = users["options-a"]
    wizard, credential_id = users["options-b"]
    client.force_login(signed_in)
    client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": wizard.username,
            "auth-password": PASSWORD,
        },
    )
    assert credential_ids(options(client)) == [credential_id]


def test_expired_wizard_user_is_forgotten(client, users, settings):
    settings.TWO_FACTOR_LOGIN_TIMEOUT = 60
    client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": "options-a",
            "auth-password": PASSWORD,
        },
    )
    session = client.session
    session["wizard_login_view"]["authentication_time"] -= 120
    session.save()
    assert options(client).status_code == 400


def test_passkey_login_then_security_key_second_factor(client, users, settings):
    user, _ = users["options-a"]
    org = Organization.objects.create(name="Passkey plus key", status="ok")
    org.set_org_flag(settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    org.save()
    org.usergroup.user_set.add(user)
    passkey = SoftAuthenticator(b"options-a-passkey")
    passkey.register(user, passkey_login=True)
    second_factor = SoftAuthenticator(b"options-a-second")
    second_factor.register(user)

    client.get(reverse("two_factor:login"))
    challenge = options(client, for_login=1).json()["challenge"]
    response = client.post(
        reverse("two_factor:login"),
        {"credential": passkey.assertion(challenge, user_verified=True, user=user)},
    )
    assert response.status_code == 200
    assert SESSION_KEY not in client.session

    response = options(client)
    assert b64url(passkey.credential_id) not in credential_ids(response)
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "security-key",
            "security-key-credential": second_factor.assertion(
                response.json()["challenge"]
            ),
        },
    )
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["amr"] == ["swk", "swk", "mfa"]


def case_variant(credential_id):
    i = next(i for i, c in enumerate(credential_id) if c.isalpha())
    return credential_id[:i] + credential_id[i].swapcase() + credential_id[i + 1 :]


def test_passkey_case_variant_is_not_a_second_factor(client, users, settings):
    """
    The database matches credential ids case-insensitively; a case variant of
    the login passkey's id must not count as another key.
    """

    user, _ = users["options-a"]
    org = Organization.objects.create(name="Passkey case variant", status="ok")
    org.set_org_flag(settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    org.save()
    org.usergroup.user_set.add(user)
    passkey = SoftAuthenticator(b"options-a-passkey")
    passkey.register(user, passkey_login=True)

    client.get(reverse("two_factor:login"))
    challenge = options(client, for_login=1).json()["challenge"]
    client.post(
        reverse("two_factor:login"),
        {"credential": passkey.assertion(challenge, user_verified=True, user=user)},
    )
    assert SESSION_KEY not in client.session

    variant = case_variant(b64url(passkey.credential_id))
    assert variant != b64url(passkey.credential_id)
    client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "security-key",
            "security-key-credential": passkey.assertion(
                options(client).json()["challenge"], credential_id=variant
            ),
        },
    )
    assert SESSION_KEY not in client.session


def test_passkey_login_with_case_variant_id_is_refused(client, users):
    user, _ = users["options-a"]
    passkey = SoftAuthenticator(b"options-a-passkey")
    passkey.register(user, passkey_login=True)

    client.get(reverse("two_factor:login"))
    challenge = options(client, for_login=1).json()["challenge"]
    client.post(
        reverse("two_factor:login"),
        {
            "credential": passkey.assertion(
                challenge,
                user_verified=True,
                user=user,
                credential_id=case_variant(b64url(passkey.credential_id)),
            )
        },
    )
    assert SESSION_KEY not in client.session
