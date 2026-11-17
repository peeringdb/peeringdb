"""
An organization's hold on MFA setup (`mfa_setup_required`) is lifted only by a
second factor the user's organizations accept (#550).
"""

from base64 import b32decode
from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import SESSION_KEY
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_email.models import EmailDevice
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from peeringdb_server.models import Organization, User
from peeringdb_server.util import PASSKEY_BACKEND
from tests.webauthn_util import SoftAuthenticator

pytestmark = pytest.mark.django_db
PASSWORD = "org-mfa-hold-password-550"
PASSWORD_BACKEND = "allauth.account.auth_backends.AuthenticationBackend"


@pytest.fixture
def mfa_enforced(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() - timedelta(days=2)
    settings.MFA_FORCE_HARD_START = timezone.now() - timedelta(days=1)


def make_member(name, settings, *flags):
    user = User.objects.create_user(
        name, email=f"{name}@example.net", password=PASSWORD, status="ok"
    )
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=True
    )
    org = Organization.objects.create(name=f"Org {name}", status="ok")
    for flag in flags:
        org.set_org_flag(getattr(settings, flag), True)
    org.save()
    org.usergroup.user_set.add(user)
    return user


def add_factor(user, factor):
    if factor == "totp_default":
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    elif factor == "email_default":
        EmailDevice.objects.create(user=user, name="default", confirmed=True)
    elif factor == "security_key":
        SoftAuthenticator(b"hold-2fa-key").register(user, passkey_login=False)
    elif factor == "passkey":
        SoftAuthenticator(b"hold-passkey").register(user, passkey_login=True)
    elif factor == "backup_tokens":
        device = StaticDevice.objects.create(user=user, name="backup", confirmed=True)
        StaticToken.objects.create(device=device, token="hold-backup-code")


def password_login(client, user):
    return client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": PASSWORD,
        },
    )


def held(client):
    response = client.get(reverse("user-profile"))
    if response.status_code == 302:
        assert response.url == reverse("two_factor:profile")
        assert client.session.get("mfa_setup_required")
        return True
    assert response.status_code == 200
    return False


def submit_otp(client, user):
    """
    Answers the token step with the account's default device.
    """
    totp_device = TOTPDevice.objects.filter(user=user, name="default").first()
    if totp_device:
        token = str(totp(totp_device.bin_key)).zfill(6)
    else:
        # the token step emailed a code when it rendered
        token = EmailDevice.objects.get(user=user, name="default").token
    return client.post(
        reverse("two_factor:login"),
        {"login_view-current_step": "token", "token-otp_token": token},
    )


def answers(client, paths):
    return [
        (response.status_code, response.get("Location"))
        for response in (client.post(path) for path in paths)
    ]


ENROLLMENT_PATHS = [
    reverse("profile_passkey"),
    reverse("security-keys-request-registration"),
    reverse("security-keys-request-registration") + "?passkey=1",
    "/security_keys/add",
]


@pytest.mark.parametrize("factor", ["totp_default", "email_default"])
def test_totp_disabled_password_login_asks_existing_factor_then_holds(
    client, settings, mfa_enforced, factor
):
    user = make_member("hold-pwd", settings, "ORG_FLAGS_DISABLE_TOTP")
    add_factor(user, factor)

    response = password_login(client, user)
    assert response.status_code == 200
    assert response.context["wizard"]["steps"].current == "token"
    assert SESSION_KEY not in client.session
    # without the token, enrollment answers as for an anonymous caller
    assert answers(client, ENROLLMENT_PATHS) == answers(Client(), ENROLLMENT_PATHS)

    response = submit_otp(client, user)
    assert response.status_code == 302
    assert response.url == reverse("two_factor:profile")
    assert client.session[SESSION_KEY] == str(user.pk)
    assert held(client)
    # still held on later requests
    assert held(client)

    # a key enrolled in the held session lifts the hold
    SoftAuthenticator(b"hold-enrolled").register(user, passkey_login=False)
    assert not held(client)


def test_totp_disabled_password_login_without_factor_is_held(
    client, settings, mfa_enforced
):
    user = make_member("hold-none", settings, "ORG_FLAGS_DISABLE_TOTP")

    response = password_login(client, user)
    assert response.status_code == 302
    assert response.url == reverse("two_factor:profile")
    assert held(client)


def test_passkey_enrollment_session_asks_existing_factor_first(
    client, settings, mfa_enforced
):
    """
    Organizations that disable password login and TOTP: the passkey
    enrollment session starts only after the account's default device (#552).
    """
    user = make_member(
        "enroll-pwd",
        settings,
        "ORG_FLAGS_DISABLE_TOTP",
        "ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH",
    )
    add_factor(user, "totp_default")

    response = password_login(client, user)
    assert response.status_code == 200
    assert response.context["wizard"]["steps"].current == "token"
    assert SESSION_KEY not in client.session
    assert answers(client, ENROLLMENT_PATHS) == answers(Client(), ENROLLMENT_PATHS)

    response = submit_otp(client, user)
    assert response.status_code == 302
    assert response.url == reverse("profile_passkey")
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["passkey_setup_required"]


def test_hold_survives_login_over_another_session(client, settings, mfa_enforced):
    client.force_login(make_member("hold-other", settings))
    user = make_member("hold-switch", settings, "ORG_FLAGS_DISABLE_TOTP")
    add_factor(user, "totp_default")

    password_login(client, user)
    response = submit_otp(client, user)
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert held(client)


@pytest.mark.parametrize(
    "flags, backend, factor, cleared",
    [
        # TOTP disabled: no django-otp device counts, keys do
        (["ORG_FLAGS_DISABLE_TOTP"], PASSWORD_BACKEND, "totp_default", False),
        (["ORG_FLAGS_DISABLE_TOTP"], PASSWORD_BACKEND, "email_default", False),
        (["ORG_FLAGS_DISABLE_TOTP"], PASSWORD_BACKEND, "security_key", True),
        (["ORG_FLAGS_DISABLE_TOTP"], PASSWORD_BACKEND, "passkey", True),
        # MFA after a passkey: passkeys do not count, other factors do
        (["ORG_FLAGS_PASSKEY_REQUIRE_MFA"], PASSKEY_BACKEND, "passkey", False),
        (["ORG_FLAGS_PASSKEY_REQUIRE_MFA"], PASSKEY_BACKEND, "security_key", True),
        (["ORG_FLAGS_PASSKEY_REQUIRE_MFA"], PASSKEY_BACKEND, "totp_default", True),
        (
            ["ORG_FLAGS_PASSKEY_REQUIRE_MFA", "ORG_FLAGS_DISABLE_TOTP"],
            PASSKEY_BACKEND,
            "totp_default",
            False,
        ),
        # backup tokens never count on their own
        (["ORG_FLAGS_PASSKEY_REQUIRE_MFA"], PASSKEY_BACKEND, "backup_tokens", False),
        (["ORG_FLAGS_DISABLE_TOTP"], PASSWORD_BACKEND, "backup_tokens", False),
    ],
)
def test_hold_lifted_only_by_an_accepted_factor(
    client, settings, mfa_enforced, flags, backend, factor, cleared
):
    user = make_member("hold-clear", settings, *flags)
    if backend == PASSKEY_BACKEND and factor != "passkey":
        add_factor(user, "passkey")
    add_factor(user, factor)
    client.force_login(user, backend=backend)
    session = client.session
    session["mfa_setup_required"] = True
    session.save()

    assert held(client) is not cleared


def complete_totp_setup(client):
    def step(name, **data):
        payload = {"two_factor_setup_view-current_step": name}
        payload.update({f"{name}-{key}": value for key, value in data.items()})
        return client.post(reverse("two_factor:setup"), payload)

    step("password", password=PASSWORD)
    step("welcome")
    step("method", method="generator")
    key = b32decode(client.session["django_two_factor-qr_secret_key"])
    return step("generator", token=str(totp(key)).zfill(6))


@pytest.mark.parametrize(
    "flag, cleared",
    [("ORG_FLAGS_DISABLE_TOTP", False), ("ORG_FLAGS_PASSKEY_REQUIRE_MFA", True)],
)
def test_totp_setup_lifts_hold_only_where_totp_is_allowed(
    client, settings, mfa_enforced, flag, cleared
):
    user = make_member("hold-setup", settings, flag)
    add_factor(user, "passkey")
    client.force_login(user, backend=PASSKEY_BACKEND)
    session = client.session
    session["mfa_setup_required"] = True
    session.save()

    complete_totp_setup(client)
    assert TOTPDevice.objects.filter(user=user, name="default").exists()

    assert held(client) is not cleared


def test_held_user_can_confirm_email(client, settings, mfa_enforced):
    user = make_member("hold-unconfirmed", settings, "ORG_FLAGS_DISABLE_TOTP")
    EmailAddress.objects.filter(user=user).update(verified=False)
    client.force_login(user, backend=PASSWORD_BACKEND)
    session = client.session
    session["mfa_setup_required"] = True
    session.save()

    assert client.get(reverse("user-profile")).status_code == 200
    assert client.get("/org/1").url == reverse("two_factor:profile")
