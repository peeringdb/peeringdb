import base64
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_security_keys.models import SecurityKey, UserHandle

from peeringdb_server.models import Organization, User

pytestmark = pytest.mark.django_db
PASSWORD_BACKEND = "allauth.account.auth_backends.AuthenticationBackend"
PASSKEY_BACKEND = "django_security_keys.backends.PasskeyAuthenticationBackend"
PASSWORD = "passkey-admin-password"


@pytest.fixture
def staff(settings):
    settings.ADMIN_REQUIRE_PASSKEY = True
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=1)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=2)
    user = User.objects.create_user(
        "passkey-admin",
        email="passkey-admin@example.net",
        password=PASSWORD,
        status="ok",
        is_staff=True,
        is_superuser=True,
    )
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=True
    )
    return user


@pytest.fixture
def required_org(settings):
    org = Organization.objects.create(name="Passkey required", status="ok")
    org.set_org_flag(settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
    org.save()
    return org


@pytest.mark.parametrize("path", ["/cp/", "/cp/peeringdb_server/user/"])
def test_password_session_cannot_access_passkey_required_admin(
    client, staff, required_org, path
):
    required_org.usergroup.user_set.add(staff)
    client.force_login(staff, backend=PASSWORD_BACKEND)
    response = client.get(path)
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login"))
    assert SESSION_KEY not in client.session


def test_totp_and_legacy_passkey_marker_do_not_substitute_for_passkey(
    client, staff, required_org
):
    required_org.admin_usergroup.user_set.add(staff)
    device = TOTPDevice.objects.create(user=staff, confirmed=True)
    client.force_login(staff, backend=PASSWORD_BACKEND)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session["used_passkey_auth"] = True
    session["amr"] = ["swk", "otp", "mfa"]
    session.save()
    assert client.get("/cp/").status_code == 302
    assert SESSION_KEY not in client.session


@pytest.mark.parametrize("change", ["join", "enable"])
def test_policy_changes_recheck_existing_admin_sessions(
    client, staff, required_org, change, settings
):
    if change == "enable":
        required_org.set_org_flag(
            settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, False
        )
        required_org.save()
        required_org.usergroup.user_set.add(staff)
    client.force_login(staff, backend=PASSWORD_BACKEND)
    assert client.get("/cp/").status_code == 403
    if change == "join":
        required_org.usergroup.user_set.add(staff)
    else:
        required_org.set_org_flag(
            settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True
        )
        required_org.save()
    assert client.get("/cp/").status_code == 302
    assert SESSION_KEY not in client.session


@pytest.mark.xdist_group(name="read_only_tests")
def test_required_passkey_reauthentication_in_read_only_mode(
    client, staff, required_org, settings
):
    required_org.usergroup.user_set.add(staff)
    client.force_login(staff, backend=PASSWORD_BACKEND)
    with override_settings(
        DJANGO_READ_ONLY=True,
        INSTALLED_APPS=[*settings.INSTALLED_APPS, "django_read_only"],
    ):
        response = client.get("/cp/")
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("two_factor:login"))
        assert SESSION_KEY not in client.session


def test_admin_login_uses_application_flow(client):
    response = client.get(reverse("admin:login"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login"))


def test_real_password_login_is_blocked_for_required_org(client, staff, required_org):
    required_org.usergroup.user_set.add(staff)
    SecurityKey.objects.create(
        user=staff,
        name="Existing passkey",
        passkey_login=True,
        credential_id="existing-passkey",
        credential_public_key="test",
    )
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": staff.username,
            "auth-password": PASSWORD,
            "next": "/cp/",
        },
    )
    assert response.status_code == 302
    assert SESSION_KEY not in client.session
    assert client.get("/cp/").status_code == 302


@pytest.mark.parametrize("require_mfa", [False, True])
def test_passkey_login_establishes_backend_and_admin_access(
    client, staff, required_org, mocker, settings, require_mfa
):
    required_org.usergroup.user_set.add(staff)
    if require_mfa:
        required_org.set_org_flag(settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
        required_org.save()
        device = TOTPDevice.objects.create(user=staff, name="default", confirmed=True)
    handle = UserHandle.require_for_user(staff)
    credential = json.dumps(
        {
            "id": "test-credential",
            "response": {
                "userHandle": base64.urlsafe_b64encode(handle.handle.encode())
                .decode()
                .rstrip("="),
            },
        }
    )
    # Only the hardware assertion boundary is substituted; the login wizard,
    # authentication backend, session and admin middleware run normally.
    mocker.patch.object(
        SecurityKey,
        "credentials",
        side_effect=lambda username, for_login=False: [object()] if for_login else [],
    )
    verify = mocker.patch.object(
        SecurityKey, "verify_authentication", return_value=SimpleNamespace(user=staff)
    )
    response = client.post(
        reverse("two_factor:login"), {"credential": credential, "next": "/cp/"}
    )
    if require_mfa:
        assert response.status_code == 200
        assert SESSION_KEY not in client.session
        response = client.post(
            reverse("two_factor:login"),
            {
                "login_view-current_step": "token",
                "token-otp_token": str(totp(device.bin_key)).zfill(6),
                "next": "/cp/",
            },
        )
    assert response.status_code == 302
    assert verify.call_count == 1
    assert verify.call_args.kwargs["for_login"] is True
    assert client.session[SESSION_KEY] == str(staff.pk)
    assert client.session[BACKEND_SESSION_KEY] == PASSKEY_BACKEND
    assert client.session["used_passkey_auth"] is True
    assert client.session["amr"] == (["swk", "otp", "mfa"] if require_mfa else ["swk"])
    assert client.get("/cp/").status_code == 200


def test_password_login_still_requires_and_accepts_totp(client, staff, settings):
    settings.ADMIN_REQUIRE_PASSKEY = False
    device = TOTPDevice.objects.create(user=staff, name="default", confirmed=True)
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": staff.username,
            "auth-password": PASSWORD,
            "next": "/cp/",
        },
    )
    assert response.status_code == 200
    assert SESSION_KEY not in client.session
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "token",
            "token-otp_token": str(totp(device.bin_key)).zfill(6),
            "next": "/cp/",
        },
    )
    assert response.status_code == 302
    assert client.session[BACKEND_SESSION_KEY] == PASSWORD_BACKEND
    assert client.session["amr"] == ["pwd", "otp", "mfa"]
    assert not client.session.get("used_passkey_auth")
    assert client.get("/cp/").status_code == 200


def test_failed_passkey_attempt_does_not_set_success_marker(client):
    response = client.post(reverse("two_factor:login"), {"credential": "{}"})
    assert response.status_code == 200
    assert SESSION_KEY not in client.session
    assert not client.session.get("used_passkey_auth")


def test_disabled_admin_passkey_gate_preserves_django_authorization(
    client, staff, settings
):
    settings.ADMIN_REQUIRE_PASSKEY = False
    client.force_login(staff, backend=PASSWORD_BACKEND)
    assert client.get("/cp/").status_code == 200
    staff.is_staff = False
    staff.is_superuser = False
    staff.save()
    assert client.get("/cp/").status_code == 302


def test_passkey_does_not_grant_model_permissions(client, staff, required_org):
    required_org.usergroup.user_set.add(staff)
    staff.is_superuser = False
    staff.save()
    client.force_login(staff, backend=PASSKEY_BACKEND)
    assert client.get("/cp/").status_code == 200
    assert client.get("/cp/peeringdb_server/user/").status_code == 403


@pytest.mark.parametrize(
    "amr,disable_totp,allowed",
    [
        (["swk"], False, False),
        (["swk", "otp", "mfa"], False, True),
        (["swk", "otp", "mfa"], True, False),
        (["swk", "swk", "mfa"], True, True),
    ],
)
def test_current_extra_factor_policy_applies_to_admin(
    client, staff, required_org, settings, amr, disable_totp, allowed
):
    required_org.set_org_flag(settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    required_org.set_org_flag(settings.ORG_FLAGS_DISABLE_TOTP, disable_totp)
    required_org.save()
    required_org.usergroup.user_set.add(staff)
    client.force_login(staff, backend=PASSKEY_BACKEND)
    session = client.session
    session["amr"] = amr
    session.save()
    assert client.get("/cp/").status_code == (200 if allowed else 302)


@pytest.mark.parametrize("backend", [PASSWORD_BACKEND, PASSKEY_BACKEND])
def test_enabled_gate_denies_users_outside_required_orgs(client, staff, backend):
    client.force_login(staff, backend=backend)
    response = client.get("/cp/")
    assert response.status_code == 403
    assert b"membership in an organization" in response.content


def test_leaving_required_org_revokes_admin_access(client, staff, required_org):
    required_org.usergroup.user_set.add(staff)
    client.force_login(staff, backend=PASSKEY_BACKEND)
    assert client.get("/cp/").status_code == 200
    required_org.usergroup.user_set.remove(staff)
    assert client.get("/cp/").status_code == 403


def test_disabled_gate_does_not_enforce_org_policy_on_existing_admin_session(
    client,
    staff,
    required_org,
    settings,
):
    required_org.usergroup.user_set.add(staff)
    client.force_login(staff, backend=PASSWORD_BACKEND)
    settings.ADMIN_REQUIRE_PASSKEY = False
    assert client.get("/cp/").status_code == 200
    settings.ADMIN_REQUIRE_PASSKEY = True
    assert client.get("/cp/").status_code == 302


def test_enabled_gate_preserves_nonstaff_denial(client, staff, required_org):
    required_org.usergroup.user_set.add(staff)
    staff.is_staff = False
    staff.is_superuser = False
    staff.save()
    client.force_login(staff, backend=PASSKEY_BACKEND)
    assert client.get("/cp/").status_code == 302
