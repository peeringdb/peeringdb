"""
Custom rate limit handlers for the REST API
"""

from django.conf import settings
from rest_framework import throttling
from rest_framework.exceptions import PermissionDenied

from peeringdb_server.permissions import get_org_key_from_request, get_user_from_request


class IXFImportThrottle(throttling.UserRateThrottle):
    scope = "ixf_import_request"

    def get_cache_key(self, request, view):
        key = super().get_cache_key(request, view)
        ix = view.get_object()
        return f"{key}.{ix.id}"


class FilterThrottle(throttling.SimpleRateThrottle):

    """
    Base class for API throttling targeted at specific query filters

    Scope name will be 'filter_{self.filter_name}'
    """

    filter_name = None

    def __init__(self):
        pass

    def allow_request(self, request, view):

        # If the parameter specified in cls.filter_name
        # is set in request parameters, set the scope
        # accordingly

        if self.filter_name in request.query_params:
            self.scope = f"filter_{self.filter_name}"
        else:
            return True

        # user either comes from request.user, or user api key
        #
        # it will be None if an organization key is set or request
        # is anonymous
        self.user = user = get_user_from_request(request)
        self.org_key = org_key = get_org_key_from_request(request)

        # Neither user nor organzation key could be identified
        # Get user directly from request, which will likely return
        # an anonymous user instance

        if not org_key and not user:
            self.user = user = request.user

        # require authenticated user to use this filter ?

        require_auth = (
            getattr(
                settings, f"API_{self.filter_name.upper()}_FILTER_REQUIRE_AUTH", False
            )
            and user
        )

        # require verified user to use this filter ?

        require_verified = (
            getattr(
                settings,
                f"API_{self.filter_name.upper()}_FILTER_REQUIRE_VERIFIED",
                False,
            )
            and user
        )

        if (require_auth or require_verified) and not user.is_authenticated:
            raise PermissionDenied(
                f"Please authenticate to use the `{self.filter_name}` filter"
            )

        if require_verified and not user.is_verified_user:
            raise PermissionDenied(
                f"Please verify your account to use the `{self.filter_name}` filter"
            )

        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

        return super().allow_request(request, view)

    def get_cache_key(self, request, view):

        if self.org_key:
            ident = f"org-key:{self.org_key.prefix}"
        elif self.user and self.user.is_authenticated:
            ident = self.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {"scope": self.scope, "ident": ident}


class FilterDistanceThrottle(FilterThrottle):

    """
    Rate limiting for ?distance= queries
    """

    filter_name = "distance"
