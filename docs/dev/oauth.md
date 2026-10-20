## Example backend for python social core

```python
from django.conf import settings
from social_core.backends.oauth import BaseOAuth2
from social_core.exceptions import AuthFailed


class PeeringDBOAuth2(BaseOAuth2):
    name = "peeringdb"
    AUTHORIZATION_URL = settings.PDB_OAUTH_AUTHORIZE_URL
    ACCESS_TOKEN_URL = settings.PDB_OAUTH_ACCESS_TOKEN_URL
    PROFILE_URL = settings.PDB_OAUTH_PROFILE_URL

    ACCESS_TOKEN_METHOD = "POST"

    DEFAULT_SCOPE = ["email", "profile", "networks", "amr"]
    EXTRA_DATA = ["networks", "amr"]

    def get_user_details(self, response):
        """Return user details."""

        if response.get("verified_user") is not True:
            raise AuthFailed(
                self,
                "PeeringDB user is not verified. Please affiliate yourself with an organization in PeeringDB and try again.",
            )

        return {
            "username": response.get("given_name"),
            "email": response.get("email") or "",
            "first_name": response.get("given_name"),
            "last_name": response.get("family_name"),
        }

    def user_data(self, access_token, *args, **kwargs):
        """Load user data from service."""
        headers = {"Authorization": "Bearer %s" % access_token}
        data = self.get_json(self.PROFILE_URL, headers=headers)

        return data
```

## AMR values

PeeringDB currently is not collecting device attestation, thus has no way to identify the authentication method according to RFC 8176 (https://datatracker.ietf.org/doc/html/rfc8176). However, we are collecting the following AMR values:

- `pwd` - Password
- `mfa` - Multi-factor authentication
- `otp` - One-time password
- `swk` - Proof-of-Possession (PoP) of a software-secured key - usage of webauthn security key will append this

```python
"amr": ["pwd", "mfa", "otp"] # password entered + OTP
"amr": ["pwd", "mfa", "swk"] # password entered + Security Key
"amr": ["pwd"] # password entered
"amr": ["mfa", "swk", "otp"] # passkey with security key + OTP
"amr": ["mfa", "swk", "swk"] # passkey with security key + plus 2fa with another security key
"amr": ["swk"] # password less without mfa
```

## ID token signing

OpenID Connect ID tokens are signed with RS256. Verify them with the public keys published at `/oauth2/.well-known/jwks.json`.

HS256 is not supported: client secrets are stored hashed, so they cannot serve as the HMAC signing key. The application form no longer offers it and discovery no longer advertises it. An application still set to HS256 gets an `unauthorized_client` error whenever an ID token would be issued, until its owner switches it to RS256.

An application set to "No OIDC support" that requests the `openid` scope gets an `invalid_scope` error whenever an ID token would be issued: a 400 from the token endpoint, or for implicit and hybrid responses that include `id_token` a redirect back to the client from the authorization endpoint.

Operators can list, migrate and/or notify the owners of remaining HS256 applications whose secret is hashed with `pdb_oauth_hs256` (dry run unless `--commit`).
