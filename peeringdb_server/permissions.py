"""
Utilities for permission handling.

Permission logic is handled through django-grainy.

API key auth is handled through djangorestframework-api-key.

Determine permission holder from request (api key or user).

Read only user api key handling.

Censor API output data according to permissions using grainy Applicators.
"""

# from django_grainy.rest import ModelViewSetPermissions, PermissionDenied
import grainy.const as grainy_constant
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django_grainy.helpers import request_method_to_flag

# from django_grainy.const import *
from django_grainy.util import Permissions
from grainy.core import NamespaceKeyApplicator
from rest_framework.permissions import BasePermission
from rest_framework_api_key.permissions import KeyParser

from peeringdb_server.models import Group, OrganizationAPIKey, User, UserAPIKey


def validate_rdap_user_or_key(request, rdap):
    user = get_user_from_request(request)
    if user:
        return user.validate_rdap_relationship(rdap)

    org_key = get_org_key_from_request(request)
    if org_key:
        return validate_rdap_org_key(org_key, rdap)

    return False


def get_email_from_user_or_key(request):
    user = get_user_from_request(request)
    if user:
        return user.email

    org_key = get_org_key_from_request(request)
    if org_key:
        return org_key.email
    return None


def validate_rdap_org_key(org_key, rdap):
    for email in rdap.emails:
        if email and email.lower() == org_key.email.lower():
            return True
    return False


def get_key_from_request(request):
    """Use the default KeyParser from drf-api-keys to pull the key out of the request."""
    return KeyParser().get(request)


def get_permission_holder_from_request(request):
    """Return either an API Key instance or User instance
    depending on how the request is Authenticated.
    """

    if hasattr(request, "_permission_holder"):
        return request._permission_holder

    key = get_key_from_request(request)
    if key is not None:
        try:
            api_key = OrganizationAPIKey.objects.get_from_key(key)
            request._permission_holder = api_key
            return api_key

        except OrganizationAPIKey.DoesNotExist:
            pass

        try:
            api_key = UserAPIKey.objects.get_from_key(key)
            request._permission_holder = api_key
            return api_key

        except UserAPIKey.DoesNotExist:
            pass

    if hasattr(request, "user"):
        request._permission_holder = request.user
        return request.user

    anon = AnonymousUser()
    request._permission_holder = anon
    return anon


def get_user_from_request(request):
    """
    Return a user from the request if the request
    was made with either a User or UserAPIKey.

    If request was made with OrgKey, returns None.
    """
    perm_holder = get_permission_holder_from_request(request)
    if isinstance(perm_holder, User):
        return perm_holder
    elif isinstance(perm_holder, UserAPIKey):
        return perm_holder.user
    elif isinstance(perm_holder, OrganizationAPIKey):
        return None

    return None


def get_org_key_from_request(request):
    """
    Return an org key from the request if the request
    was made with an OrgKey.

    Otherwise returns None.
    """
    perm_holder = get_permission_holder_from_request(request)

    if isinstance(perm_holder, OrganizationAPIKey):
        return perm_holder

    return None


def get_user_key_from_request(request):
    """
    Return a user API key from the request if the request
    was made with an User API Key.

    Otherwise returns None.
    """
    perm_holder = get_permission_holder_from_request(request)

    if isinstance(perm_holder, UserAPIKey):
        return perm_holder

    return None


def check_permissions_from_request(request, target, flag, **kwargs):
    """Call the check_permissions util but takes a request as
    input, not a permission-holding object.
    """
    perm_obj = get_permission_holder_from_request(request)
    return check_permissions(perm_obj, target, flag, **kwargs)


def check_permissions(obj, target, permissions, **kwargs):
    """Use the provided permission holding object to initialize
    the Permissions Util, which then checks permissions.
    """
    if not hasattr(obj, "_permissions_util"):
        obj._permissions_util = init_permissions_helper(obj)

    return obj._permissions_util.check(target, permissions, **kwargs)


def init_permissions_helper(obj):
    """Initialize the Permission Util based on
    whether the provided object is a UserAPIKey, OrgAPIKey,
    or a different object.
    """

    if hasattr(obj, "_permissions_util"):
        return obj._permissions_util

    if isinstance(obj, UserAPIKey):
        perms = return_user_api_key_perms(obj)
    elif isinstance(obj, OrganizationAPIKey):
        perms = return_org_api_key_perms(obj)
    else:
        perms = Permissions(obj)
        if isinstance(obj, User):
            for org in obj.organizations:
                org.adjust_permissions_for_periodic_reauth(obj, perms)

    obj._permissions_util = perms
    return perms


def return_user_api_key_perms(key):
    """
    Initialize the Permissions Util with the
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
    and general user group permissions.
    """
    permissions = Permissions(key)
    # #Add user group perms
    org_usergroup = key.org.usergroup
    permissions.pset.update(
        org_usergroup.grainy_permissions.permission_set().permissions, override=False
    )

    # # Add general user group perms
    general_usergroup = Group.objects.get(id=settings.USER_GROUP_ID)
    permissions.pset.update(
        general_usergroup.grainy_permissions.permission_set().permissions,
        override=False,
    )
    return permissions


class ModelViewSetPermissions(BasePermission):
    """
    Use as a permission class on a ModelRestViewSet
    to automatically wire up the following views
    to the correct permissions based on the handled object:
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

        if isinstance(request, AnonymousUser):
            perm_obj = request
        else:
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
