from django.core.exceptions import ImproperlyConfigured
from oauth2_provider.oauth2_validators import Grant, OAuth2Validator
from oauthlib.oauth2.rfc6749.errors import InvalidScopeError, UnauthorizedClientError

from mainsite.oauth2 import claims
from mainsite.oauth2.scopes import SupportedScopes
from peeringdb_server.context import is_issuing_at_authorization_endpoint
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
