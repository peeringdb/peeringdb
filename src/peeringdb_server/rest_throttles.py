"""
Custom rate limit handlers for the REST API.
"""

import ipaddress
import re

from django.conf import settings
from django.core.cache import cache
from rest_framework import throttling
from rest_framework.exceptions import PermissionDenied

from peeringdb_server.models import EnvironmentSetting
from peeringdb_server.permissions import get_org_key_from_request, get_user_from_request


class IXFImportThrottle(throttling.UserRateThrottle):
    scope = "ixf_import_request"

    def get_cache_key(self, request, view):
        key = super().get_cache_key(request, view)
        ix = view.get_object()
        return f"{key}.{ix.id}"


class TargetedRateThrottle(throttling.SimpleRateThrottle):
    """
    Base class for targeted rate throttling depending
    on authentication status

    Rate throttle by
        - user (sess-auth, basic-auth, key),
        - org (key),
        - anonymous (inet, cdir)
    """

    scope_ip = "anon"
    scope_cidr = "anon"
    scope_user = "user"
    scope_org = "user"
    scope_admin = "user"

    def __init__(self):
        pass

    def ident_prefix(self, request):
        return ""

    def is_authenticated(self, request):
        self.user = get_user_from_request(request)
        self.org_key = get_org_key_from_request(request)
        return self.user is not None or self.org_key is not None

    def set_throttle_response(self, request, msg_setting):
        request.throttle_response_message = EnvironmentSetting.get_setting_value(
            msg_setting
        )

    def wait(self):
        """
        Returns the recommended next request time in seconds.

        This is a custom implmentation of the original wait() logic that can
        also handle dynamic downward adjustments of rate limits (through
        changing EnvironmentSetting variables for example)
        """
        if self.history:
            remaining_duration = self.duration - (self.now - self.history[-1])
        else:
            remaining_duration = self.duration

        available_requests = self.num_requests - len(self.history) + 1
        if available_requests < 1:
            # a negative/zero value only occurs when rate limit has been adjusted
            # while already being tracked for the requesting client

            remaining_duration = self.duration
            new_history = []
            for entry in self.history[: self.num_requests]:
                diff = self.now - entry
                if diff < self.duration:
                    new_history.append(entry)
                    remaining_duration = self.duration - diff

            self.history = new_history
            self.cache.set(self.key, self.history, self.duration)
            available_requests = self.num_requests - len(self.history) + 1

        if available_requests < 1:
            return None

        return remaining_duration / float(available_requests)

    def _allow_request_admin_auth(self, request, view, ident_prefix=""):
        self.ident = f"{ident_prefix}admin:{self.user.pk}"
        self.scope = self.scope_admin
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        allowed = super().allow_request(request, view)

        if not allowed:
            self.set_throttle_response(request, "API_THROTTLE_RATE_USER_MSG")

        return allowed

    def _allow_request_user_auth(self, request, view, ident_prefix=""):
        self.ident = f"{ident_prefix}user:{self.user.pk}"
        self.scope = self.scope_user
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        allowed = super().allow_request(request, view)

        if not allowed:
            self.set_throttle_response(request, "API_THROTTLE_RATE_USER_MSG")

        return allowed

    def _allow_request_org_auth(self, request, view, ident_prefix=""):
        self.ident = f"{ident_prefix}org:{self.org_key.org_id}"
        self.scope = self.scope_org
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

        allowed = super().allow_request(request, view)

        if not allowed:
            self.set_throttle_response(request, "API_THROTTLE_RATE_USER_MSG")

        return allowed

    def _allow_request_anon(self, request, view, ident_prefix=""):
        # first, check ip-address throttling
        # this is the default throttling mechanism for SimpleRateThrottle
        # so calling `get_ident` will give us the request ip-address

        ip_address = self.get_ident(request)

        # handle XFF

        ip_address = ip_address.split(",")[0].strip()

        if self.check_ip(request):
            self.ident = ip_address
            self.ident = f"{ident_prefix}{self.ident}"
            self.scope = self.scope_ip
            self.rate = self.get_rate()
            self.num_requests, self.duration = self.parse_rate(self.rate)
            allow_ip = super().allow_request(request, view)
        else:
            allow_ip = True

        # single ip was allowed, next check if the /24 block for the
        # ip is allowed as well.

        if self.check_cidr(request):
            ip = ipaddress.ip_address(ip_address)

            if ip.version == 4:
                self.ident = str(
                    ipaddress.ip_network(f"{ip_address}/32").supernet(new_prefix=24)
                )
            else:
                self.ident = str(
                    ipaddress.ip_network(f"{ip_address}/128").supernet(new_prefix=64)
                )

            self.ident = f"{ident_prefix}{self.ident}"
            self.scope = self.scope_cidr
            self.rate = self.get_rate()
            self.num_requests, self.duration = self.parse_rate(self.rate)
            allow_cidr = super().allow_request(request, view)
        else:
            allow_cidr = True

        # both the supernet as well as the single ip address
        # need to pass to allow the request

        allowed = allow_ip and allow_cidr

        if not allowed:
            self.set_throttle_response(request, "API_THROTTLE_RATE_ANON_MSG")

        return allowed

    def allow_request(self, request, view):
        # skip rate throttling for the api-cache generate process
        if getattr(settings, "GENERATING_API_CACHE", False):
            return True

        self.is_authenticated(request)

        ident_prefix = self.ident_prefix(request)

        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            # writes are now checked by WriteRateThrottle
            return True

        if self.user and self.user.is_superuser:
            # admin user

            if self.check_admin(request):
                return self._allow_request_admin_auth(request, view, ident_prefix)

            # user is admin and throttling for admins is not enabled past
            # this point

            return True

        if self.user and self.check_user(request):
            # authenticated user

            return self._allow_request_user_auth(request, view, ident_prefix)

        if self.org_key and self.check_org(request):
            # organization

            return self._allow_request_org_auth(request, view, ident_prefix)

        # at this point if the request is authenticated its ok to let through

        if self.user or self.org_key:
            return True

        # anonymous

        return self._allow_request_anon(request, view, ident_prefix)

    def check_user(self, request):
        return True

    def check_org(self, request):
        return True

    def check_ip(self, request):
        return True

    def check_cidr(self, request):
        return True

    def check_admin(self, request):
        return True

    def get_rate(self):
        if hasattr(self, "_rate"):
            return self._rate
        return super().get_rate()

    def get_cache_key(self, request, view):
        cache_key = self.cache_format % {"scope": self.scope, "ident": self.ident}
        return cache_key


class FilterThrottle(throttling.SimpleRateThrottle):
    """
    Base class for API throttling targeted at specific query filters.

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
    Rate limiting for ?distance= queries.
    """

    filter_name = "distance"


class APIAnonUserThrottle(TargetedRateThrottle):
    """
    General rate limiting for anonymous users via the request ip-address
    """

    def check_user(self, request):
        return False

    def check_org(self, request):
        return False

    def check_ip(self, request):
        self.scope = "anon"
        self._rate = EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_ANON")
        return True

    def check_cidr(self, request):
        return False


class APIUserThrottle(TargetedRateThrottle):
    """
    General rate limiting for authenticated requests (users or orgs)
    """

    def check_user(self, request):
        self.scope = "user"
        self._rate = EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_USER")
        return True

    def check_org(self, request):
        self.scope = "user"
        self._rate = EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_USER")
        return True

    def check_ip(self, request):
        return False

    def check_cidr(self, request):
        return False


class ResponseSizeThrottle(TargetedRateThrottle):
    """
    Rate limit repeated requests based request content-size

    See #1126 for rationale
    """

    scope_user = "response_size_user"
    scope_org = "response_size_org"
    scope_ip = "response_size_ip"
    scope_cidr = "response_size_cidr"

    @classmethod
    def size_cache_key(cls, request):
        """
        Returns the cache key to use for storing response size cache
        """

        # use the full request path plus appended query string
        # for the cache key

        return f"request-size:{request.get_full_path()}"

    @classmethod
    def cache_response_size(cls, request, size):
        """
        Caches the response size for the request

        The api renderer (renderers.py) calls this automatically
        when it renders the response
        """

        # This will be called for EVERY api request.
        #
        # Only write the response size cache if it does not exist yet
        # or is expired otherwise it introduces and unnecessary database
        # write operation at the back of each request.

        if cls.expected_response_size(request) is None:
            cache.set(
                cls.size_cache_key(request),
                size,
                settings.API_THROTTLE_REPEATED_REQUEST_CACHE_EXPIRY,
            )

    @classmethod
    def expected_response_size(cls, request):
        """
        Returns the expected response size (number of bytes) for the request as `int`

        It will return None if there is no cached response size for the request.
        """

        # Expected size was already determined for this request
        # object, return it

        if hasattr(request, "_expected_response_size"):
            return request._expected_response_size

        # Request content size is unkown at this point, so logic relies
        # on cached size stored from a previous request to the same
        # path
        #
        # if cache does not exist, its the first time this path is
        # requested and it can be allowed through.

        size = cache.get(cls.size_cache_key(request))
        request._expected_response_size = size

        return size

    def ident_prefix(self, request):
        return f"{request.get_full_path()}:"

    def check_user(self, request):
        return self._check_source(request, "user")

    def check_org(self, request):
        return self._check_source(request, "org")

    def check_ip(self, request):
        return self._check_source(request, "ip")

    def check_cidr(self, request):
        return self._check_source(request, "cidr")

    def _check_source(self, request, src):
        suffix = src.upper()
        enabled = EnvironmentSetting.get_setting_value(
            f"API_THROTTLE_REPEATED_REQUEST_ENABLED_{suffix}"
        )

        if not enabled:
            return False

        size = self.expected_response_size(request)

        if size is None:
            return False

        limit = EnvironmentSetting.get_setting_value(
            f"API_THROTTLE_REPEATED_REQUEST_THRESHOLD_{suffix}"
        )

        self._rate = EnvironmentSetting.get_setting_value(
            f"API_THROTTLE_REPEATED_REQUEST_RATE_{suffix}"
        )

        return size >= limit


class MelissaThrottle(TargetedRateThrottle):
    """
    Rate limits requests that do a melissa lookup (#1124)
    """

    scope_user = "melissa_user"
    scope_org = "melissa_org"
    scope_ip = "melissa_ip"
    scope_admin = "melissa_admin"

    def ident_prefix(self, request):
        return "melissa:"

    def check_user(self, request):
        return self._check_source(request, "user")

    def check_org(self, request):
        return self._check_source(request, "org")

    def check_ip(self, request):
        return self._check_source(request, "ip")

    def check_admin(self, request):
        return self._check_source(request, "admin")

    def check_cidr(self, request):
        return False

    def set_throttle_response(self, request, msg_setting):
        reason = getattr(request, "_melissa_throttle_reason", "melissa")
        super().set_throttle_response(request, msg_setting)
        request.throttle_response_message += f" - {reason}"

    def _check_source(self, request, src):
        suffix = src.upper()
        enabled = EnvironmentSetting.get_setting_value(
            f"API_THROTTLE_MELISSA_ENABLED_{suffix}"
        )

        rate_setting = f"API_THROTTLE_MELISSA_RATE_{suffix}"

        if not enabled:
            return False

        # case 1 - `state` filter to api end points

        if re.match(r"^/api/(fac|org)$", request.path) and request.GET.get("state"):
            self._rate = EnvironmentSetting.get_setting_value(rate_setting)
            request._melissa_throttle_reason = (
                "geo address normalization query on api filter for `state` field"
            )
            return True

        # case 2 -post/put to objects that trigger address normalization

        if re.match(r"^/api/(fac|org)/\d+$", request.path) and request.method in [
            "POST",
            "PUT",
        ]:
            request._melissa_throttle_reason = (
                "saving object that requires geo address normalization"
            )
            self._rate = EnvironmentSetting.get_setting_value(rate_setting)
            return True

        return False


class WriteRateThrottle(throttling.UserRateThrottle):
    scope = "write_api"
    default_rate = "2/minute"

    def __init__(self):
        super().__init__()
        self.rate = self.get_rate()

    def get_rate(self):
        rate = EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_WRITE")
        if rate:
            return rate
        else:
            return self.default_rate

    def get_cache_key(self, request, view):
        if request.method not in ["POST", "PUT", "PATCH", "DELETE"]:
            return None
        if request.user.is_authenticated:
            return f"throttle_{self.scope}_{request.user.pk}"
        else:
            return self.get_ident(request)
