"""
Views for organization api key management.
"""

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect
from grainy.const import PERM_READ

from peeringdb_server.forms import OrgAdminUserPermissionForm, OrganizationAPIKeyForm
from peeringdb_server.models import (
    OrganizationAPIKey,
    OrganizationAPIPermission,
    UserAPIKey,
)
from peeringdb_server.org_admin_views import load_entity_permissions, org_admin_required


def save_key_permissions(org, key, perms):
    """
    Save key permissions for the specified org and key.

    Perms should be a dict of permissioning ids and permission levels.
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
            grainy_perms[f"{org.grainy_namespace}.network.*.poc_set.private"] = (
                permissions
            )
        elif id == "net":
            grainy_perms[f"{org.grainy_namespace}.network"] = permissions
            grainy_perms[f"{org.grainy_namespace}.network.*.poc_set.private"] = (
                permissions
            )
        elif id == "ix":
            grainy_perms[f"{org.grainy_namespace}.internetexchange"] = permissions
        elif id == "fac":
            grainy_perms[f"{org.grainy_namespace}.facility"] = permissions
        elif id.find(".") > -1:
            id = id.split(".")
            if id[0] == "net":
                grainy_perms[f"{org.grainy_namespace}.network.{id[1]}"] = permissions
                grainy_perms[
                    f"{org.grainy_namespace}.network.{id[1]}.poc_set.private"
                ] = permissions
            elif id[0] == "ix":
                grainy_perms[f"{org.grainy_namespace}.internetexchange.{id[1]}"] = (
                    permissions
                )
            elif id[0] == "fac":
                grainy_perms[f"{org.grainy_namespace}.facility.{id[1]}"] = permissions

    # save
    for ns, p in list(grainy_perms.items()):
        OrganizationAPIPermission.objects.create(
            namespace=ns, permission=p, org_api_key=key
        )

    return grainy_perms


def load_all_key_permissions(org):
    """
    Returns dict of all users with all their permissions for
    the given org.
    """

    rv = {}
    for key in org.api_keys.filter(revoked=False):
        kperms, perms = load_entity_permissions(org, key)
        rv[key.prefix] = {
            "prefix": key.prefix,
            "perms": perms,
            "name": key.name,
        }
    return rv


@login_required
@transaction.atomic
@org_admin_required
def manage_key_add(request, **kwargs):
    """
    Create a new Organization API key.

    Requires a name for the key.
    """

    api_key_form = OrganizationAPIKeyForm(request.POST)

    if api_key_form.is_valid():
        name = api_key_form.cleaned_data.get("name")
        org_id = api_key_form.cleaned_data.get("org_id")
        email = api_key_form.cleaned_data.get("email")

        api_key, key = OrganizationAPIKey.objects.create_key(
            org_id=org_id, name=name, email=email
        )

        return JsonResponse(
            {
                "status": "ok",
                "name": api_key.name,
                "email": api_key.email,
                "prefix": api_key.prefix,
                "org_id": api_key.org_id,
                "key": key,
            }
        )

    else:
        return JsonResponse(api_key_form.errors, status=400)


@login_required
@transaction.atomic
@org_admin_required
def manage_key_update(request, **kwargs):
    """
    Updated existing Organization API key.
    """

    prefix = request.POST.get("prefix")
    org = kwargs.get("org")

    api_key_form = OrganizationAPIKeyForm(request.POST)

    if api_key_form.is_valid():
        name = api_key_form.cleaned_data.get("name")
        email = api_key_form.cleaned_data.get("email")

        # attempt to retrieve api for key prefix + org combination

        try:
            api_key = OrganizationAPIKey.objects.get(prefix=prefix, org=org)
        except OrganizationAPIKey.DoesNotExist:
            return JsonResponse({"non_field_errors": [_("Key not found")]}, status=404)

        # update name and email fields of key

        api_key.name = name
        api_key.email = email
        api_key.save()

        return JsonResponse(
            {
                "status": "ok",
                "name": api_key.name,
                "email": api_key.email,
                "prefix": api_key.prefix,
            }
        )

    else:
        return JsonResponse(api_key_form.errors, status=400)


@login_required
@transaction.atomic
@org_admin_required
def manage_key_revoke(request, **kwargs):
    """
    Revoke an existing API key.
    """

    org = kwargs.get("org")
    prefix = request.POST.get("prefix")

    try:
        api_key = OrganizationAPIKey.objects.get(org=org, prefix=prefix)
    except OrganizationAPIKey.DoesNotExist:
        return JsonResponse({"non_field_errors": [_("Key not found")]}, status=404)

    api_key.revoked = True
    api_key.save()

    return JsonResponse(
        {
            "status": "ok",
        }
    )


@login_required
@org_admin_required
def key_permissions(request, **kwargs):
    """
    Returns JsonResponse with list of key permissions for the targeted
    org an entities under it.

    Permisions are returned as a dict of permissioning ids and permission
    levels.

    Permissioning ids serve as a wrapper for actual permissioning namespaces
    so they can be exposed to the organization admins for changes without allowing
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
@transaction.atomic
@org_admin_required
def key_permission_update(request, **kwargs):
    """
    Update/Add a user's permission.

    perms = permission level
    entity = permission id
    """

    org = kwargs.get("org")
    prefix = request.POST.get("key_prefix")
    key = OrganizationAPIKey.objects.get(prefix=prefix)
    kperms, perms = load_entity_permissions(org, key)
    form = OrgAdminUserPermissionForm(request.POST)
    if not form.is_valid():
        return JsonResponse(form.errors, status=400)

    level = form.cleaned_data.get("perms")
    entity = form.cleaned_data.get("entity")
    perms[entity] = level
    save_key_permissions(org, key, perms)

    return JsonResponse({"status": "ok"})


@login_required
@csrf_protect
@transaction.atomic
@org_admin_required
def key_permission_remove(request, **kwargs):
    """
    Remove a keys permission.

    entity = permission id
    """

    org = kwargs.get("org")
    prefix = request.POST.get("key_prefix")
    key = OrganizationAPIKey.objects.get(prefix=prefix)

    entity = request.POST.get("entity")
    kperms, perms = load_entity_permissions(org, key)
    if entity in perms:
        del perms[entity]
        save_key_permissions(org, key, perms)

    return JsonResponse({"status": "ok"})


"""
USER API KEY MANAGEMENT
"""


def convert_to_bool(data):
    if data is None:
        return False

    return data.lower() == "true"


@login_required
@transaction.atomic
def add_user_key(request, **kwargs):
    """
    Create a new User API key.

    Requires a name and a readonly boolean.
    """

    user = request.user
    name = request.POST.get("name")
    readonly = convert_to_bool(request.POST.get("readonly"))

    if not name:
        return JsonResponse({"name": [_("This field is required.")]}, status=400)

    api_key, key = UserAPIKey.objects.create_key(
        name=name,
        user=user,
        readonly=readonly,
    )

    return JsonResponse(
        {
            "status": "ok",
            "name": api_key.name,
            "prefix": api_key.prefix,
            "readonly": api_key.readonly,
            "key": key,
        }
    )


@login_required
@transaction.atomic
def remove_user_key(request, **kwargs):
    """
    Revoke user api key.
    """

    user = request.user
    prefix = request.POST.get("prefix")

    try:
        api_key = UserAPIKey.objects.get(user=user, prefix=prefix)
    except UserAPIKey.DoesNotExist:
        return JsonResponse({"non_field_errors": [_("Key not found")]}, status=404)
    api_key.revoked = True
    api_key.save()

    return JsonResponse(
        {
            "status": "ok",
        }
    )
