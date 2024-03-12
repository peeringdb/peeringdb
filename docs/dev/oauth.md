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
- `u2f` - Universal 2nd Factor (not in the RFC spec, but since we're not able to collect device attestation, we're using this as a proxy for security key usage - e.g., YubiKey, device pin, fingerprint scanner etc.)

```python
"amr": ["pwd", "mfa", "otp"] # password entered + OTP
"amr": ["pwd", "mfa", "u2f"] # password entered + Security Key
"amr": ["pwd"] # password entered
"amr": ["mfa", "u2f", "otp"] # passwordless with security key + OTP
"amr": ["mfa", "u2f", "u2f"] # passwordless with security key + plus 2fa with another security key
"amr": ["u2f"] # password less without mfa
```