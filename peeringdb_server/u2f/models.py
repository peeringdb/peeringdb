"""
Implementation of FIDO U2F authentication for PeeringDB through Webauthn. (#692)

Allows for passwordless login as well as using FIDO U2F for 2FA.

2FA integration is handled by extending a custom django_otp device.

The Web Authentication API (also known as WebAuthn) is a specification written by the W3C and FIDO, with the participation of Google, Mozilla, Microsoft, Yubico, and others. The API allows servers to register and authenticate users using public key cryptography instead of a password.

Ref: https://webauthn.io/
Ref: https://webauthn.guide/#webauthn-api
Ref: https://w3c.github.io/webauthn
Ref: https://github.com/duo-labs/py_webauthn
"""

from django.db import models, transaction
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from django_otp.models import SideChannelDevice, ThrottlingMixin

import secrets
import webauthn

from webauthn.helpers import parse_client_data_json, bytes_to_base64url, base64url_to_bytes

from webauthn.helpers.structs import (
    RegistrationCredential,
    AuthenticationCredential,
    PublicKeyCredentialDescriptor,
)


class UserHandle(models.Model):

    """
    Unique identifier used to map users to their webauthn security keys

    Webauthn specifications recommend a unqiue set of 64 bytes for this value

    Ref: https://w3c.github.io/webauthn/#sctn-user-handle-privacy
    """

    user = models.OneToOneField(
        "peeringdb_server.User",
        primary_key=True,
        related_name="webauthn_user_handle",
        on_delete=models.CASCADE,
    )

    handle = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text=_(
            "Unqiue user handle to be used to map users to their Webauthn credentials, only set if user has registered one or more security keys. Will be unique random 64 bytes"
        ),
        db_index=True,
        unique=True,
    )

    class Meta:
        db_table = "peeringdb_webauthn_user_handle"
        verbose_name = _("Webauthn User Handle")
        verbose_name_plural = _("Webauthn User Handles")

    @classmethod
    def require_for_user(cls, user):

        """
        Requires a user handle for the user, will create it if it does not exist
        """

        try:
            return user.webauthn_user_handle
        except UserHandle.DoesNotExist:
            pass

        handle = secrets.token_urlsafe(32)
        max_tries = 1000
        tries = 0

        while cls.objects.filter(handle=handle).exists():
            handle = secrets.token_urlsafe(32)
            if tries >= max_tries:
                raise ValueError(
                    _("Unable to generate unique user handle for webauthn")
                )
            tries += 1

        return cls.objects.create(user=user, handle=handle)


class SecurityKey(models.Model):

    """
    Describes a Webauthn (U2F) SecurityKey be used for passwordless
    login or 2FA

    2FA is handled through SecurityKeyDevice which allows integration
    of Webauthn security keys as a 2FA option for django_otp
    """

    class Meta:
        db_table = "peeringdb_webauthn_security_key"
        verbose_name = _("Webauthn Security Key")
        verbose_name_plural = _("Webauthn Security Keys")

    user = models.ForeignKey(
        "peeringdb_server.User",
        related_name="webauthn_security_keys",
        on_delete=models.CASCADE,
    )

    name = models.CharField(max_length=255, null=True, help_text=_("Security key name"))
    credential_id = models.CharField(max_length=255, unique=True, db_index=True)
    credential_public_key = models.CharField(max_length=255, unique=True)
    sign_count = models.PositiveIntegerField(default=0)

    type = models.CharField(max_length=64)
    passwordless_login = models.BooleanField(
        default=False, help_text=_("User has enabled this key for passwordless login")
    )

    @classmethod
    def set_challenge(cls, session, challenge):
        session["webauthn_challenge"] = bytes_to_base64url(challenge)

    @classmethod
    def get_challenge(cls, session):
        return base64url_to_bytes(session["webauthn_challenge"])

    @classmethod
    def clear_challenge(cls, session):
        try:
            del session["webauthn_challenge"]
        except KeyError:
            pass

    @classmethod
    def generate_registration(cls, user, session):

        opts = webauthn.generate_registration_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            rp_name=settings.WEBAUTHN_RP_NAME,
            user_id=UserHandle.require_for_user(user).handle,
            user_name=user.username,
            attestation="none",
        )

        cls.set_challenge(session, opts.challenge)

        return webauthn.options_to_json(opts)

    @classmethod
    def verify_registration(cls, user, session, raw_credential, **kwargs):

        try:
            challenge = cls.get_challenge(session)
        except KeyError:
            raise ValueError(_("Invalid webauthn challenge"))

        credential = RegistrationCredential.parse_raw(raw_credential)

        client_data = parse_client_data_json(credential.response.client_data_json)

        verified_registration = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )

        cls.clear_challenge(session)

        return cls.objects.create(
            user=user,
            credential_id=bytes_to_base64url(verified_registration.credential_id),
            credential_public_key=bytes_to_base64url(verified_registration.credential_public_key),
            sign_count=verified_registration.sign_count,
            name=kwargs.get("name", "main"),
            passwordless_login=kwargs.get("passwordless_login", False)
        )

    @classmethod
    def credentials(cls, username):
        return [
            PublicKeyCredentialDescriptor(
                type="public-key",
                id=base64url_to_bytes(key.credential_id),
            ) for key in cls.objects.filter(user__username=username)
        ]

    @classmethod
    def generate_authentication(cls, username, session):

        opts = webauthn.generate_authentication_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            allow_credentials=cls.credentials(username),
        )

        cls.set_challenge(session, opts.challenge)

        return webauthn.options_to_json(opts)

    @classmethod
    def verify_authentication(cls, username, session, raw_credential):

        try:
            challenge = cls.get_challenge(session)
        except Challenge.DoesNotExist:
            raise ValueError(_("Invalid webauthn challenge"))

        credential = AuthenticationCredential.parse_raw(raw_credential)

        try:
            key = cls.objects.get(credential_id=credential.id)
        except SecurityKey.DoesNotExist:
            raise ValueError(_("Invalid key"))

        verified_authentication = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=base64url_to_bytes(key.credential_public_key),
            credential_current_sign_count=key.sign_count,
        )

        cls.clear_challenge(session)

        key.sign_count = verified_authentication.new_sign_count
        key.save()


class SecurityKeyDevice(ThrottlingMixin, SideChannelDevice):
    """
    Integration of SecurityKey (FIDO U2F) with django_otp
    """

    key = models.OneToOneField(
        SecurityKey, related_name="twofactor_device", on_delete=models.CASCADE
    )

    class Meta:
        db_table = "peeringdb_webauthn_2fa_device"
        verbose_name = _("Webauthn Security Key 2FA Device")
        verbose_name_plural = _("Webauthn Security Key 2FA Devices")
