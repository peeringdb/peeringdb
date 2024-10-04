"""
Custom django middleware.
"""

import base64
import binascii
import json

import django_read_only
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import caches
from django.http import HttpResponse, JsonResponse
from django.middleware.common import CommonMiddleware
from django.urls import reverse
from django.utils import translation
from django.utils.deprecation import MiddlewareMixin

from peeringdb_server.context import current_request
from peeringdb_server.models import OrganizationAPIKey, UserAPIKey
from peeringdb_server.permissions import get_key_from_request

ERR_MULTI_AUTH = "Cannot authenticate through Authorization header while logged in. Please log out and try again."
ERR_BASE64_DECODE = "Corrupt base64 input."
ERR_UNKNOWN = "Unknown error."
ERR_VALUE_ERROR = "Invalid Input."


def get_auth_identity(request):
    """
    Returns a string that uniquely identifies the authentication
    method used for the request.

    This is used to cache negative authentication responses
    """

    auth_value = request.META.get("HTTP_AUTHORIZATION", "")
    session_id = request.COOKIES.get("sessionid", "")[:10]

    if session_id:
        return f"session__{session_id}"

    auth_type = None

    if auth_value:
        try:
            method, auth_value = auth_value.split(" ", 1)
            if method.lower() == "basic":
                # base 64 auth value is decoded and split to get the username
                auth_value = (
                    base64.b64decode(auth_value).decode("utf-8").split(":", 1)[0]
                )
                auth_type = "user"
            elif method.lower() == "api-key":
                # api key auth value is truncated to prefix
                auth_value = auth_value.split(".", 1)[0]
                auth_type = "key"
            return f"{auth_type}__{auth_value}"
        except Exception:
            # avoid 500 error in decode and split
            pass

    return "anonymous__guest"


class PDBSessionMiddleware(SessionMiddleware):
    """
    As PeeringDB gets a lot of repeated anonymous requests that do not
    store and re-use session cookies this lead to substantial amount of junk
    django session objects.

    It was decided in #1205 that new django sessions are only to be established
    On the login and registration processes.
    """

    def process_response(self, request, response):
        try:
            request.session.is_empty()
        except AttributeError:
            return response
        session_key = request.session.session_key

        if session_key and not request.session.is_empty():
            # request specifies session and session is not empty, proceed normally
            if settings.DJANGO_READ_ONLY:
                with django_read_only.temp_writes():
                    return super().process_response(request, response)
            else:
                return super().process_response(request, response)

        elif not request.COOKIES.get(settings.SESSION_COOKIE_NAME):
            # request specifies no session, check if the request.path falls into the
            # set of valid paths for new session creation

            NEW_SESSION_VALID_PATHS = [
                reverse("login"),
                reverse("register"),
                reverse("username-retrieve"),
                reverse("username-retrieve-initiate"),
                reverse("reset-password"),
            ]

            if request.resolver_match and "key" in request.resolver_match.kwargs:
                NEW_SESSION_VALID_PATHS.append(
                    reverse(
                        "account_confirm_email",
                        kwargs={"key": request.resolver_match.kwargs.get("key")},
                    ),
                )

            if request.path in NEW_SESSION_VALID_PATHS:
                # path is valid for a new session, proceed normally
                if settings.DJANGO_READ_ONLY:
                    with django_read_only.temp_writes():
                        return super().process_response(request, response)
                else:
                    return super().process_response(request, response)
            else:
                # path is NOT valid for a new session, abort session
                # creation

                return response

        # proceed normally

        return super().process_response(request, response)


class CurrentRequestContext:
    """
    Middleware that sets the current request context.

    This allows access to the current request from anywhere.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with current_request(request):
            return self.get_response(request)


class HttpResponseUnauthorized(HttpResponse):
    status_code = 401


class PDBCommonMiddleware(CommonMiddleware):
    def has_subdomain(self, request):
        # Check if the request has a subdomain and does not start with www
        host = request.get_host()
        if host.startswith("www.") or (len(host.split(".")) > 2):
            return True
        return False

    def process_request(self, request):
        must_prepend = settings.PDB_PREPEND_WWW and not self.has_subdomain(request)
        redirect_url = (
            (f"{request.scheme}://www.{request.get_host()}") if must_prepend else ""
        )
        # Check if a slash should be appended
        if self.should_redirect_with_slash(request):
            path = self.get_full_path_with_slash(request)
        else:
            path = request.get_full_path()

        # Return a redirect if necessary

        if redirect_url or path != request.get_full_path():
            redirect_url += path
            return self.response_redirect_class(redirect_url)


class PDBPermissionMiddleware(MiddlewareMixin):
    """
    Middleware that checks if the current user has the correct permissions
    to access the requested resource.
    """

    def get_username_and_password(self, http_auth):
        """
        Get the username and password from the HTTP auth header.
        """
        # Check if the HTTP auth header is valid.
        if http_auth.startswith("Basic "):
            # Get the HTTP auth header without the "Basic " prefix.
            http_auth = http_auth[6:]
        else:
            # Return an empty tuple.
            return tuple()
        # Decode the HTTP auth header.
        http_auth = base64.b64decode(http_auth).decode("utf-8")
        # If username or password is empty return an empty tuple.
        # Split the username and password from the HTTP auth header.
        userpw = http_auth.split(":", 1)

        return userpw

    def response_unauthorized(self, request, status=None, message=None):
        """
        Return a Unauthorized response.
        """
        return JsonResponse({"meta": {"error": message}}, status=status)

    def process_request(self, request):
        http_auth = request.META.get("HTTP_AUTHORIZATION", None)
        req_key = get_key_from_request(request)
        api_key = None

        # session auth already exists, set x-auth-id value and return

        if request.user.is_authenticated:
            request.auth_id = f"u{request.user.id}"

            # request attempting to provide separate authentication while
            # already authenticated through session cookie, fail with
            # bad request

            if req_key or http_auth:
                return self.response_unauthorized(
                    request,
                    message=ERR_MULTI_AUTH,
                    status=400,
                )

            return

        # Check if HTTP auth is valid and if the request is made with basic auth.

        if http_auth and http_auth.startswith("Basic "):
            error = None
            try:
                # Get the username and password from the HTTP auth header.
                username, password = self.get_username_and_password(http_auth)
            except (
                UnicodeDecodeError,
                binascii.Error,
            ):
                error = ERR_BASE64_DECODE
            except ValueError:
                error = ERR_VALUE_ERROR
            except Exception:
                error = ERR_UNKNOWN
            if error:
                # avoid 500 error when decode and split in the get_username_and_password
                return self.response_unauthorized(request, message=error, status=400)

            user = None
            try:
                user_object = get_user_model().objects.get(username=username)

                if not user_object.is_active:
                    # If user is inactive, cache the inactive auth
                    # and return unauthorized

                    identifier = get_auth_identity(request)
                    caches["negative"].set(
                        f"inactive__{identifier}",
                        True,
                        timeout=settings.NEGATIVE_CACHE_EXPIRY_INACTIVE_AUTH,
                    )

                    return self.response_unauthorized(
                        request, message="Inactive account", status=401
                    )
                else:
                    # Check if the username and password are valid.
                    user = authenticate(username=username, password=password)
            except get_user_model().DoesNotExist:
                user_object = None

            # return username input in x-auth-id header
            if user:
                request.auth_id = f"u{user.id}"

            # if user is not authenticated return 401 Unauthorized
            else:
                # truncate the username if needed.
                if len(username) > 255:
                    request.auth_id = username[:255]
                else:
                    request.auth_id = username

                return self.response_unauthorized(
                    request, message="Invalid username or password", status=401
                )

        # Check API keys
        if req_key:
            try:
                api_key = OrganizationAPIKey.objects.get_from_key(req_key)

            except OrganizationAPIKey.DoesNotExist:
                pass

            try:
                api_key = UserAPIKey.objects.get_from_key(req_key)

            except UserAPIKey.DoesNotExist:
                pass

            if not api_key:
                # If api key is not valid return 401 Unauthorized

                if len(req_key) > 16:
                    req_key = req_key[:16]
                request.auth_id = f"apikey_{req_key}"
                return self.response_unauthorized(
                    request, message="Invalid API key", status=401
                )
            elif api_key.revoked or api_key.status != "active":
                # If api key is revoked or inactive, cache as inactive
                # and return 401 Unauthorized

                identifier = get_auth_identity(request)
                caches["negative"].set(
                    f"inactive__{identifier}",
                    True,
                    timeout=settings.NEGATIVE_CACHE_EXPIRY_INACTIVE_AUTH,
                )

                return self.response_unauthorized(
                    request, message="Inactive API key", status=401
                )

            # If API key is provided, check if the user has an active session
            else:
                if isinstance(api_key, OrganizationAPIKey):
                    prefix = f"o{api_key.org_id}"
                else:
                    prefix = f"u{api_key.user_id}"

                request.auth_id = f"{prefix}_apikey_{api_key.prefix}"
                if request.session.get("_auth_user_id") and request.user.id:
                    if int(request.user.id) == int(
                        request.session.get("_auth_user_id")
                    ):
                        return self.response_unauthorized(
                            request,
                            message=ERR_MULTI_AUTH,
                            status=400,
                        )

    def process_response(self, request, response):
        response["X-Auth-Status"] = (
            "authenticated" if request.user.is_authenticated else "unauthenticated"
        )
        response["X-App-Version"] = settings.PEERINGDB_VERSION
        if hasattr(request, "auth_id"):
            # Sanitizes the auth_id
            request.auth_id = request.auth_id.replace(" ", "_")
            # If auth_id ends with a 401 make sure is it limited to 16 bytes
            if response.status_code == 401 and len(request.auth_id) > 16:
                if not request.auth_id.startswith("apikey_"):
                    request.auth_id = request.auth_id[:16]

            response["X-Auth-ID"] = request.auth_id
        return response


class RedisNegativeCacheMiddleware(MiddlewareMixin):
    """
    Middleware that uses Django's cache framework with Redis backend to cache error responses.
    """

    def process_response(self, request, response):
        """
        Process the response before it's sent to the client.
        """

        if not settings.NEGATIVE_CACHE_ENABLED:
            return response

        # Check if the response is an error response
        if response.status_code in [401, 403, 429]:
            # Generate the cache key
            cache_key = self.generate_cache_key(request)
            # Cache the response content and status code with specific expiry time
            cache_data = {
                "content": response.content.decode(),
                "status": response.status_code,
                "content-type": response.get("content-type"),
            }
            expiry_setting = f"NEGATIVE_CACHE_EXPIRY_{response.status_code}"
            caches["negative"].set(
                cache_key, cache_data, timeout=getattr(settings, expiry_setting)
            )

            # If the response is 401 or 403, increment the count for this IP address
            # so we can throttle it if it exceeds the limit
            if response.status_code in [401, 403]:
                throttle_key = self.generate_ratelimit_key(request)
                throttle_count = caches["negative"].get(throttle_key, 0)
                throttle_count += 1

                # cache for 1 minute
                caches["negative"].set(throttle_key, throttle_count, timeout=60)

        return response

    def process_request(self, request):
        """
        Process the request before it's passed to the view.
        """

        if not settings.NEGATIVE_CACHE_ENABLED:
            return

        # Check if inactive auth cache
        identifier = get_auth_identity(request)

        # Check if the IP address has been throttled for too many 401 or 403 responses
        throttle_key = self.generate_ratelimit_key(request)
        throttle_count = caches["negative"].get(throttle_key, 0)

        # If the count exceeds the limit, return a throttled error response
        if throttle_count > settings.NEGATIVE_CACHE_REPEATED_RATE_LIMIT:
            response = JsonResponse(
                {
                    "meta": {
                        "error": "Too many requests that resulted in 401 or 403 responses"
                    }
                },
                status=429,
            )
            response["X-Throttled-Response"] = "True"
            return response

        if identifier:
            inactive_cache = caches["negative"].get(f"inactive__{identifier}")
            if inactive_cache:
                if identifier.startswith("key__"):
                    response = JsonResponse(
                        {"meta": {"error": "Inactive API key"}}, status=401
                    )
                else:
                    response = JsonResponse(
                        {"meta": {"error": "Inactive account"}}, status=401
                    )
                response["X-Cached-Response"] = "True"
                return response

        # Generate the cache key
        cache_key = self.generate_cache_key(request)
        # Check if the response is cached
        cached_response = caches["negative"].get(cache_key)
        if (
            cached_response
            and cached_response.get("content-type") == "application/json"
        ):
            # Deserialize the cached response content and return it with the cached status code
            response = JsonResponse(
                json.loads(cached_response["content"]),
                safe=False,
                status=cached_response["status"],
            )
        elif cached_response:
            # Return the cached response as is
            response = HttpResponse(
                cached_response["content"],
                content_type=cached_response["content-type"],
                status=cached_response["status"],
            )
        else:
            # No cached response found, return
            return

        # Add a custom header to indicate that this is a cached response
        response["X-Cached-Response"] = "True"
        return response

    def get_ident(self, request):
        """
        Get the IP address of the client, taking both X-Forwarded-For and REMOTE_ADDR into account.
        """

        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        remote_addr = request.META.get("REMOTE_ADDR")
        return "".join(xff.split()) if xff else remote_addr

    def generate_ratelimit_key(self, request):
        return f"negcache__throttle__{self.get_ident(request)}"

    def generate_cache_key(self, request):
        """
        Generate the cache key using the IP address, HTTP_AUTHORIZATION value or session ID, request path, and URL parameters.
        """
        ip_address = self.get_ident(request)
        request_path = request.path
        url_parameters = request.GET.urlencode()
        identifier = get_auth_identity(request)
        method = request.method

        # Generate the key and sanitize it by replacing spaces and colons with underscores
        cache_key = f"negcache_{ip_address}__{identifier}__{method}__{request_path}__{url_parameters}"
        sanitized_cache_key = cache_key.replace(" ", "_").replace(":", "_")

        return sanitized_cache_key


class CacheControlMiddleware(MiddlewareMixin):
    """
    Sets the Cache-Control s-maxage header on responses
    """

    # views using CACHE_CONTROL_DYNAMIC_PAGE as value for s-maxage
    # views that will receive frequent update and require a shorter
    # TTL

    dynamic_views = [
        "sponsors",
        "home",
        # entity views (net, ix, fac, org, carrier)
        "net-view",
        "net-view-asn",
        "ix-view",
        "org-view",
        "fac-view",
        "carrier-view",
        # data views that fill select elements when editing
        # fac, ix, net, org or carrier
        "data-facilities",
        "data-asns",
    ]

    # views using CACHE_CONTROL_STATIC_PAGE as a value for s-maxage
    # views that generally dont change outside of deploys and can
    # support a longer TTL

    static_views = [
        "about",
        "aup",
        # data views that fill select elements when editing
        # fac, ix, net, org or carrier
        "data-countries",
        "data-enum",
        "data-locales",
    ]

    # views that support caching while authenticated
    # currently this NEEDS TO EXCLUDE anything that references
    # the logged in user and or data only available to the logged
    # in user

    authenticated_views = [
        # data views that fill select elements when editing
        # fac, ix, net, org or carrier
        "data-countries",
        "data-enum",
        "data-locales",
        "data-facilities",
        "data-asns",
    ]

    # REST api views are handled automatically and will use
    # the `CACHE_CONTROL_API_CACHE` setting for api-cache responses
    # and the `CACHE_CONTROL_API` setting for normal responses

    def process_response(self, request, response):
        # only on GET requests

        if request.method != "GET":
            return response

        # generally, requests that dont have a resolver match
        # are ignored as we are being specific which views
        # get the Cache-Control header at this point, rather
        # than applying some broad caching policy

        match = request.resolver_match

        if not match or not match.url_name:
            return response

        if (
            request.user.is_authenticated
            and match.url_name not in self.authenticated_views
        ):
            # request is authenticated, dont set cache-control
            # headers for authenticated responses.
            return response

        if match.namespace == "api":
            # REST API

            if getattr(response, "context_data", None):
                # API CACHE

                if (
                    response.context_data.get("apicache") is True
                    and settings.CACHE_CONTROL_API_CACHE
                ):
                    response["Cache-Control"] = (
                        f"s-maxage={settings.CACHE_CONTROL_API_CACHE}"
                    )
            elif settings.CACHE_CONTROL_API:
                # NO API CACHE

                response["Cache-Control"] = f"s-maxage={settings.CACHE_CONTROL_API}"

        elif match.url_name in self.dynamic_views:
            # DYNAMIC CONTENT VIEW

            if settings.CACHE_CONTROL_DYNAMIC_PAGE:
                response["Cache-Control"] = (
                    f"s-maxage={settings.CACHE_CONTROL_DYNAMIC_PAGE}"
                )

        elif match.url_name in self.static_views:
            # STATIC CONTENT VIEW

            if settings.CACHE_CONTROL_STATIC_PAGE:
                response["Cache-Control"] = (
                    f"s-maxage={settings.CACHE_CONTROL_STATIC_PAGE}"
                )

        return response


class ActivateUserLocaleMiddleware(MiddlewareMixin):
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, *view_args, **view_kwargs):
        # Check if the 'django_language' cookie is not set
        if not request.COOKIES.get("django_language"):
            if request.user.is_authenticated:
                translation.activate(request.user.locale)
