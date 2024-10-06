from oauth2_provider.oauth2_validators import Grant, OAuth2Validator

from mainsite.oauth2 import claims
from mainsite.oauth2.scopes import SupportedScopes
from peeringdb_server.context import current_request
from peeringdb_server.models import OAuthAccessTokenInfo, OAuthGrantInfo

# import SessionStore


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

        The info holds the AMR values as passed on the Grant instance.
        """

        # create the token as usual
        token = super()._create_access_token(
            expires, request, token, source_refresh_token
        )

        # get the grant instance by the code passed in the
        # request body
        body = dict(request.decoded_body)
        code = body.get("code")

        try:
            # get the grant info instance by the grant instance
            grant = Grant.objects.get(code=code, application=request.client)
            grant_info = grant.grant_info
        except (Grant.DoesNotExist, OAuthGrantInfo.DoesNotExist):
            # if the grant info instance does not exist, set it to None
            grant_info = None

        # create the access token info instance
        OAuthAccessTokenInfo.objects.create(
            access_token=token,
            amr=grant_info.amr if grant_info else "",
        )

        return token

    def _create_authorization_code(self, request, code, expires=None):
        """
        This is the method that creates the AuthorizationGrant instance

        We override it so we can attach the OAuthGrantInfo instance to the grant.

        The info holds the AMR values as set in the user's authenticated session.
        """

        # `request` is a sanitized oauthlib.common.Request instance
        # and hasn't parsed cookies and/or loaded the django session.
        #
        # to get the amr values, we need to access the user's session
        # and we can use the current_request context manager to do that
        with current_request() as django_request:
            if django_request:
                session = django_request.session
                amr = session.get("amr", [])
            else:
                amr = []

        # create the grant as usual
        grant = super()._create_authorization_code(request, code, expires=expires)

        # create the grant info instance
        OAuthGrantInfo.objects.create(
            grant=grant,
            amr=",".join(amr),
        )

        return grant
