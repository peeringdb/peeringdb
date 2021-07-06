from django.conf import settings
from rest_framework import throttling
from rest_framework.exceptions import PermissionDenied


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

        # require authenticated user to use this filter ?

        require_auth = getattr(
            settings, f"API_{self.filter_name.upper()}_FILTER_REQUIRE_AUTH", False
        )

        # require verified user to use this filter ?

        require_verified = getattr(
            settings, f"API_{self.filter_name.upper()}_FILTER_REQUIRE_VERIFIED", False
        )

        if (require_auth or require_verified) and not request.user.is_authenticated:
            raise PermissionDenied(
                f"Please authenticate to use the `{self.filter_name}` filter"
            )

        if require_verified and not request.user.is_verified_user:
            raise PermissionDenied(
                f"Please verify your account to use the `{self.filter_name}` filter"
            )

        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {"scope": self.scope, "ident": ident}


class FilterDistanceThrottle(FilterThrottle):

    """
    Rate limiting for ?distance= queries
    """

    filter_name = "distance"
