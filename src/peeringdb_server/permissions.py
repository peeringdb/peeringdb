"""
Utilities for permission handling.

Permission logic is handled through django-grainy.

API key auth is handled through djangorestframework-api-key.

Determine permission holder from request (api key or user).

Read only user api key handling.

Censor API output data according to permissions using grainy Applicators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# from django_grainy.rest import ModelViewSetPermissions, PermissionDenied
import grainy.const as grainy_constant
from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q

# from django_grainy.const import *
from django_grainy.helpers import int_flags, request_method_to_flag
from django_grainy.helpers import namespace as grainy_namespace
from django_grainy.util import Permissions
from grainy.core import NamespaceKeyApplicator, PermissionSet
from rest_framework.permissions import BasePermission
from rest_framework_api_key.permissions import KeyParser

from peeringdb_server.models import (
    Group,
    OrganizationAPIKey,
    User,
    UserAPIKey,
)

if TYPE_CHECKING:
    from django.db.models import Model
    from django.http import HttpRequest
    from rdap.objects import RdapObject
    from rest_framework.views import APIView

    from peeringdb_server.models import Organization


def org_namespace_filter(org: Organization) -> Q:
    """
    Return a Q matching an org's own namespace and its descendants, and nothing
    else.

    A bare `namespace__startswith=org.grainy_namespace` compiles to
    `LIKE 'peeringdb.organization.5%'`, which also matches org 50, 500 and
    5000 -- so filtering on one org reached into unrelated ones (#2039).

    The exact-match half is load-bearing: the org-root grant is stored at
    exactly `peeringdb.organization.<id>` with no trailing separator, so a
    dotted-prefix-only filter would leave it behind on every save.
    """

    return Q(namespace=org.grainy_namespace) | Q(
        namespace__startswith=f"{org.grainy_namespace}."
    )


def validate_rdap_user_or_key(request: HttpRequest, rdap: RdapObject) -> bool:
    user = get_user_from_request(request)
    if user:
        return user.validate_rdap_relationship(rdap)

    org_key = get_org_key_from_request(request)
    if org_key:
        return validate_rdap_org_key(org_key, rdap)

    return False


def get_email_from_user_or_key(request: HttpRequest) -> str | None:
    user = get_user_from_request(request)
    if user:
        return user.email

    org_key = get_org_key_from_request(request)
    if org_key:
        return org_key.email
    return None


def org_key_email_is_verified(org_key: OrganizationAPIKey) -> bool:
    """
    Whether the key email is a verified email address of an active user of
    the key's organization, member or admin.
    """
    if not org_key.email:
        return False

    org = org_key.org
    emails = EmailAddress.objects.filter(
        verified=True,
        user__is_active=True,
        user__groups__in=[org.usergroup, org.admin_usergroup],
    ).values_list("email", flat=True)

    # compare in python, the db collation may be accent-insensitive
    key_email = org_key.email.lower()
    return any(email.lower() == key_email for email in emails)


def validate_rdap_org_key(org_key: OrganizationAPIKey, rdap: RdapObject) -> bool:
    """
    The key email is typed in by an org admin and never verified, so it only
    proves RDAP ownership while it is also a verified email address of a
    current admin of the key's organization.
    """
    if not any(
        email and email.lower() == org_key.email.lower() for email in rdap.emails
    ):
        return False

    # compare in python, the db collation may be accent-insensitive
    admin_emails = EmailAddress.objects.filter(
        verified=True,
        user__is_active=True,
        user__groups=org_key.org.admin_usergroup,
    ).values_list("email", flat=True)
    key_email = org_key.email.lower()
    return any(email.lower() == key_email for email in admin_emails)


def get_key_from_request(request: HttpRequest) -> str | None:
    """Use the default KeyParser from drf-api-keys to pull the key out of the request."""
    return KeyParser().get(request)


def get_permission_holder_from_request(
    request: HttpRequest,
) -> OrganizationAPIKey | UserAPIKey | User | AnonymousUser:
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


def get_user_from_request(request: HttpRequest) -> User | None:
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


def get_org_key_from_request(request: HttpRequest) -> OrganizationAPIKey | None:
    """
    Return an org key from the request if the request
    was made with an OrgKey.

    Otherwise returns None.
    """
    perm_holder = get_permission_holder_from_request(request)

    if isinstance(perm_holder, OrganizationAPIKey):
        return perm_holder

    return None


def get_user_key_from_request(request: HttpRequest) -> UserAPIKey | None:
    """
    Return a user API key from the request if the request
    was made with an User API Key.

    Otherwise returns None.
    """
    perm_holder = get_permission_holder_from_request(request)

    if isinstance(perm_holder, UserAPIKey):
        return perm_holder

    return None


def check_permissions_from_request(
    request: HttpRequest, target: Any, flag: int, **kwargs: Any
) -> bool:
    """Call the check_permissions util but takes a request as
    input, not a permission-holding object.
    """
    # `target` and `kwargs` are forwarded verbatim to grainy's check(), which
    # accepts an open-ended set of permission targets (namespace str, model
    # instance, viewset, dict, ...) and options — genuinely unconstrained.
    perm_obj = get_permission_holder_from_request(request)
    return check_permissions(perm_obj, target, flag, **kwargs)


def check_permissions(obj: Any, target: Any, permissions: int, **kwargs: Any) -> bool:
    """Use the provided permission holding object to initialize
    the Permissions Util, which then checks permissions.
    """
    # `obj` stays Any: a dynamic `_permissions_util` attribute is cached on it,
    # which the concrete permission-holder types (User, AnonymousUser, *APIKey)
    # do not declare. `target`/`kwargs` are forwarded to grainy's open-ended
    # check() (see check_permissions_from_request).
    if not hasattr(obj, "_permissions_util"):
        obj._permissions_util = init_permissions_helper(obj)

    allowed = obj._permissions_util.check(target, permissions, **kwargs)
    if not allowed:
        record_reauth_denial(obj, target, permissions, kwargs.get("explicit", False))
    return allowed


def record_reauth_denial(
    obj: Any, target: Any, permissions: int | str, explicit: bool
) -> None:
    """
    If a grant stripped for periodic re-authentication would have passed a
    failed check, note the organization on the permission holder, so the
    denial can say why.
    """
    # `obj` and `target` stay Any, see check_permissions

    perms = obj._permissions_util
    if not getattr(perms, "reauth_stripped", None):
        return

    # the live set is final once the helper is initialized, so each restored
    # set is built once. A single update() indexes once, where the dict
    # constructor re-indexes after every namespace

    if not hasattr(perms, "reauth_restored"):
        live = {ns: perm.value for ns, perm in perms.pset.permissions.items()}
        perms.reauth_restored = []
        for org, stripped in perms.reauth_stripped:
            restored = PermissionSet()
            restored.update({**live, **stripped})
            perms.reauth_restored.append((org, restored))

    for org, restored in perms.reauth_restored:
        if restored.check(
            grainy_namespace(target), int_flags(permissions), explicit=explicit
        ):
            if not hasattr(obj, "reauth_denied_orgs"):
                obj.reauth_denied_orgs = {}
            obj.reauth_denied_orgs[org.id] = org


class ReadOnlyPermissions(Permissions):
    """
    Permissions that read whatever the holder reads, and refuse every check
    that asks for more than read.

    Rewriting the permission set to read is not enough for a superuser:
    grainy's `grant_all` passes their checks without consulting it.
    """

    def check(
        self,
        target: Any,
        permissions: int | str,
        explicit: bool = False,
        ignore_grant_all: bool = False,
    ) -> bool:
        # `target` stays Any: forwarded to grainy's open-ended check()
        if int_flags(permissions) & ~grainy_constant.PERM_READ:
            return False
        return super().check(
            target, permissions, explicit=explicit, ignore_grant_all=ignore_grant_all
        )


def init_permissions_helper(obj: Any) -> Permissions:
    """Initialize the Permission Util based on
    whether the provided object is a UserAPIKey, OrgAPIKey,
    or a different object.
    """
    # `obj` stays Any: a dynamic `_permissions_util` attribute is cached on it,
    # which the concrete permission-holder types do not declare.

    if hasattr(obj, "_permissions_util"):
        return obj._permissions_util

    if isinstance(obj, UserAPIKey):
        perms = return_user_api_key_perms(obj)
    elif isinstance(obj, OrganizationAPIKey):
        perms = return_org_api_key_perms(obj)
    else:
        perms = Permissions(obj)
        if isinstance(obj, User):
            adjust_permissions_for_periodic_reauth(obj, perms)

    obj._permissions_util = perms
    return perms


def adjust_permissions_for_periodic_reauth(user: User, perms: Permissions) -> None:
    """
    Strip the user's permissions for every organization that currently
    flags the user as needing re-authentication.
    """

    for org in user.organizations:
        org.adjust_permissions_for_periodic_reauth(user, perms)


def reauth_denial_message(holder: Any, org: Organization | None = None) -> str | None:
    """
    Return an error message naming the organizations whose re-authentication
    requirement caused a failed permission check of the holder in this
    request, or None. Pass `org` to only report that organization.
    """
    # `holder` stays Any: any permission holder, read through getattr

    denied = getattr(holder, "reauth_denied_orgs", None) or {}
    names = sorted(
        denied_org.name
        for denied_org in denied.values()
        if org is None or denied_org.id == org.id
    )
    if not names:
        return None
    return f"Re-authentication required for {', '.join(names)}: confirm your email"


def return_user_api_key_perms(key: UserAPIKey) -> Permissions:
    """
    Initialize the Permissions Util with the
    permissions of the user linked to the User API
    key.

    If the UserAPIKey is marked readonly, it downgrades
    all permissions to readonly.

    For a superuser, grainy's `grant_all` bypasses the permission
    set entirely, so a readonly key of a superuser gets
    ReadOnlyPermissions instead.
    """
    user = key.user

    if key.readonly is True and user.is_superuser:
        return ReadOnlyPermissions(user)

    permissions = Permissions(user)

    # the key acts as its user, so it inherits the user's re-auth restriction

    adjust_permissions_for_periodic_reauth(user, permissions)

    if key.readonly is True:
        readonly_perms = {
            ns: grainy_constant.PERM_READ for ns in permissions.pset.namespaces
        }
        permissions.pset.update(readonly_perms)

        # re-confirming would only give a readonly key read back

        permissions.reauth_stripped = [
            (org, dict.fromkeys(stripped, grainy_constant.PERM_READ))
            for org, stripped in getattr(permissions, "reauth_stripped", [])
        ]

    return permissions


def return_org_api_key_perms(key: OrganizationAPIKey) -> Permissions:
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

    def has_permission(self, request: HttpRequest, view: APIView) -> bool:
        if hasattr(view, "Grainy"):
            perm_obj = get_permission_holder_from_request(request)
            flag = request_method_to_flag(request.method)
            return check_permissions(perm_obj, view, flag)

        # view has not been grainy decorated
        return True

    def has_object_permission(
        self, request: HttpRequest, view: APIView, obj: Model
    ) -> bool:
        perm_obj = get_permission_holder_from_request(request)
        flag = request_method_to_flag(request.method)
        return check_permissions(perm_obj, obj, flag)


class APIPermissionsApplicator(NamespaceKeyApplicator):
    @property
    def is_generating_api_cache(self) -> bool:
        try:
            return getattr(settings, "GENERATING_API_CACHE", False)
        except IndexError:
            return False

    def __init__(self, request: HttpRequest | AnonymousUser) -> None:
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

    def set_peeringdb_handlers(self) -> None:
        self.handler(
            "peeringdb.organization.*.network.*.poc_set.private", explicit=True
        )
        self.handler("peeringdb.organization.*.network.*.poc_set.users", explicit=True)
        self.handler(
            "peeringdb.organization.*.internetexchange.*", fn=self.handle_ixlan
        )

    def handle_ixlan(self, namespace: str, data: dict[str, Any]) -> None:
        # `data` is a serialized entity dict whose values are heterogeneous
        # field values (str, bool, nested dict, ...) — genuinely unconstrained.
        if "ixf_ixp_member_list_url" in data:
            visible = data["ixf_ixp_member_list_url_visible"].lower()
            _namespace = f"{namespace}.ixf_ixp_member_list_url.{visible}"

            perms = self.permissions.check(_namespace, 0x01, explicit=True)
            if not perms:
                del data["ixf_ixp_member_list_url"]

            # Issue #1730: When retrieving only the 'ixf_ixp_member_list_url' field using
            # ?fields=ixf_ixp_member_list_url, an error occurs because this field requires
            # 'ixf_ixp_member_list_url_visible' to also be present.
            #
            # Solution: We added 'ixf_ixp_member_list_url_visible' in the serializer to make
            # the permission check pass. Then we check if only these two specific fields are
            # present in the data (ignoring the "_grainy" key added by the model serializer).
            #
            # If that's the case, we remove 'ixf_ixp_member_list_url_visible' since it wasn't
            # explicitly requested by the user.
            ignored_keys = {"_grainy"}
            remaining_keys = set(data.keys()) - ignored_keys
            # Only check if 'ixf_ixp_member_list_url' and 'ixf_ixp_member_list_url_visible' present
            if remaining_keys == {
                "ixf_ixp_member_list_url",
                "ixf_ixp_member_list_url_visible",
            }:
                del data["ixf_ixp_member_list_url_visible"]
