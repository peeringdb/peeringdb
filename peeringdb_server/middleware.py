"""
Custom django middleware.
"""

import base64

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse, JsonResponse
from django.middleware.common import CommonMiddleware
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

from peeringdb_server.context import current_request
from peeringdb_server.models import OrganizationAPIKey, UserAPIKey
from peeringdb_server.permissions import get_key_from_request

ERR_MULTI_AUTH = "Cannot authenticate through Authorization header while logged in. Please log out and try again."


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
                        "account_confirm_email", kwargs={"key": request.resolver_match.kwargs.get("key")}
                    ),
                )

            if request.path in NEW_SESSION_VALID_PATHS:

                # path is valid for a new session, proceed normally

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

            # Get the username and password from the HTTP auth header.
            username, password = self.get_username_and_password(http_auth)
            # Check if the username and password are valid.
            user = authenticate(username=username, password=password)

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

            # If api key is not valid return 401 Unauthorized
            if not api_key:
                if len(req_key) > 16:
                    req_key = req_key[:16]
                request.auth_id = f"apikey_{req_key}"
                return self.response_unauthorized(
                    request, message="Invalid API key", status=401
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

        if hasattr(request, "auth_id"):
            # Sanitizes the auth_id
            request.auth_id = request.auth_id.replace(" ", "_")
            # If auth_id ends with a 401 make sure is it limited to 16 bytes
            if response.status_code == 401 and len(request.auth_id) > 16:
                if not request.auth_id.startswith("apikey_"):
                    request.auth_id = request.auth_id[:16]

            response["X-Auth-ID"] = request.auth_id
        return response


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
                    response[
                        "Cache-Control"
                    ] = f"s-maxage={settings.CACHE_CONTROL_API_CACHE}"
            elif settings.CACHE_CONTROL_API:

                # NO API CACHE

                response["Cache-Control"] = f"s-maxage={settings.CACHE_CONTROL_API}"

        elif match.url_name in self.dynamic_views:

            # DYNAMIC CONTENT VIEW

            if settings.CACHE_CONTROL_DYNAMIC_PAGE:
                response[
                    "Cache-Control"
                ] = f"s-maxage={settings.CACHE_CONTROL_DYNAMIC_PAGE}"

        elif match.url_name in self.static_views:

            # STATIC CONTENT VIEW

            if settings.CACHE_CONTROL_STATIC_PAGE:
                response[
                    "Cache-Control"
                ] = f"s-maxage={settings.CACHE_CONTROL_STATIC_PAGE}"

        return response
