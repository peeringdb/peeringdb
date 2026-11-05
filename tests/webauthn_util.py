"""
A software WebAuthn authenticator for tests.

It signs real assertions with a P-256 key, so py_webauthn verifies them the
way it verifies a hardware key's: signature, challenge, origin, RP id and
sign count.
"""

import base64
import hashlib
import json
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django_security_keys.models import SecurityKey, SecurityKeyDevice, UserHandle
from webauthn.helpers import encode_cbor

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


def b64url(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def origin():
    if isinstance(settings.WEBAUTHN_ORIGIN, str):
        return settings.WEBAUTHN_ORIGIN
    return settings.WEBAUTHN_ORIGIN[0]


class SoftAuthenticator:
    def __init__(self, credential_id):
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = credential_id
        self.sign_count = 0

    def public_key(self):
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )

    def register(self, user, passkey_login=False):
        """
        Stores the key for `user` as a completed registration would.
        """

        key = SecurityKey.objects.create(
            user=user,
            name=f"key-{self.credential_id.decode()}",
            credential_id=b64url(self.credential_id),
            credential_public_key=b64url(self.public_key()),
            passkey_login=passkey_login,
            type="security-key",
        )
        SecurityKeyDevice.require_for_user(user)
        return key

    def client_data(self, ceremony, challenge):
        return json.dumps(
            {"type": ceremony, "challenge": challenge, "origin": origin()}
        ).encode()

    def assertion(self, challenge, user_verified=False, user=None, credential_id=None):
        """
        Returns the credential JSON `navigator.credentials.get` produces.

        Passing `user` adds its user handle, as a discoverable (passkey)
        credential does. `credential_id` replaces the id and raw id the
        client reports; the signature does not cover them.
        """

        self.sign_count += 1
        flags = FLAG_UP | (FLAG_UV if user_verified else 0)
        authenticator_data = (
            hashlib.sha256(settings.WEBAUTHN_RP_ID.encode()).digest()
            + bytes([flags])
            + struct.pack(">I", self.sign_count)
        )
        client_data = self.client_data("webauthn.get", challenge)
        signature = self.private_key.sign(
            authenticator_data + hashlib.sha256(client_data).digest(),
            ec.ECDSA(hashes.SHA256()),
        )
        response = {
            "authenticatorData": b64url(authenticator_data),
            "clientDataJSON": b64url(client_data),
            "signature": b64url(signature),
        }
        if user is not None:
            handle = UserHandle.require_for_user(user).handle
            response["userHandle"] = b64url(handle.encode())
        credential_id = credential_id or b64url(self.credential_id)
        return json.dumps(
            {
                "id": credential_id,
                "rawId": credential_id,
                "type": "public-key",
                "response": response,
            }
        )

    def attestation(self, challenge, user_verified=False):
        """
        Returns the credential JSON `navigator.credentials.create` produces,
        with "none" attestation.
        """

        flags = FLAG_UP | FLAG_AT | (FLAG_UV if user_verified else 0)
        numbers = self.private_key.public_key().public_numbers()
        cose_key = encode_cbor(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )
        authenticator_data = (
            hashlib.sha256(settings.WEBAUTHN_RP_ID.encode()).digest()
            + bytes([flags])
            + struct.pack(">I", 0)
            + bytes(16)
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + cose_key
        )
        attestation_object = encode_cbor(
            {"fmt": "none", "attStmt": {}, "authData": authenticator_data}
        )
        return json.dumps(
            {
                "id": b64url(self.credential_id),
                "rawId": b64url(self.credential_id),
                "type": "public-key",
                "response": {
                    "attestationObject": b64url(attestation_object),
                    "clientDataJSON": b64url(
                        self.client_data("webauthn.create", challenge)
                    ),
                },
            }
        )
