"""
Which second factors count for MFA enrollment (#548).

`User.has_2fa` has to agree with what the login wizard asks for: a WebAuthn
key or passkey, or the default django-otp device. Backup tokens are only a
fallback next to one of those.
"""

from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import SESSION_KEY
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_email.models import EmailDevice
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_security_keys.models import SecurityKey

from peeringdb_server.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "second-factor-password-548"
BACKUP_TOKEN = "backup-code-548"


def add_backup_tokens(user):
    # the same device the backup tokens view creates
    device = StaticDevice.objects.create(user=user, name="backup", confirmed=True)
    StaticToken.objects.create(device=device, token=BACKUP_TOKEN)
    return device


def add_totp(user, name="default", confirmed=True):
    return TOTPDevice.objects.create(user=user, name=name, confirmed=confirmed)


def add_key(user, passkey_login):
    return SecurityKey.objects.create(
        user=user,
        credential_id=f"cred-{user.username}-{int(passkey_login)}",
        credential_public_key="",
        type="security-key",
        passkey_login=passkey_login,
    )


SETUPS = {
    "none": [],
    "backup_tokens": [add_backup_tokens],
    "totp_not_default": [lambda u: add_totp(u, name="phone")],
    "totp_default_unconfirmed": [lambda u: add_totp(u, confirmed=False)],
    "email_not_default": [
        lambda u: EmailDevice.objects.create(user=u, name="mail", confirmed=True)
    ],
    "totp_not_default_and_backup_tokens": [
        lambda u: add_totp(u, name="phone"),
        add_backup_tokens,
    ],
    "totp_default": [add_totp],
    "email_default": [
        lambda u: EmailDevice.objects.create(user=u, name="default", confirmed=True)
    ],
    "totp_default_and_backup_tokens": [add_totp, add_backup_tokens],
    "security_key": [lambda u: add_key(u, passkey_login=False)],
    "security_key_and_backup_tokens": [
        lambda u: add_key(u, passkey_login=False),
        add_backup_tokens,
    ],
    "passkey": [lambda u: add_key(u, passkey_login=True)],
}

NOT_ENROLLED = [
    "none",
    "backup_tokens",
    "totp_not_default",
    "totp_default_unconfirmed",
    "email_not_default",
    "totp_not_default_and_backup_tokens",
]
ENROLLED = [
    "totp_default",
    "email_default",
    "totp_default_and_backup_tokens",
    "security_key",
    "security_key_and_backup_tokens",
    "passkey",
]


def make_user(setup):
    user = User.objects.create_user(
        f"factor-{setup}".replace("_", "-"),
        email=f"{setup}@example.net",
        password=PASSWORD,
        status="ok",
    )
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=True
    )
    for step in SETUPS[setup]:
        step(user)
    # fresh instance: two_factor caches the default device on the user object
    return User.objects.get(pk=user.pk)


@pytest.fixture
def mfa_enforced(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() - timedelta(days=2)
    settings.MFA_FORCE_HARD_START = timezone.now() - timedelta(days=1)


def password_login(client, user):
    return client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": PASSWORD,
        },
    )


@pytest.mark.parametrize("setup", NOT_ENROLLED)
def test_has_2fa_false_without_a_factor_login_asks_for(setup):
    assert not make_user(setup).has_2fa


@pytest.mark.parametrize("setup", ENROLLED)
def test_has_2fa_true_with_a_factor_login_asks_for(setup):
    assert make_user(setup).has_2fa


@pytest.mark.parametrize(
    "setup",
    [
        "backup_tokens",
        "totp_not_default",
        "totp_not_default_and_backup_tokens",
    ],
)
def test_enforcement_redirects_when_login_asked_for_no_factor(
    client, mfa_enforced, setup
):
    user = make_user(setup)

    response = password_login(client, user)
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)

    response = client.get(reverse("user-profile"))
    assert response.status_code == 302
    assert response.url == reverse("two_factor:profile")


@pytest.mark.parametrize(
    "setup, step",
    [
        ("totp_default_and_backup_tokens", "token"),
        ("security_key_and_backup_tokens", "security-key"),
    ],
)
def test_login_asks_for_the_factor_that_counts(client, setup, step):
    user = make_user(setup)
    assert user.has_2fa

    response = password_login(client, user)
    assert response.status_code == 200
    assert SESSION_KEY not in client.session
    assert response.context["wizard"]["steps"].current == step


def test_backup_token_still_completes_login_next_to_default_device(
    client, mfa_enforced
):
    # The login wizard offers the backup step only next to the default device.
    user = make_user("totp_default_and_backup_tokens")
    password_login(client, user)

    assert (
        client.post(
            reverse("two_factor:login"), {"wizard_goto_step": "backup"}
        ).status_code
        == 200
    )
    response = client.post(
        reverse("two_factor:login"),
        {"login_view-current_step": "backup", "backup-otp_token": BACKUP_TOKEN},
    )
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["amr"] == ["pwd", "otp", "mfa"]

    # the remaining factor still counts, so enforcement lets the user through
    assert client.get(reverse("user-profile")).status_code == 200


def test_default_totp_completes_login_and_passes_enforcement(client, mfa_enforced):
    user = make_user("totp_default")
    device = TOTPDevice.objects.get(user=user)
    password_login(client, user)

    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "token",
            "token-otp_token": str(totp(device.bin_key)).zfill(6),
        },
    )
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.get(reverse("user-profile")).status_code == 200


def complete_email_setup(client, user):
    def step(name, **data):
        payload = {"two_factor_setup_view-current_step": name}
        payload.update({f"{name}-{key}": value for key, value in data.items()})
        return client.post(reverse("two_factor:setup"), payload)

    step("password", password=PASSWORD)
    step("welcome")
    step("method", method="email")
    token = EmailDevice.objects.get(user=user).token
    return step("validation", token=token)


@pytest.mark.parametrize("existing_name", [None, ""])
def test_email_setup_enrolls_with_login_provisioned_device(
    client, mfa_enforced, existing_name
):
    """
    The setup wizard's email method reuses an existing email device; one the
    login view provisioned has no name. Either way the user ends up enrolled.
    """
    user = make_user("none")
    if existing_name is not None:
        EmailDevice.objects.create(user=user, name=existing_name, confirmed=True)
    assert not user.has_2fa
    client.force_login(user)

    response = complete_email_setup(client, user)
    assert response.status_code == 302

    devices = EmailDevice.objects.filter(user=user)
    assert [d.name for d in devices] == ["default"]
    assert User.objects.get(pk=user.pk).has_2fa
    assert client.get(reverse("user-profile")).status_code == 200


def test_email_setup_keeps_existing_default_device(client, mfa_enforced):
    user = make_user("totp_default")
    EmailDevice.objects.create(user=user, name="", confirmed=True)
    client.force_login(user)

    # the wizard is not offered to users who are already enrolled
    response = client.get(reverse("two_factor:setup"))
    assert response.status_code == 302
    assert EmailDevice.objects.get(user=user).name == ""
