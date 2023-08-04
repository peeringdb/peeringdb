from oauth2_provider.oauth2_validators import OAuth2Validator

from mainsite.oauth2 import claims
from mainsite.oauth2.scopes import SupportedScopes


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
        ]
