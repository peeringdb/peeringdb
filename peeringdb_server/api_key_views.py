"""
Views for organization administrative actions
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from django.http import JsonResponse
from django.template import loader
from django.conf import settings
from .forms import OrgAdminUserPermissionForm

from grainy.const import PERM_READ
from django_grainy.models import UserPermission

from django_handleref.models import HandleRefModel

from django.utils.translation import ugettext_lazy as _
from django.utils.translation import override

from peeringdb_server.org_admin_views import (
    load_entity_permissions,
    org_admin_required,
)


from peeringdb_server.models import (
    OrganizationAPIKey,
    OrganizationAPIPermission,
)


def save_key_permissions(org, key, perms):
    """
    Save key permissions for the specified org and key

    perms should be a dict of permissioning ids and permission levels
    """

    # wipe all the key's perms for the targeted org

    key.grainy_permissions.filter(namespace__startswith=org.grainy_namespace).delete()

    # collect permissioning namespaces from the provided permissioning ids

    grainy_perms = {}

    for id, permissions in list(perms.items()):

        if not permissions & PERM_READ:
            permissions = permissions | PERM_READ

        if id == "org.%d" % org.id:
            grainy_perms[org.grainy_namespace] = permissions
            grainy_perms[
                f"{org.grainy_namespace}.network.*.poc_set.private"
            ] = permissions
        elif id == "net":
            grainy_perms[
                f"{org.grainy_namespace}.network"
            ] = permissions
            grainy_perms[
                f"{org.grainy_namespace}.network.*.poc_set.private"
            ] = permissions
        elif id == "ix":
            grainy_perms[
                f"{org.grainy_namespace}.internetexchange"
            ] = permissions
        elif id == "fac":
            grainy_perms[
                f"{org.grainy_namespace}.facility"
            ] = permissions
        elif id.find(".") > -1:
            id = id.split(".")
            if id[0] == "net":
                grainy_perms[
                    f"{org.grainy_namespace}.network.{id[1]}"
                ] = permissions
                grainy_perms[
                    f"{org.grainy_namespace}.network.{id[1]}.poc_set.private"
                ] = permissions
            elif id[0] == "ix":
                grainy_perms[
                    f"{org.grainy_namespace}.internetexchange.{id[1]}"
                ] = permissions
            elif id[0] == "fac":
                grainy_perms[
                    f"{org.grainy_namespace}.facility.{id[1]}"
                ] = permissions

    # save
    for ns, p in list(grainy_perms.items()):
        OrganizationAPIPermission.objects.create(
            namespace=ns, permission=p, org_api_key=key)

    return grainy_perms


def load_all_key_permissions(org):
    """
    Returns dict of all users with all their permissions for
    the given org
    """

    rv = {}
    for key in org.api_keys.all():
        kperms, perms = load_entity_permissions(org, key)
        rv[key.prefix] = {
            "prefix": key.prefix,
            "perms": perms,
            "description": key.name,
        }
    return rv


# @login_required
# @org_admin_required
# def keys(request, **kwargs):
#     """
#     Returns JsonResponse with a list of all keys in the specified org
#     """

#     org = kwargs.get("org")

#     rv = {
#         "keys": [
#             {
#                 "prefix": key.prefix,
#                 "hashed_key": key.hashed_key,
#                 "name": key.name
#             }
#             for key in org.api_keys.filter(revoked=False).all()
#         ]
#     }

#     rv.update({"status": "ok"})

#     return JsonResponse(rv)


@login_required
@org_admin_required
def manage_key_add(request, **kwargs):
    """
    Create a new API key

    Requires a name for the key.
    """

    org = kwargs.get("org")
    description = request.POST.get("description")

    api_key, key = OrganizationAPIKey.objects.create_key(
        org=org,
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
        org__id=org.id,
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
        kperms, perms = load_entity_permissions(org, key)
        perms_rv[key.prefix] = perms

    return JsonResponse({"status": "ok", "key_permissions": perms_rv})


@login_required
@csrf_protect
@org_admin_required
def key_permission_update(request, **kwargs):
    """
    Update/Add a user's permission

    perms = permission level
    entity = permission id
    """

    org = kwargs.get("org")
    prefix = request.POST.get("key_prefix")
    key = OrganizationAPIKey.objects.get(prefix=prefix)
    print(key)
    kperms, perms = load_entity_permissions(org, key)
    form = OrgAdminUserPermissionForm(request.POST)
    if not form.is_valid():
        return JsonResponse(form.errors, status=400)

    level = form.cleaned_data.get("perms")
    entity = form.cleaned_data.get("entity")
    perms[entity] = level
    save_key_permissions(org, key, perms)

    return JsonResponse({"status": "ok"})


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
#     key = kwargs.get("key")
#     entity = request.POST.get("entity")
#     uperms, perms = load_user_permissions(org, user)
#     if entity in perms:
#         del perms[entity]
#         save_user_permissions(org, user, perms)

#     return JsonResponse({"status": "ok"})


