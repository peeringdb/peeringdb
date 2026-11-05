from django.core.exceptions import ImproperlyConfigured
from oauth2_provider.oauth2_validators import Grant, OAuth2Validator
from oauthlib.oauth2.rfc6749.errors import (
    InvalidScopeError,
    UnauthorizedClientError,
    UnsupportedGrantTypeError,
)

from mainsite.oauth2 import claims
from mainsite.oauth2.scopes import SupportedScopes
from peeringdb_server.context import (
    current_request,
    is_issuing_at_authorization_endpoint,
)
from peeringdb_server.models import OAuthAccessTokenInfo, OAuthGrantInfo

# import SessionStore


HS256_UNSUPPORTED = (
    "This application is configured for HS256 ID token signing, which "
    "PeeringDB no longer supports. The application owner must switch it "
    "to RS256 in the application settings."
)


OPENID_UNSUPPORTED = (
    "This application does not support OpenID Connect, so no ID token can be "
    "issued for the openid scope. The application owner can enable it by "
    "selecting RS256 in the application settings."
)


PASSWORD_GRANT_UNSUPPORTED = (
    "The resource owner password credentials grant is not supported. "
    "Use the authorization code grant with PKCE instead."
)


class IDTokenErrorHeadersMixin:
    @property
    def headers(self):
        # raised past the grant handler, so django-oauth-toolkit builds the
        # response from these headers alone instead of oauthlib's defaults
        return {
            **super().headers,
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        }


class IDTokenSigningUnsupported(IDTokenErrorHeadersMixin, UnauthorizedClientError):
    description = HS256_UNSUPPORTED


class OpenIDScopeUnsupported(IDTokenErrorHeadersMixin, InvalidScopeError):
    description = OPENID_UNSUPPORTED


def hs256_signing_unavailable(application):
    """
    Returns True for an HS256 application whose client secret is stored
    hashed and so cannot be used as the HMAC signing key (#2055)
    """

    if application.algorithm != application.HS256_ALGORITHM:
        return False
    try:
        application.jwk_key
    except ImproperlyConfigured:
        return True
    return False


def uses_password_grant(application):
    """
    Returns True for an application registered with the password grant,
    whose tokens are refused since that grant is no longer supported (#519)
    """

    return (
        application is not None
        and application.authorization_grant_type == application.GRANT_PASSWORD
    )


class OIDCValidator(OAuth2Validator):
    # https://django-oauth-toolkit.readthedocs.io/en/latest/changelog.html#id12
    oidc_claim_scope = None

    def get_additional_claims(self):
        """PeeringDB-specific claims added to the standard claims defined in a JWT token.

        These claims will be omitted if the scope requested does not match any
        of the scopes the claim is associated with.

        Returns:
            List[Tuple(str, callable)]: List of claims to be resolved from request details.
        """
        return [
            # Standard claims
            # https://openid.net/specs/openid-connect-core-1_0.html#StandardClaims
            ("name", claims.Name([SupportedScopes.PROFILE])),
            ("given_name", claims.GivenName([SupportedScopes.PROFILE])),
            ("family_name", claims.FamilyName([SupportedScopes.PROFILE])),
            ("email", claims.Email([SupportedScopes.EMAIL])),
            ("email_verified", claims.EmailVerified([SupportedScopes.EMAIL])),
            # Custom claims
            ("id", claims.UserId([SupportedScopes.PROFILE])),
            ("verified_user", claims.UserVerified([SupportedScopes.PROFILE])),
            ("networks", claims.Networks([SupportedScopes.NETWORKS])),
            ("amr", claims.AMR([SupportedScopes.OPENID])),
        ]

    def validate_bearer_token(self, token, scopes, request):
        """
        Refuses tokens of deactivated users and of applications registered
        with the password grant (#519), and records the token's user on the
        request as `oauth_user` for the request log

        Only endpoints that validate the token themselves get here, and they
        must not treat the request as a logged-in session, so `request.user`
        is left alone.
        """

        valid = super().validate_bearer_token(token, scopes, request)
        # client credentials tokens have no user
        if valid and (request.user is None or not request.user.is_active):
            request.oauth2_error = {
                "error": "invalid_token",
                "error_description": "The access token is invalid.",
            }
            return False
        if valid and uses_password_grant(request.client):
            request.oauth2_error = {
                "error": "invalid_token",
                "error_description": "The access token is invalid.",
            }
            return False
        if valid:
            with current_request() as django_request:
                if django_request is not None:
                    django_request.oauth_user = request.user
        return valid

    def validate_user(self, username, password, client, request, *args, **kwargs):
        """
        Refuses the password grant without checking the credentials (#519)

        oauthlib calls this before validate_grant_type, where
        COMPLIANT_BCP_RFC9700_PASSWORD_GRANT refuses it, so the refusal has to
        happen here for the response not to depend on the password.
        """

        raise UnsupportedGrantTypeError(
            description=PASSWORD_GRANT_UNSUPPORTED, request=request
        )

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        """
        Refuses refresh tokens of deactivated users and of applications
        registered with the password grant (#519)
        """

        valid = super().validate_refresh_token(
            refresh_token, client, request, *args, **kwargs
        )
        return valid and request.user.is_active and not uses_password_grant(client)

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        """
        Refuses authorization codes of deactivated users
        """

        valid = super().validate_code(client_id, code, client, request, *args, **kwargs)
        return valid and request.user.is_active

    def _create_access_token(self, expires, request, token, source_refresh_token=None):
        """
        This is the method that creates the AccessToken instance

        We override it so we can attach the OAuthAccessTokenInfo instance to the token.

        The info holds the AMR values as passed on the Grant instance, or
        those of the login session for a token issued at the authorization
        endpoint (implicit and hybrid flows, #490).
        """

        # create the token as usual
        token = super()._create_access_token(
            expires, request, token, source_refresh_token
        )

        if is_issuing_at_authorization_endpoint():
            amr = ",".join(claims.session_amr())
        else:
            # get the grant instance by the code passed in the
            # request body
            body = dict(request.decoded_body or [])
            code = body.get("code")

            try:
                # get the grant info instance by the grant instance
                grant = Grant.objects.get(code=code, application=request.client)
                grant_info = grant.grant_info
            except (Grant.DoesNotExist, OAuthGrantInfo.DoesNotExist):
                # if the grant info instance does not exist, set it to None
                grant_info = None
            amr = grant_info.amr if grant_info else ""

        # create the access token info instance
        OAuthAccessTokenInfo.objects.create(access_token=token, amr=amr)

        return token

    def _create_authorization_code(self, request, code, expires=None):
        """
        This is the method that creates the AuthorizationGrant instance

        We override it so we can attach the OAuthGrantInfo instance to the grant.

        The info holds the AMR values as set in the user's authenticated session.
        """

        amr = claims.session_amr()

        # create the grant as usual
        grant = super()._create_authorization_code(request, code, expires=expires)

        # create the grant info instance
        OAuthGrantInfo.objects.create(
            grant=grant,
            amr=",".join(amr),
        )

        return grant

    def finalize_id_token(self, id_token, token, token_handler, request):
        """
        Rejects the request with an OAuth error instead of failing to sign
        the ID token: invalid_scope for an application without OIDC support
        (#490), unauthorized_client for an HS256 application (#2055)

        oauthlib saves the token only after this runs, so nothing is issued.
        """

        if request.client.algorithm == request.client.NO_ALGORITHM:
            raise OpenIDScopeUnsupported(request=request)
        if hs256_signing_unavailable(request.client):
            raise IDTokenSigningUnsupported(request=request)
        return super().finalize_id_token(id_token, token, token_handler, request)

    def _get_client_by_audience(self, audience):
        """
        Treats ID tokens of an application that cannot sign them as invalid
        instead of failing to load its key (#2055)

        #2022 filters this lookup to signing applications as well; the two
        checks belong in one definition, each pinned by its own test.
        """

        application = super()._get_client_by_audience(audience)
        if application and hs256_signing_unavailable(application):
            return None
        return application
