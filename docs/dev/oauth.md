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

## Where access tokens are accepted

An OAuth access token (`Authorization: Bearer <token>`) is accepted only by:

- `/profile/v1`, which needs the `profile` scope and adds email, networks and AMR data for the `email`, `networks` and `amr` scopes
- the OpenID Connect and OAuth endpoints under `/oauth2/`, such as `/oauth2/userinfo/`

Everywhere else the token is ignored: a website view treats the request as anonymous. The REST API answers `401` with "OAuth access tokens are not accepted by the API, use an API key." Use an API key for API access.

Deactivating or closing an account revokes its access and refresh tokens and deletes its pending authorization codes and device grants. `/profile/v1`, userinfo, token refresh and the authorization code exchange also refuse tokens of an inactive account.

## Grant types

New applications should use the authorization code grant with PKCE. The resource owner password credentials grant is not supported. The token endpoint answers `grant_type=password` with `400 unsupported_grant_type` without checking the credentials, also for applications registered with it before. The application form no longer offers it and the server metadata no longer advertises it. Access and refresh tokens of an application still set to it are refused, and it must switch to another grant type before its settings can be saved.

## Token lifetimes

Access tokens last 10 hours (the django-oauth-toolkit default).

A refresh token expires `OAUTH2_REFRESH_TOKEN_EXPIRE_SECONDS` after its last access token expired, 90 days by default. Every refresh issues a new pair and restarts the clock, so only clients that stop refreshing for that long have to send their user through authorization again. The expiry is enforced when the client refreshes. Set the environment variable to `0` to turn expiry off.

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

## RP-initiated logout

PeeringDB supports [OpenID Connect RP-Initiated Logout 1.0](https://openid.net/specs/openid-connect-rpinitiated-1_0.html). The OIDC discovery document (`/.well-known/openid-configuration`) advertises the endpoint as `end_session_endpoint`:

```
https://www.peeringdb.com/oauth2/logout/
```

To log a user out of PeeringDB as well as your application, send the user's browser there:

```
https://www.peeringdb.com/oauth2/logout/?id_token_hint=<id token>&post_logout_redirect_uri=https://example.com/logged-out&state=<state>
```

- `id_token_hint`: an ID token PeeringDB issued to your application for this user. Expired tokens are accepted.
- `client_id`: your client id. It is only needed when you do not send `id_token_hint`.
- `post_logout_redirect_uri`: where PeeringDB sends the user afterwards. It must be https and match one of the **post logout redirect URIs** registered on your application exactly (see below). Edit the application under your profile or organization OAuth settings to add them, separated by spaces.
- `state`: optional, appended to the query of `post_logout_redirect_uri` when PeeringDB redirects back.

A user who is logged in to PeeringDB is asked to confirm the logout. A user who has no PeeringDB session is redirected straight away.

Logout ends the PeeringDB session only. Access and refresh tokens issued to your application stay valid until they expire. If your application should no longer use them, revoke them with the token revocation endpoint (`/oauth2/revoke_token/`, RFC 7009).

### Matching post logout redirect URIs

Registered and requested URIs may contain a port, a path and a query (RP-Initiated Logout 1.0, sections 2 and 3). The requested `post_logout_redirect_uri` must match a registered one exactly, component by component:

- scheme and host are compared case-insensitively, and the scheme must be `https`
- the port must be the same number; `https://example.com:443/out` does not match a registered `https://example.com/out`
- the path must be identical, including case, trailing slash and percent-encoding
- the query must be identical, including parameter order; a missing, extra or reordered parameter, or a query on only one side (even a bare `?`), does not match
- a fragment (`#...`) or credentials (`user@`) in the requested URI never match

For example, with `https://rp.example:8443/logout/done?a=1&b=2` registered, only that URI (with any letter case in scheme and host) is accepted; `https://rp.example/logout/done?a=1&b=2`, `https://rp.example:8443/logout/done/?a=1&b=2` and `https://rp.example:8443/logout/done?b=2&a=1` are rejected. A rejected URI shows an error page and leaves the PeeringDB session as it was.

## ID token signing

OpenID Connect ID tokens are signed with RS256. Verify them with the public keys published at `/oauth2/.well-known/jwks.json`.

HS256 is not supported: client secrets are stored hashed, so they cannot serve as the HMAC signing key. The application form no longer offers it and discovery no longer advertises it. An application still set to HS256 gets an `unauthorized_client` error whenever an ID token would be issued, until its owner switches it to RS256.

An application set to "No OIDC support" that requests the `openid` scope gets an `invalid_scope` error whenever an ID token would be issued: a 400 from the token endpoint, or for implicit and hybrid responses that include `id_token` a redirect back to the client from the authorization endpoint.

Operators can list, migrate and/or notify the owners of remaining HS256 applications whose secret is hashed with `pdb_oauth_hs256` (dry run unless `--commit`).
