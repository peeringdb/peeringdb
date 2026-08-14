"""
Django HTTPRequest utilities.
"""

from __future__ import annotations

from django.http import HttpRequest

from peeringdb_server.context import current_request


def bypass_validation(
    request: HttpRequest | None = None, check_admin: bool = False
) -> bool:
    """
    Return whether the specified request is to bypass
    certain data quality validations. (#741)

    If not request is passed, attempt to get
    the current request from the current request
    context.

    If no request can be obtained this will return False.
    """

    if not request:
        with current_request() as _request:
            request = _request

    if not request or not getattr(request, "user", None):
        return False

    if check_admin:
        if not request or getattr(request, "path", None).startswith("/cp/") is not True:  # type: ignore[union-attr]
            return False

    return request.user.is_superuser
