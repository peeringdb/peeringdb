Generated from security_keys.py on 2026-11-05 20:07:16.953937

# peeringdb_server.security_keys

Checks PeeringDB adds to django-security-keys' WebAuthn verification.

They are applied in `PeeringDBServerAppConfig.ready` and belong in the
library; they move there once the fixes can be published (#514,
20c/django-security-keys#1).

# Functions
---

## generate_authentication
`def generate_authentication(cls, username, session, for_login=False, ignore_credential_filter=False)`

`SecurityKey.generate_authentication` that requires user verification for
passkey login, where the passkey is the whole login.

---
## verify_authentication
`def verify_authentication(cls, username, session, raw_credential, for_login=False)`

`SecurityKey.verify_authentication` that also requires the key to belong
to `username`, and user verification for passkey login.

The library finds the key by credential id alone, so a valid assertion
from any registered key would verify for any user.

The credential id has to match the stored one exactly. The database
compares it case-insensitively, and the signature does not cover it, so
a case variant of one passkey's id would otherwise pass as a different
credential (the passkey login and its second factor).

---
## verify_registration
`def verify_registration(cls, user, session, raw_credential, **kwargs)`

`SecurityKey.verify_registration` that requires user verification for
keys registered for passkey login.

---
