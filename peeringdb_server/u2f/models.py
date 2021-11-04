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

from webauthn.helpers.structs import (
    RegistrationCredential,
    AuthenticationCredential,
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
        max_length=64,
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

        if user.webauthn_user_handle:
            return user.webauthn_user_handle

        handle = secrets.token_urlsafe(64)
        max_tries = 1000
        tries = 0

        while cls.objects.filter(handle=handle).exists():
            handle = secrets.token_urlsafe(64)
            if tries >= 1000:
                raise ValueError(
                    _("Unable to generate unique user handle for webauthn")
                )
            tries += 1

        return cls.objects.create(user=user, handle=handle)


class Challenge(models.Model):
    """
    Describes a webauthn registration or authentication challenge
    """

    user = models.ForeignKey(
        "peeringdb_server.User",
        related_name="webauthn_challenges",
        on_delete=models.CASCADE,
    )

    challenge = models.BinaryField(max_length=64, db_index=True)
    created = models.DateTimeField(auto_now_add=True)
    type = models.CharField(
        max_length=4,
        choices=(
            ("auth", "Authentication"),
            ("reg", "Registration"),
        ),
    )

    class Meta:
        db_table = "peeringdb_webauthn_challenge"
        verbose_name = _("Webauthn Challenge")
        verbose_name_plural = _("Webauthn_Challenges")


class SecurityKey(models.Model):

    """
    Describes a Webauthn (U2F) SecurityKey be used for passwordless
    login or 2FA

    2FA is handled through U2FOTPDevice which allows integration
    of Webauthn security keys as a 2FA option for django_otp
    """

    class Meta:
        db_table = "peeringdb_webauthn_security_key"
        verbose_name = _("U2F Device")
        verbose_name_plural = _("U2F Devices")

    name = models.CharField(max_length=255, null=True, help_text=_("Security key name"))
    credential_id = models.CharField(max_length=255, unique=True, db_index=True)
    credetnial_public_key = models.CharField(max_length=255, unique=True)
    sign_count = models.PositiveIntegerField(default=0)

    type = models.CharField(max_length=64)
    passwordless_login = models.BooleanField(
        default=False, help_text=_("User has enabled this key for passwordless login")
    )

    @classmethod
    def generate_registration(cls, user):

        opts = webauthn.generate_registration_options(
            settings.WEBAUTHN_RP_ID,
            settings.WEBAUTHN_RP_NAME,
            UserHandle.require_for_user(user).handle,
            user.username,
            attestation=None,
        )

        challenge = Challenge.objects.create(
            user=user, challenge=opts.challenge, type="reg"
        )

        return webauthn.options_to_json(opts)

    @classmethod
    def verify_registration(cls, user, challenge_str, raw_credential, name="main"):

        try:
            challenge = user.webauthn_challenges.get(
                challenge=challenge_str, type="reg"
            )
        except Challenge.DoesNotExist:
            raise ValueError(_("Invalid webauthn challenge"))

        credential = RegistrationCredential.parse_raw(raw_redential)
        verified_registration = webauthn.verify_registration_response(
            credential,
            challenge.challenge,
            settings.WEBAUTHN_RP_ID,
            settings.WEBAUTHN_ORIGIN,
        )

        challenge.delete()

        return cls.objects.create(
            name=name,
            credential_id=verified_registration.credential_id,
            credential_public_key=verified_registration.credential_public_key,
            sign_count=verified_registration.sign_count,
        )

    @classmethod
    def generate_authentication(cls):

        opts = webauthn.generate_authentication_options(
            settings.WEBAUTHN_RP_ID,
        )

        challenge = Challenge.objects.create(
            user=user, challenge=opts.challenge, type="auth"
        )

        return webauthn.options_to_json(opts)

    @classmethod
    def verify_authentication(cls, challenge_str, raw_credential):

        try:
            challenge = Challenge.objects.get(challenge=challenge_str, type="auth")
        except Challenge.DoesNotExist:
            raise ValueError(_("Invalid webauthn challenge"))

        credential = AuthenticationCredential.parse_raw(raw_credential)

        try:
            key = cls.objects.get(credential_id=credential.id)
        except SecurityKey.DoesNotExist:
            raise ValueError(_("Invalid key"))

        verified_authentication = webauthn.verify_authentication_response(
            credential,
            challenge.challenge,
            settings.WEBAUTHN_RP_ID,
            settings.WEBAUTHN_ORIGIN,
            key.credential_public_key,
            key.sign_count,
        )

        challenge.delete()

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
