import base64
import json
from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_security_keys.models import SecurityKey, UserHandle

from peeringdb_server.models import Organization, User

pytestmark = pytest.mark.django_db
PASSWORD = "amr-login-password-478"


@pytest.fixture
def factors(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() - timedelta(days=2)
    settings.MFA_FORCE_HARD_START = timezone.now() - timedelta(days=1)
    user = User.objects.create_user(
        "amr-login", email="amr@example.net", password=PASSWORD, status="ok"
    )
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=True
    )
    device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    backup = StaticDevice.objects.create(user=user, name="backup", confirmed=True)
    recovery = StaticToken.objects.create(device=backup, token="recovery-code")
    key = SecurityKey.objects.create(
        user=user,
        credential_id="c2Vjb25kLWtleQ",
        credential_public_key="",
        type="security-key",
        passkey_login=False,
    )
    login_key = SecurityKey.objects.create(
        user=user,
        credential_id="cGFzc2tleQ",
        credential_public_key="",
        type="security-key",
        passkey_login=True,
    )
    return user, device, recovery, key, login_key


@pytest.fixture
def start_login(client, factors, mocker, settings):
    user, _, _, key, login_key = factors
    # Credential selection, wizard forms and session handling remain real;
    # only verification of the physical authenticator assertion is substituted.
    verify = mocker.patch.object(
        SecurityKey,
        "verify_authentication",
        side_effect=lambda username, session, credential, for_login=False: (
            login_key if for_login else key
        ),
    )

    def start(passkey):
        if passkey:
            org = Organization.objects.create(name="Passkey with MFA", status="ok")
            org.set_org_flag(settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
            org.set_org_flag(settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
            org.save()
            org.usergroup.user_set.add(user)
            handle = UserHandle.require_for_user(user)
            data = {
                "credential": json.dumps(
                    {
                        "id": login_key.credential_id,
                        "response": {
                            "userHandle": base64.urlsafe_b64encode(
                                handle.handle.encode()
                            )
                            .decode()
                            .rstrip("=")
                        },
                    }
                )
            }
        else:
            data = {
                "login_view-current_step": "auth",
                "auth-username": user.username,
                "auth-password": PASSWORD,
            }
        response = client.post(reverse("two_factor:login"), data)
        assert response.status_code == 200
        assert SESSION_KEY not in client.session
        return verify

    return start


@pytest.mark.parametrize("passkey", [False, True])
def test_security_key_login_does_not_claim_unused_otp(
    client, factors, start_login, passkey
):
    user, device, recovery, key, _ = factors
    verify = start_login(passkey)
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "security-key",
            "security-key-credential": json.dumps({"id": key.credential_id}),
        },
    )
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["amr"] == ["swk" if passkey else "pwd", "swk", "mfa"]
    assert client.session[BACKEND_SESSION_KEY] == (
        "django_security_keys.backends.PasskeyAuthenticationBackend"
        if passkey
        else "allauth.account.auth_backends.AuthenticationBackend"
    )
    assert verify.call_count == (2 if passkey else 1)
    assert json.loads(verify.call_args.args[2])["id"] == key.credential_id
    device.refresh_from_db()
    assert device.last_t == -1
    assert StaticToken.objects.filter(pk=recovery.pk).exists()


@pytest.mark.parametrize("passkey", [False, True])
@pytest.mark.parametrize("valid", [False, True])
def test_recovery_login_claims_otp_only_after_verification(
    client, factors, start_login, passkey, valid
):
    user, device, recovery, _, _ = factors
    verify = start_login(passkey)
    assert (
        client.post(
            reverse("two_factor:login"), {"wizard_goto_step": "backup"}
        ).status_code
        == 200
    )
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "backup",
            "backup-otp_token": recovery.token if valid else "invalid-code",
        },
    )
    if valid:
        assert response.status_code == 302
        assert client.session[SESSION_KEY] == str(user.pk)
        assert client.session["amr"] == ["swk" if passkey else "pwd", "otp", "mfa"]
        assert not StaticToken.objects.filter(pk=recovery.pk).exists()
    else:
        assert response.status_code == 200
        assert SESSION_KEY not in client.session
        assert "amr" not in client.session
        assert StaticToken.objects.filter(pk=recovery.pk).exists()
    assert verify.call_count == (1 if passkey else 0)
    device.refresh_from_db()
    assert device.last_t == -1


@pytest.mark.parametrize("passkey", [False, True])
def test_totp_login_does_not_claim_unused_security_key(
    client, factors, start_login, passkey
):
    user, device, recovery, _, _ = factors
    verify = start_login(passkey)
    response = client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "token",
            "token-otp_token": str(totp(device.bin_key)).zfill(6),
        },
    )
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)
    assert client.session["amr"] == ["swk" if passkey else "pwd", "otp", "mfa"]
    assert StaticToken.objects.filter(pk=recovery.pk).exists()
    assert verify.call_count == (1 if passkey else 0)
