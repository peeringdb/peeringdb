from rest_framework import throttling


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

        if self.filter_name in request.GET or self.filter_name in request.POST:
            self.scope = f"filter_{self.filter_name}"
        else:
            return True

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
