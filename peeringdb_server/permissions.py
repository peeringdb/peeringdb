# from django_grainy.rest import ModelViewSetPermissions, PermissionDenied
from rest_framework_api_key.permissions import KeyParser
from rest_framework.permissions import BasePermission

from django_grainy.helpers import request_method_to_flag
from django_grainy.util import check_permissions as _check_perms

from peeringdb_server.models import OrganizationAPIKey, OrganizationAPIPermission
from django.contrib.auth.models import AnonymousUser


def get_key_from_request(request):
    return KeyParser().get(request)


def check_permissions(request, target, flag):
    """
    Determines if a request's permissions are being set through an API key
    or user authorization and then checks permissions accordingly.
    """

    key = get_key_from_request(request)
    if key is not None:
        # See if it's an org key
        print("Checking key")
        try:
            api_key = OrganizationAPIKey.objects.get_from_key(key)
            return _check_perms(api_key, target, flag)

        except OrganizationAPIKey.DoesNotExist as exc:
            print(exc)

    # User authorization
    if hasattr(request, "user"):
        return _check_perms(request.user, target, flag)

    # For testing
    return False


class ModelViewSetPermissions(BasePermission):
    """
    Use as a permission class on a ModelRestViewSet
    to automatically wire up the following views
    to the correct permissions based on the handled object
    - retrieve
    - list
    - create
    - destroy
    - update
    - partial update
    """

    def has_permission(self, request, view):
        if hasattr(view, "Grainy"):
            flag = request_method_to_flag(request.method)
            return check_permissions(request, view, flag)

        # view has not been grainy decorated

        return True

    def has_object_permission(self, request, view, obj):
        flag = request_method_to_flag(request.method)
        return check_permissions(request, obj, flag)
