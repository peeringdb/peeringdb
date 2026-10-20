import base64
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_security_keys.models import SecurityKey, UserHandle

from peeringdb_server.models import Organization, User

pytestmark = pytest.mark.django_db
PASSWORD = "enrollment-test-password"


@pytest.fixture
def enrollment_user(settings):
    settings.ADMIN_REQUIRE_PASSKEY = True
    user = User.objects.create_user(
        "passkey-enrollment",
        password=PASSWORD,
        email="enrollment@example.net",
        status="ok",
        is_staff=True,
        is_superuser=True,
    )
    org = Organization.objects.create(name="Enrollment policy", status="ok")
    org.set_org_flag(settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
    org.save()
    org.admin_usergroup.user_set.add(user)
    return user


def password_login(client, user, password=PASSWORD):
    return client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": user.username,
            "auth-password": password,
            "next": "/cp/",
        },
    )


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("enforce", [False, True])
def test_missing_passkey_enters_restricted_enrollment(
    client,
    enrollment_user,
    settings,
    verified,
    enforce,
):
    settings.MFA_FORCE_SOFT_START = (
        None if enforce else timezone.now() + timedelta(days=1)
    )
    settings.MFA_FORCE_HARD_START = (
        None if enforce else timezone.now() + timedelta(days=2)
    )
    if verified:
        EmailAddress.objects.create(
            user=enrollment_user,
            email=enrollment_user.email,
            primary=True,
            verified=True,
        )
    response = password_login(client, enrollment_user)
    assert response.status_code == 302
    assert response["Location"] == reverse("profile_passkey")
    assert client.session[SESSION_KEY] == str(enrollment_user.pk)
    assert client.session["passkey_setup_required"] is True
    assert (
        client.session[BACKEND_SESSION_KEY]
        != "django_security_keys.backends.PasskeyAuthenticationBackend"
    )
    assert client.get(reverse("profile_passkey")).status_code == 200
    for path in [
        "/",
        "/cp/",
        "/api/org",
        "/profile",
        "/oauth2/authorize/",
        reverse("two_factor:backup_tokens"),
        "/security_keys/update-security-key",
    ]:
        response = client.get(path)
        assert response.status_code == 302, path
        assert response["Location"] == reverse("profile_passkey"), path
    for path in [
        "/user_keys/add",
        "/org_admin/users",
        "/security_keys/remove",
        reverse("two_factor:disable"),
        "/oauth2/authorize/",
    ]:
        assert client.post(path).status_code == 302, path
    assert "oauth_session" not in client.cookies


def test_wrong_password_cannot_start_enrollment(client, enrollment_user):
    response = password_login(client, enrollment_user, "wrong-password")
    assert response.status_code == 200
    assert SESSION_KEY not in client.session
    assert not client.session.get("passkey_setup_required")


def test_enrollment_keeps_existing_totp_challenge(client, enrollment_user):
    device = TOTPDevice.objects.create(
        user=enrollment_user, name="default", confirmed=True
    )
    assert password_login(client, enrollment_user).status_code == 200
    assert SESSION_KEY not in client.session
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "token",
            "token-otp_token": str(totp(device.bin_key)).zfill(6),
        },
    )
    assert response["Location"] == reverse("profile_passkey")
    assert client.session["passkey_setup_required"] is True


def test_existing_passkey_cannot_use_password_enrollment(client, enrollment_user):
    SecurityKey.objects.create(
        user=enrollment_user,
        name="Existing passkey",
        passkey_login=True,
        credential_id=b"existing",
        credential_public_key=b"test",
    )
    response = password_login(client, enrollment_user)
    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:login")
    assert SESSION_KEY not in client.session


@pytest.mark.parametrize("admin_required", [False, True])
@pytest.mark.parametrize("extra_mfa", [False, True])
@pytest.mark.parametrize("ui_next", [False, True])
def test_registration_keeps_session_restricted_until_passkey_login(
    client,
    enrollment_user,
    mocker,
    settings,
    ui_next,
    extra_mfa,
    admin_required,
):
    settings.ADMIN_REQUIRE_PASSKEY = admin_required
    settings.MFA_FORCE_HARD_START = timezone.now() - timedelta(days=1)
    if extra_mfa:
        device = TOTPDevice.objects.create(
            user=enrollment_user, name="default", confirmed=True
        )
        org = enrollment_user.organizations[0]
        org.set_org_flag(settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
        org.save()

    def submit_token():
        # Permit a fresh code in this test without waiting for a TOTP interval.
        device.refresh_from_db()
        device.last_t = -1
        device.save()
        return client.post(
            reverse("two_factor:login"),
            {
                "login_view-current_step": "token",
                "token-otp_token": str(totp(device.bin_key)).zfill(6),
                "next": reverse("two_factor:login"),
            },
        )

    if ui_next:
        enrollment_user.opt_flags |= settings.USER_OPT_FLAG_UI_NEXT
        enrollment_user.save()
    password_login(client, enrollment_user)
    if extra_mfa:
        assert SESSION_KEY not in client.session
        assert submit_token()["Location"] == reverse("profile_passkey")
    response = client.get(reverse("profile_passkey"))
    assert b"Your organization requires passkey authentication" in response.content
    assert b'data-edit-name="password"' in response.content
    assert b"request_registration?passkey=1" in response.content
    assert (
        client.post(
            reverse("security-keys-request-registration"), {"password": "wrong"}
        ).status_code
        == 401
    )
    response = client.post(
        reverse("security-keys-request-registration"), {"password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["challenge"]
    assert (
        response.json().get("authenticatorSelection", {}).get("residentKey")
        != "required"
    )
    response = client.post(
        reverse("security-keys-request-registration") + "?passkey=1",
        {"password": PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["authenticatorSelection"]["residentKey"] == "required"

    def register(user, session, credential, **kwargs):
        assert user == enrollment_user
        assert credential == "test-registration"
        return SecurityKey.objects.create(
            user=user,
            credential_id="test-credential",
            credential_public_key="test",
            **kwargs,
        )

    # Hardware verification is substituted; registration, password verification,
    # the login wizard and access restrictions use their real implementations.
    verification = mocker.patch.object(
        SecurityKey, "verify_registration", side_effect=register
    )
    assert client.post("/security_keys/add", {"password": "wrong"}).status_code == 401
    verification.assert_not_called()
    assert (
        client.post(
            "/security_keys/add",
            {
                "password": PASSWORD,
                "credential": "test-registration",
                "name": "New passkey",
                "passkey_login": "true",
            },
        ).status_code
        == 200
    )
    assert enrollment_user.get_passkey_security_keys.count() == 1
    assert client.get("/cp/")["Location"] == reverse("profile_passkey")
    assert client.get("/profile")["Location"] == reverse("profile_passkey")
    assert client.session["passkey_setup_required"] is True

    # Keep the authenticated enrollment session: rejection redirects to the
    # caller-selected next URL too, but must never count as successful login.
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": enrollment_user.username,
            "auth-password": PASSWORD,
            "next": reverse("two_factor:login"),
        },
    )
    if extra_mfa:
        assert response.status_code == 200
        assert client.session["passkey_setup_required"] is True
        response = submit_token()
    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:login")
    assert client.session[SESSION_KEY] == str(enrollment_user.pk)
    assert client.session["passkey_setup_required"] is True
    assert "amr" not in client.session
    assert "used_passkey_auth" not in client.session
    for method in (client.get, client.post):
        for path in ("/profile", "/cp/", "/api/org", "/oauth2/authorize/"):
            response = method(path)
            assert response.status_code == 302, path
            assert response["Location"] == reverse("profile_passkey"), path
    assert "oauth_session" not in client.cookies

    handle = UserHandle.require_for_user(enrollment_user)
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
    mocker.patch.object(
        SecurityKey,
        "verify_authentication",
        return_value=SimpleNamespace(user=enrollment_user),
    )
    response = client.post(
        reverse("two_factor:login"), {"credential": credential, "next": "/cp/"}
    )
    if extra_mfa:
        assert response.status_code == 200
        assert client.session["passkey_setup_required"] is True
        assert client.get("/cp/")["Location"] == reverse("profile_passkey")
        response = submit_token()
    assert response.status_code == 302
    assert not client.session.get("passkey_setup_required")
    assert (
        client.session[BACKEND_SESSION_KEY]
        == "django_security_keys.backends.PasskeyAuthenticationBackend"
    )
    assert client.session["amr"] == (["swk", "otp", "mfa"] if extra_mfa else ["swk"])
    assert client.get("/cp/").status_code == 200


def test_enrollment_can_sign_out(client, enrollment_user):
    password_login(client, enrollment_user)
    assert client.get("/logout").status_code == 302
    assert SESSION_KEY not in client.session
    assert not client.session.get("passkey_setup_required")


@pytest.mark.parametrize("passkey_required", [False, True])
def test_registration_retry_after_wrong_password_is_not_cached(
    client, settings, passkey_required
):
    """
    A non-staff user who mistypes the password for passkey registration can
    retry right away; the negative cache must not replay the 401 for the
    corrected request, whose only difference is the POST body
    """

    settings.NEGATIVE_CACHE_ENABLED = True
    user = User.objects.create_user(
        "passkey-registration-retry",
        password=PASSWORD,
        email="retry@example.net",
        status="ok",
    )
    if passkey_required:
        org = Organization.objects.create(name="Registration retry", status="ok")
        org.set_org_flag(settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
        org.save()
        org.usergroup.user_set.add(user)
        password_login(client, user)
        assert client.session["passkey_setup_required"] is True
    else:
        client.force_login(user)

    url = reverse("security-keys-request-registration") + "?passkey=1"
    response = client.post(url, {"password": "wrong"})
    assert response.status_code == 401

    response = client.post(url, {"password": PASSWORD})
    assert response.status_code == 200
    assert response.headers.get("X-Cached-Response") is None
    assert response.json()["authenticatorSelection"]["residentKey"] == "required"
