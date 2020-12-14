# from django_grainy.rest import ModelViewSetPermissions, PermissionDenied
from rest_framework_api_key.permissions import KeyParser
from rest_framework.permissions import BasePermission

from django_grainy.helpers import request_method_to_flag

from peeringdb_server.models import (
    OrganizationAPIKey,
    UserAPIKey,
    Group
)
from django.contrib.auth.models import AnonymousUser

import grainy.const as grainy_constant
from grainy.core import NamespaceKeyApplicator
from django.conf import settings

# from django_grainy.const import *
from django_grainy.util import Permissions


def get_key_from_request(request):
    return KeyParser().get(request)


def get_permission_holder_from_request(request):
    key = get_key_from_request(request)
    if key is not None:
        try:
            print("Checking if org key")
            api_key = OrganizationAPIKey.objects.get_from_key(key)
            print(f"Org key found: {api_key.prefix}")
            return api_key

        except OrganizationAPIKey.DoesNotExist:
            print("Not a valid org key")

        try:
            print("Checking if user key")
            api_key = UserAPIKey.objects.get_from_key(key)
            print(f"User key found {api_key.prefix}")
            return api_key

        except UserAPIKey.DoesNotExist:
            print("Not a valid user key.")

    if hasattr(request, "user"):
        print(f"Returning user: {request.user}")
        return request.user

    return AnonymousUser()


def check_permissions_from_request(request, target, flag, **kwargs):
    perm_obj = get_permission_holder_from_request(request)
    return check_permissions(perm_obj, target, flag, **kwargs)


def check_permissions(obj, target, permissions, **kwargs):
    if not hasattr(obj, "_permissions_util"):
        obj._permissions_util = init_permissions_helper(obj)

    return obj._permissions_util.check(target, permissions, **kwargs)


def init_permissions_helper(obj):
    if isinstance(obj, UserAPIKey):
        return return_user_api_key_perms(obj)
    if isinstance(obj, OrganizationAPIKey):
        return return_org_api_key_perms(obj)
    else:
        return Permissions(obj)


def return_user_api_key_perms(key):
    user = key.user
    permissions = Permissions(user)

    if key.readonly is True:
        readonly_perms = {
            ns: grainy_constant.PERM_READ for ns in permissions.pset.namespaces
        }
        permissions.pset.update(readonly_perms)

    return permissions


def return_org_api_key_perms(key):
    """
    Load Permissions util with OrgAPIKey perms
    and then add in that organization's user group perms
    and general user group permissions
    """
    permissions = Permissions(key)
    org = key.org

    org_usergroup = org.usergroup
    permissions.pset.update(
        org_usergroup.grainy_permissions.permission_set().permissions
    )

    general_usergroup = Group.objects.get(id=settings.USER_GROUP_ID)
    permissions.pset.update(
        general_usergroup.grainy_permissions.permission_set().permissions
    )

    return permissions


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
            perm_obj = get_permission_holder_from_request(request)
            flag = request_method_to_flag(request.method)
            return check_permissions(perm_obj, view, flag)

        # view has not been grainy decorated

        return True

    def has_object_permission(self, request, view, obj):
        perm_obj = get_permission_holder_from_request(request)
        flag = request_method_to_flag(request.method)
        return check_permissions(perm_obj, obj, flag)


class APIPermissionsApplicator(NamespaceKeyApplicator):
    @property
    def is_generating_api_cache(self):
        try:
            return getattr(settings, "GENERATING_API_CACHE", False)
        except IndexError:
            return False

    def __init__(self, request):
        super().__init__(None)
        perm_obj = get_permission_holder_from_request(request)
        self.permissions = init_permissions_helper(perm_obj)
        self.pset = self.permissions
        self.set_peeringdb_handlers()

        if self.is_generating_api_cache:
            self.drop_namespace_key = False

    def set_peeringdb_handlers(self):
        self.handler(
            "peeringdb.organization.*.network.*.poc_set.private", explicit=True
        )
        self.handler("peeringdb.organization.*.network.*.poc_set.users", explicit=True)
        self.handler(
            "peeringdb.organization.*.internetexchange.*", fn=self.handle_ixlan
        )

    def handle_ixlan(self, namespace, data):
        if "ixf_ixp_member_list_url" in data:
            visible = data["ixf_ixp_member_list_url_visible"].lower()
            _namespace = f"{namespace}.ixf_ixp_member_list_url.{visible}"

            perms = self.permissions.check(_namespace, 0x01, explicit=True)
            if not perms:
                del data["ixf_ixp_member_list_url"]
