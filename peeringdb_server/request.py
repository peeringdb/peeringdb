"""
Django HTTPRequest utilities
"""

from peeringdb_server.context import current_request


def bypass_validation(request=None):

    """
    Returns whether the specified request is to bypass
    certain data quality validations (#741)

    If not rquest is passed we will attempt to get
    the current request from the current request
    context.

    If no request can be obtained this will return False
    """

    if not request:
        with current_request() as _request:
            request = _request

    if not request or not getattr(request, "user", None):
        return False

    return request.user.is_superuser
