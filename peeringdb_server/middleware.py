"""
Custom django middleware.
"""

from peeringdb_server.context import current_request
from django.middleware.common import CommonMiddleware
from django.conf import settings


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
