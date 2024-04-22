from abc import ABC, abstractmethod

from django_grainy.util import Permissions
from oauth2_provider.models import Grant

from peeringdb_server.models import OAuthAccessTokenInfo, OAuthGrantInfo


class ScopedClaim(ABC):
    """Parent class for OIDC claims that will be rendered on scope matching."""

    def __init__(self, scopes):
        """Creates a new claim to be resolved for certain scopes.

        Args:
            scopes (List[str]): List of scopes the claim will be resolved for.
        """
        self.scopes = scopes

    def __call__(self, request):
        """Evaluate the current claim for the provided request context.

        Args:
            request (`oauthlib.common.Request`): Request wrapper containing scope, claims, and the Django user object.

        Returns:
            Any: Resolved claim for the given user, requested claims, and OAuth2 scope.
        """
        if any(scope in self.scopes for scope in request.scopes):
            return self.enact(request)

    @abstractmethod
    def enact(self, request):
        """Claim resolver to be implemented by any claim provider.

        Args:
            request (`oauthlib.common.Request`): Request wrapper containing scope, claims, and the Django user object.
        """
        pass


class UserId(ScopedClaim):
    def enact(self, request):
        return request.user.id


class GivenName(ScopedClaim):
    def enact(self, request):
        return request.user.first_name


class FamilyName(ScopedClaim):
    def enact(self, request):
        return request.user.last_name


class Name(ScopedClaim):
    def enact(self, request):
        return request.user.full_name


class UserVerified(ScopedClaim):
    def enact(self, request):
        return request.user.is_verified_user


class Email(ScopedClaim):
    def enact(self, request):
        return request.user.email


class EmailVerified(ScopedClaim):
    def enact(self, request):
        return request.user.email_confirmed


class Networks(ScopedClaim):
    def enact(self, request):
        user_perms = Permissions(request.user)
        return [
            self._get_network_permissions(user_perms, network)
            for network in request.user.networks
        ]

    def _get_network_permissions(self, user_permissions, network):
        perms = user_permissions.get(network.grainy_namespace)
        return dict(
            id=network.id,
            name=network.name,
            asn=network.asn,
            perms=perms,
        )


class AMR(ScopedClaim):
    def enact(self, request):
        try:
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

            amr = grant_info.amr if grant_info else ""
            if amr:
                amr = amr.split(",")
            else:
                amr = []
        except OAuthAccessTokenInfo.DoesNotExist:
            amr = []
        return amr
