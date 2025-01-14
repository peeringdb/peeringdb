"""
Authentication utilities for securing API access.

Provides decorators to enforce Basic Authentication or API Key Authentication on IX-F import preview.

"""

import base64

from django.contrib.auth import authenticate
from django.http import JsonResponse

from peeringdb_server.models import OrganizationAPIKey, UserAPIKey


def enable_basic_auth(fn):
    """
    A simple decorator to enable Basic Auth for a specific view.
    """

    def wrapped(request, *args, **kwargs):
        if "HTTP_AUTHORIZATION" in request.META:
            auth = request.META["HTTP_AUTHORIZATION"].split()
            if len(auth) == 2:
                if auth[0].lower() == "basic":
                    username, password = (
                        base64.b64decode(auth[1].encode("utf-8"))
                        .decode("utf-8")
                        .split(":", 1)
                    )
                    request.user = authenticate(username=username, password=password)
                    if not request.user:
                        return JsonResponse(
                            {"non_field_errors": ["Invalid credentials"]}, status=401
                        )
        return fn(request, *args, **kwargs)

    return wrapped


def enable_api_key_auth(fn):
    """
    A simple decorator to enable API Key for a specific view.
    """

    def wrapped(request, *args, **kwargs):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header:
            auth = auth_header.split()
            if len(auth) == 2 and auth[0].lower() == "api-key":
                credentials = auth[1]
                try:
                    api_key = UserAPIKey.objects.get_from_key(credentials)
                    if api_key.status != "active":
                        raise UserAPIKey.DoesNotExist
                    request.user = api_key.user
                except UserAPIKey.DoesNotExist:
                    try:
                        org_api_key = OrganizationAPIKey.objects.get_from_key(
                            credentials
                        )
                        if org_api_key.status != "active":
                            raise OrganizationAPIKey.DoesNotExist
                        request.org = org_api_key.org
                        authenticated_users = list(
                            request.org.admin_usergroup.user_set.filter(is_active=True)
                        ) + list(request.org.usergroup.user_set.filter(is_active=True))

                        request.user = next(
                            (
                                user
                                for user in authenticated_users
                                if user.is_authenticated
                            ),
                            None,
                        )

                    except OrganizationAPIKey.DoesNotExist:
                        return JsonResponse(
                            {"non_field_errors": ["Invalid API key"]}, status=403
                        )

        return fn(request, *args, **kwargs)

    return wrapped
