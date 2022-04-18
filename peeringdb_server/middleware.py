"""
Custom django middleware.
"""

import base64

from django.conf import settings
from django.contrib.auth import authenticate
from django.http import HttpResponse, JsonResponse
from django.middleware.common import CommonMiddleware
from django.utils.deprecation import MiddlewareMixin

from peeringdb_server.context import current_request
from peeringdb_server.models import OrganizationAPIKey, UserAPIKey
from peeringdb_server.permissions import get_key_from_request


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
            ("%s://www.%s" % (request.scheme, request.get_host()))
            if must_prepend
            else ""
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

    auth_id = None

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

        # Check if HTTP auth is valid and if the request is made with basic auth.
        if http_auth and http_auth.startswith("Basic "):
            # Get the username and password from the HTTP auth header.
            username, password = self.get_username_and_password(http_auth)
            # Check if the username and password are valid.
            user = authenticate(username=username, password=password)
            # if user is not authenticated return 401 Unauthorized
            if not user:
                self.auth_id = username
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
                self.auth_id = "apikey_%s" % (req_key)
                if len(req_key) > 16:
                    self.auth_id = self.auth_id[:16]
                return self.response_unauthorized(
                    request, message="Invalid API key", status=401
                )

            # If API key is provided, check if the user has an active session
            if api_key:
                self.auth_id = "apikey_%s" % req_key
                if request.session.get("_auth_user_id") and request.user.id:
                    if int(request.user.id) == int(
                        request.session.get("_auth_user_id")
                    ):

                        return self.response_unauthorized(
                            request,
                            message="Cannot authenticate through Authorization header while logged in. Please log out and try again.",
                            status=400,
                        )

    def process_response(self, request, response):

        if self.auth_id:
            # Sanitizes the auth_id
            self.auth_id = self.auth_id.replace(" ", "_")
            # If auth_id ends with a 401 make sure is it limited to 16 bytes
            if response.status_code == 401 and len(self.auth_id) > 16:
                if not self.auth_id.startswith("apikey_"):
                    self.auth_id = self.auth_id[:16]

            response["X-Auth-ID"] = self.auth_id
        return response
