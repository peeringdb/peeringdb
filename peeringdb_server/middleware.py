"""
Custom django middleware.
"""

from peeringdb_server.context import current_request


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
