"""
Views for organization administrative actions
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from django.http import JsonResponse
from django.template import loader
from django.conf import settings
from .forms import OrgAdminUserPermissionForm

from grainy.const import *
from django_grainy.models import UserPermission
from django_namespace_perms.constants import *

from django_handleref.models import HandleRefModel

from django.utils.translation import ugettext_lazy as _
from django.utils.translation import override

from peeringdb_server.util import check_permissions
from peeringdb_server.models import (
    User,
    Organization,
    Network,
    NetworkContact,
    InternetExchange,
    Facility,
    UserOrgAffiliationRequest,
    OrganizationAPIKey,
)



# def save_user_permissions(org, user, perms):
#     """
#     Save user permissions for the specified org and user

#     perms should be a dict of permissioning ids and permission levels
#     """

#     # wipe all the user's perms for the targeted org

#     user.grainy_permissions.filter(namespace__startswith=org.grainy_namespace).delete()

#     # collect permissioning namespaces from the provided permissioning ids

#     grainy_perms = {}

#     for id, permissions in list(perms.items()):

#         if not permissions & PERM_READ:
#             permissions = permissions | PERM_READ

#         if id == "org.%d" % org.id:
#             grainy_perms[org.grainy_namespace] = permissions
#             grainy_perms[
#                 f"{org.grainy_namespace}.network.*.poc_set.private"
#             ] = permissions
#         elif id == "net":
#             grainy_perms[
#                 f"{org.grainy_namespace}.network"
#             ] = permissions
#             grainy_perms[
#                 f"{org.grainy_namespace}.network.*.poc_set.private"
#             ] = permissions
#         elif id == "ix":
#             grainy_perms[
#                 f"{org.grainy_namespace}.internetexchange"
#             ] = permissions
#         elif id == "fac":
#             grainy_perms[
#                 f"{org.grainy_namespace}.facility"
#             ] = permissions
#         elif id.find(".") > -1:
#             id = id.split(".")
#             if id[0] == "net":
#                 grainy_perms[
#                     f"{org.grainy_namespace}.network.{id[1]}"
#                 ] = permissions
#                 grainy_perms[
#                     f"{org.grainy_namespace}.network.{id[1]}.poc_set.private"
#                 ] = permissions
#             elif id[0] == "ix":
#                 grainy_perms[
#                     f"{org.grainy_namespace}.internetexchange.{id[1]}"
#                 ] = permissions
#             elif id[0] == "fac":
#                 grainy_perms[
#                     f"{org.grainy_namespace}.facility.{id[1]}"
#                 ] = permissions

#     # save
#     for ns, p in list(grainy_perms.items()):
#         UserPermission.objects.create(namespace=ns, permission=p, user=user)

#     return grainy_perms


# def load_all_user_permissions(org):
#     """
#     Returns dict of all users with all their permissions for
#     the given org
#     """

#     rv = {}
#     for user in org.usergroup.user_set.all():
#         uperms, perms = load_user_permissions(org, user)
#         rv[user.id] = {
#             "id": user.id,
#             "perms": perms,
#             "name": f"{user.full_name} <{user.email}> {user.username}",
#         }
#     return rv


def load_key_permissions(org, key):
    """
    Returns key permissions for a specified org
    """

    # load all of the key permissions related to this org
    uperms = {
        p.namespace: p.permission
        for p in key.grainy_permissions.filter(namespace__startswith=org.grainy_namespace)
    }

    perms = {}

    extract_permission_id(uperms, perms, org, org)

    # extract user's permissioning ids from grainy_namespaces targeting
    # organization's entities
    for model in [Network, InternetExchange, Facility]:
        extract_permission_id(uperms, perms, model, org)

    # extract user's permissioning ids from grainy_namespaces targeting
    # organization's entities by their id (eg user has perms only
    # to THAT specific network)
    for net in org.net_set_active:
        extract_permission_id(uperms, perms, net, org)

    for net in org.ix_set_active:
        extract_permission_id(uperms, perms, net, org)

    for net in org.fac_set_active:
        extract_permission_id(uperms, perms, net, org)

    return uperms, perms


def permission_ids(org):
    """
    returns a dict of a valid permissioning ids for
    the specified organization
    """

    perms = {
        "org.%d" % org.id: _("Organization and all Entities it owns"),
        "net": _("Any Network"),
        "fac": _("Any Facility"),
        "ix": _("Any Exchange"),
    }

    perms.update(
        {
            "net.%d" % net.id: _("Network - %(net_name)s") % {"net_name": net.name}
            for net in org.net_set_active
        }
    )

    perms.update(
        {
            "ix.%d" % ix.id: _("Exchange - %(ix_name)s") % {"ix_name": ix.name}
            for ix in org.ix_set_active
        }
    )

    perms.update(
        {
            "fac.%d" % fac.id: _("Facility - %(fac_name)s") % {"fac_name": fac.name}
            for fac in org.fac_set_active
        }
    )

    return perms


def extract_permission_id(source, dest, entity, org):
    """
    extract a user's permissioning id for the specified
    entity from source <dict> and store it in dest <dict>

    source should be a dict containing django-namespace-perms
    (namespace, level) items

    dest should be a dict where permission ids are to be
    exracted to

    entity can either be a HandleRef instance or clas

    org needs to be an Organization instance that owns the
    entity
    """

    if isinstance(entity, HandleRefModel):
        # instance
        k = entity.grainy_namespace
        j = "%s.%d" % (entity.ref_tag, entity.id)
    else:
        # class
        j = entity.handleref.tag
        namespace = entity.Grainy.namespace()
        k = f"{org.grainy_namespace}.{namespace}"

    if k in source:
        dest[j] = source[k]


def org_admin_required(fnc):
    """
    Decorator function that ensures that the requesting user
    has administrative rights to the targeted organization

    Also sets "org" in kwargs
    """

    def callback(request, **kwargs):
        org_id = request.POST.get("org_id", request.GET.get("org_id"))

        if not org_id:
            return JsonResponse({}, status=400)

        try:
            org = Organization.objects.get(id=org_id)
            if not check_permissions(request.user, org.grainy_namespace_manage, "u"):
                return JsonResponse({}, status=403)
            kwargs["org"] = org
            return fnc(request, **kwargs)
        except Organization.DoesNotExist:
            return JsonResponse(
                {"non_field_errors": [_("Invalid organization specified")]}, status=400
            )

    return callback


def target_user_validate(fnc):
    """
    Decorator function that ensures that the targeted user
    is a member of the targeted organization

    Should be below org_admin_required

    Also sets "user" in kwargs
    """

    def callback(request, **kwargs):

        user_id = request.POST.get("user_id", request.GET.get("user_id"))
        org = kwargs.get("org")

        if not user_id:
            return JsonResponse({}, status=400)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({}, status=400)

        if not user.is_org_member(org) and not user.is_org_admin(org):
            return JsonResponse({}, status=403)

        kwargs["user"] = user
        return fnc(request, **kwargs)

    return callback


@login_required
@org_admin_required
def keys(request, **kwargs):
    """
    Returns JsonResponse with a list of all keys in the specified org
    """

    org = kwargs.get("org")

    rv = {
        "keys": [
            {
                "prefix": key.prefix,
                "hashed_key": key.hashed_key,
                "name": key.name
            }
            for key in org.api_keys.filter(revoked=False).all()
        ]
    }

    rv.update({"status": "ok"})

    return JsonResponse(rv)


@login_required
@org_admin_required
def manage_key_add(request, **kwargs):
    """
    Create a new API key

    Requires a name for the key.
    """

    org = kwargs.get("org")
    print(request.POST)
    description = request.POST.get("description")

    api_key, key = OrganizationAPIKey.objects.create_key(
        organization=org,
        name=description
    )

    return JsonResponse({
            "status": "ok",
            "key": key,
        }
    )


@login_required
@org_admin_required
def manage_key_revoke(request, **kwargs):
    """
    Revoke an existing API key.
    """

    org = kwargs.get("org")
    prefix = request.POST.get("prefix")

    api_key = OrganizationAPIKey.objects.filter(
        organization__id=org.id,
        prefix=prefix
    ).first()

    api_key.revoked = True
    api_key.save()

    return JsonResponse({
            "status": "ok",
        }
    )


@login_required
@org_admin_required
def key_permissions(request, **kwargs):
    """
    Returns JsonResponse with list of key permissions for the targeted
    org an entities under it

    Permisions are returned as a dict of permissioning ids and permission
    levels.

    Permissioning ids serve as a wrapper for actual permissioning namespaces
    so we can expose them to the organization admins for changes without allowing
    them to set permissioning namespaces directly.
    """

    org = kwargs.get("org")
    perms_rv = {}
    for key in org.api_keys.filter(revoked=False).all():
        uperms, perms = load_key_permissions(org, key)
        perms_rv[key.prefix] = perms

    return JsonResponse({"status": "ok", "key_permissions": perms_rv})


# @login_required
# @csrf_protect
# @org_admin_required
# @target_user_validate
# def key_permission_update(request, **kwargs):
#     """
#     Update/Add a user's permission

#     perms = permission level
#     entity = permission id
#     """

#     org = kwargs.get("org")
#     key = kwargs.get("key")

#     uperms, perms = load_key_permissions(org, key)
#     form = OrgAdminUserPermissionForm(request.POST)
#     if not form.is_valid():
#         return JsonResponse(form.errors, status=400)

#     level = form.cleaned_data.get("perms")
#     entity = form.cleaned_data.get("entity")
#     perms[entity] = level
#     save_user_permissions(org, user, perms)

#     return JsonResponse({"status": "ok"})


# @login_required
# @csrf_protect
# @org_admin_required
# @target_user_validate
# def user_permission_remove(request, **kwargs):
#     """
#     Remove a user's permission

#     entity = permission id
#     """

#     org = kwargs.get("org")
#     user = kwargs.get("user")
#     entity = request.POST.get("entity")
#     uperms, perms = load_user_permissions(org, user)
#     if entity in perms:
#         del perms[entity]
#         save_user_permissions(org, user, perms)

#     return JsonResponse({"status": "ok"})


# @login_required
# @org_admin_required
# def permissions(request, **kwargs):
#     """
#     Returns list of permissioning ids with labels that
#     are valid to be permissioned out to regular org users

#     Permissioning ids serve as a wrapper for actual permissioning namespaces
#     so we can expose them to the organization admins for changes without allowing
#     them to set permissioning namespaces directly.
#     """

#     org = kwargs.get("org")

#     perms = [{"id": id, "name": name} for id, name in list(permission_ids(org).items())]
#     perms = sorted(perms, key=lambda x: x.get("name"))
#     return JsonResponse({"status": "ok", "permissions": perms})

