# from django_grainy.rest import ModelViewSetPermissions, PermissionDenied
from rest_framework_api_key.permissions import KeyParser
from rest_framework.permissions import BasePermission

from django_grainy.helpers import request_method_to_flag

from peeringdb_server.models import (
    OrganizationAPIKey,
    UserAPIKey,
    Group,
    User
)
from django.contrib.auth.models import AnonymousUser

import grainy.const as grainy_constant
from grainy.core import NamespaceKeyApplicator
from django.conf import settings

# from django_grainy.const import *
from django_grainy.util import Permissions


def validate_rdap_user_or_key(request, rdap):
    user = get_user_from_request(request)
    if user:
        return user.validate_rdap_relationship(rdap)

    org_key = get_org_key_from_request(request)
    if org_key:
        return validate_rdap_org_key(org_key, rdap)

    return False


def validate_rdap_org_key(org_key, rdap):
    for email in rdap.emails:
        if email.lower() == org_key.email.lower():
            return True
    return False


def get_key_from_request(request):
    """ Use the default KeyParser from drf-api-keys to pull the key out of the request
    """
    return KeyParser().get(request)


def get_permission_holder_from_request(request):
    """ Returns either an API Key instance or User instance
    depending on how the request is Authenticated.
    """
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


def get_user_from_request(request):
    """
    Returns a user from the request if the request
    was made with either a User or UserAPIKey.

    If request was made with OrgKey, returns None.
    """
    perm_holder = get_permission_holder_from_request(request)
    if type(perm_holder) == User:
        return perm_holder
    elif type(perm_holder) == UserAPIKey:
        return perm_holder.user
    elif type(perm_holder) == OrganizationAPIKey:
        return None

    return None


def get_org_key_from_request(request):
    """
    Returns a org key from the request if the request
    was made with an OrgKey.

    Otherwise returns None.
    """
    perm_holder = get_permission_holder_from_request(request)

    if type(perm_holder) == OrganizationAPIKey:
        return perm_holder

    return None


def get_user_key_from_request(request):
    """
    Returns a user api key from the request if the request
    was made with an User API Key.

    Otherwise returns None.
    """
    perm_holder = get_permission_holder_from_request(request)

    if type(perm_holder) == UserAPIKey:
        return perm_holder

    return None


def check_permissions_from_request(request, target, flag, **kwargs):
    """ Call the check_permissions util but takes a request as
    input, not a permission-holding object
    """
    perm_obj = get_permission_holder_from_request(request)
    print(target)
    print(flag)
    return check_permissions(perm_obj, target, flag, **kwargs)


def check_permissions(obj, target, permissions, **kwargs):
    """ Users the provided permission holding object to initialize
    the Permissions Util, which then checks permissions.
    """
    if not hasattr(obj, "_permissions_util"):
        obj._permissions_util = init_permissions_helper(obj)

    return obj._permissions_util.check(target, permissions, **kwargs)


def init_permissions_helper(obj):
    """ Initializes the Permission Util based on
    if the provided object is a UserAPIKey, OrgAPIKey,
    or a different object.
    """
    if isinstance(obj, UserAPIKey):
        return return_user_api_key_perms(obj)
    if isinstance(obj, OrganizationAPIKey):
        return return_org_api_key_perms(obj)
    else:
        return Permissions(obj)


def return_user_api_key_perms(key):
    """
    Initializes the Permissions Util with the
    permissions of the user linked to the User API
    key.

    If the UserAPIKey is marked readonly, it downgrades
    all permissions to readonly.
    """
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
    # #Add user group perms
    org_usergroup = key.org.usergroup
    permissions.pset.update(
        org_usergroup.grainy_permissions.permission_set().permissions,
        override=False
    )

    # # Add general user group perms
    general_usergroup = Group.objects.get(id=settings.USER_GROUP_ID)
    permissions.pset.update(
        general_usergroup.grainy_permissions.permission_set().permissions,
        override=False
    )
    for ns, level in permissions.pset.permissions.items():
        print("PERM", ns, f"{level.value}")
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
