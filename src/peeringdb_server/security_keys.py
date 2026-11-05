"""
Checks PeeringDB adds to django-security-keys' WebAuthn verification.

They are applied in `PeeringDBServerAppConfig.ready` and belong in the
library; they move there once the fixes can be published (#514,
20c/django-security-keys#1).
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.models import User
from django.contrib.sessions.backends.base import SessionBase
from django.utils.translation import gettext_lazy as _
from django_security_keys.models import SecurityKey
from webauthn.helpers import (
    parse_attestation_object,
    parse_authentication_credential_json,
    parse_authenticator_data,
    parse_registration_credential_json,
)

library_generate_authentication = SecurityKey.generate_authentication
library_verify_authentication = SecurityKey.verify_authentication
library_verify_registration = SecurityKey.verify_registration

USER_VERIFICATION_REQUIRED_ERROR = _(
    "Passkey login needs a passkey that asks for your PIN or biometric, and "
    "this one did not. Set a PIN on the security key, or use another way to "
    "sign in."
)


def generate_authentication(
    cls: type[SecurityKey],
    username: User | str,
    session: SessionBase,
    for_login: bool = False,
    ignore_credential_filter: bool = False,
) -> str:
    """
    `SecurityKey.generate_authentication` that requires user verification for
    passkey login, where the passkey is the whole login.
    """

    options = library_generate_authentication(
        username,
        session,
        for_login=for_login,
        ignore_credential_filter=ignore_credential_filter,
    )
    if not for_login:
        return options
    options = json.loads(options)
    options["userVerification"] = "required"
    return json.dumps(options)


def verify_authentication(
    cls: type[SecurityKey],
    username: str,
    session: SessionBase,
    raw_credential: str,
    for_login: bool = False,
) -> SecurityKey:
    """
    `SecurityKey.verify_authentication` that also requires the key to belong
    to `username`, and user verification for passkey login.

    The library finds the key by credential id alone, so a valid assertion
    from any registered key would verify for any user.

    The credential id has to match the stored one exactly. The database
    compares it case-insensitively, and the signature does not cover it, so
    a case variant of one passkey's id would otherwise pass as a different
    credential (the passkey login and its second factor).
    """

    credential = parse_authentication_credential_json(raw_credential)
    key = cls.objects.filter(
        user__username=username, credential_id=credential.id
    ).first()
    if key is None or key.credential_id != credential.id:
        raise ValueError(_("Security key authentication failed"))

    key = library_verify_authentication(
        username, session, raw_credential, for_login=for_login
    )

    # Checked after the signature, which covers the flags.
    authenticator_data = parse_authenticator_data(
        credential.response.authenticator_data
    )
    if for_login and not authenticator_data.flags.uv:
        raise ValueError(USER_VERIFICATION_REQUIRED_ERROR)

    return key


def verify_registration(
    cls: type[SecurityKey],
    user: User,
    session: SessionBase,
    raw_credential: str,
    **kwargs: Any,
) -> SecurityKey:
    """
    `SecurityKey.verify_registration` that requires user verification for
    keys registered for passkey login.
    """

    if kwargs.get("passkey_login"):
        credential = parse_registration_credential_json(raw_credential)
        attestation = parse_attestation_object(credential.response.attestation_object)
        if not attestation.auth_data.flags.uv:
            raise ValueError(USER_VERIFICATION_REQUIRED_ERROR)

    return library_verify_registration(user, session, raw_credential, **kwargs)


def patch_security_keys() -> None:
    SecurityKey.generate_authentication = classmethod(generate_authentication)
    SecurityKey.verify_authentication = classmethod(verify_authentication)
    SecurityKey.verify_registration = classmethod(verify_registration)
