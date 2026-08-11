"""
Views for organization api key management.
"""

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect
from grainy.const import PERM_READ

from peeringdb_server.forms import (
    OrgAdminUserPermissionForm,
    OrganizationAPIKeyForm,
    UserAPIKeyPermissionForm,
)
from peeringdb_server.models import (
    Carrier,
    Facility,
    InternetExchange,
    Network,
    Organization,
    OrganizationAPIKey,
    OrganizationAPIPermission,
    UserAPIKey,
    UserAPIPermission,
)
from peeringdb_server.org_admin_views import load_entity_permissions, org_admin_required
from peeringdb_server.permissions import check_permissions

# reftag -> model, for resolving user-key scoping ids ("net.5", "ix.3", ...)
# to an actual object. Deliberately excludes "org" (org.<id> is a whole
# organization and handled separately below) since org is not a HandleRef
# model in the same registry.
USER_KEY_REF_TAG_MODELS = {
    "net": Network,
    "ix": InternetExchange,
    "fac": Facility,
    "carrier": Carrier,
}

# reverse of the above, keyed by the grainy namespace segment name each
# model registers under (see the `@grainy_model(namespace=...)` decorators
# in models.py) rather than the shorter ref_tag, since that's what shows
# up in a saved namespace string.
NAMESPACE_SEGMENT_TO_REF_TAG = {
    "network": "net",
    "internetexchange": "ix",
    "facility": "fac",
    "carrier": "carrier",
}


def resolve_user_key_permission_id(user, permission_id):
    """
    Resolve a user-key scoping id ("org.<id>" or "<reftag>.<id>") to
    a grainy namespace, after confirming `user` already has read
    access to that namespace on their own account.

    Scoping can only ever narrow what a key can see - it is never a
    grant - so if the user themselves can't read the target object,
    there is nothing valid to scope the key to and this fails.

    Returns a (namespace, error) tuple - exactly one of which will
    be None.

    Note: unlike organization API key scoping, this does not support
    bare type-level ids ("net" meaning "any network"), since without
    an owning org to anchor it that would mean "every network in the
    entire database" rather than "every network belonging to this
    org" - a materially different and much broader grant. Only
    single objects or whole organizations can be targeted.
    """

    try:
        reftag, raw_id = permission_id.split(".", 1)
        obj_id = int(raw_id)
    except (ValueError, AttributeError):
        return None, _("Invalid permission id")

    if reftag == "org":
        try:
            obj = Organization.objects.get(id=obj_id)
        except Organization.DoesNotExist:
            return None, _("Organization not found")
    elif reftag in USER_KEY_REF_TAG_MODELS:
        model = USER_KEY_REF_TAG_MODELS[reftag]
        try:
            obj = model.objects.get(id=obj_id)
        except model.DoesNotExist:
            return None, _("Object not found")
    else:
        return None, _("Unsupported permission id")

    namespace = obj.grainy_namespace

    if not check_permissions(user, namespace, PERM_READ, explicit=False):
        return None, _("You do not have access to this object")

    return namespace, None


def save_user_key_permissions(user, key, entity_ids):
    """
    Replace the scoping on a UserAPIKey.

    `entity_ids` is a list of permissioning ids (e.g. ["net.5",
    "org.3"]). Each is resolved and validated via
    `resolve_user_key_permission_id` before being saved - invalid or
    inaccessible ids are collected and returned as errors rather than
    silently dropped, so the caller can surface them.

    User key scoping is always read-only: this is a "read scoped API
    key" feature, not a mechanism for granting write access, so the
    permission level is hardcoded to PERM_READ regardless of what
    the user might otherwise be able to do to the target object.

    Returns (namespaces_saved, errors).
    """

    namespaces = []
    errors = {}

    for entity_id in entity_ids:
        namespace, error = resolve_user_key_permission_id(user, entity_id)
        if error:
            errors[entity_id] = error
        else:
            namespaces.append(namespace)

    if errors:
        return [], errors

    # full replace - wipe any existing scoping and re-apply
    key.grainy_permissions.all().delete()

    for namespace in namespaces:
        UserAPIPermission.objects.create(
            namespace=namespace, permission=PERM_READ, api_key=key
        )

    return namespaces, {}


def load_user_key_permissions(key):
    """
    Return a dict of {permission_id: permission_level} for a
    UserAPIKey's current scoping, in the same "<reftag>.<id>" /
    "org.<id>" id format `save_user_key_permissions` accepts - the
    inverse operation, for populating the account settings UI.

    Namespaces that don't cleanly map back to a known object type are
    skipped rather than raised, since they shouldn't occur through
    normal use of this feature but a stale/manually-inserted row
    shouldn't break the whole listing.
    """

    perms = {}

    for perm in key.grainy_permissions.all():
        parts = perm.namespace.split(".")

        # "peeringdb.organization.<id>" - whole org
        if len(parts) == 3 and parts[:2] == ["peeringdb", "organization"]:
            perms[f"org.{parts[2]}"] = perm.permission
            continue

        # "peeringdb.organization.<org_id>.<segment>.<id>" - single object
        if len(parts) >= 5 and parts[:2] == ["peeringdb", "organization"]:
            segment, obj_id = parts[3], parts[4]
            reftag = NAMESPACE_SEGMENT_TO_REF_TAG.get(segment)
            if reftag:
                perms[f"{reftag}.{obj_id}"] = perm.permission

    return perms


def load_all_user_key_permissions(user):
    """
    Returns a dict of all of `user`'s non-revoked API keys with
    their current scoping, keyed by prefix - the per-user analogue
    of `load_all_key_permissions(org)`, used to populate the account
    settings page without one AJAX round trip per key.
    """

    rv = {}
    for key in user.api_keys.filter(revoked=False):
        rv[key.prefix] = {
            "prefix": key.prefix,
            "name": key.name,
            "is_readonly": key.readonly,
            "is_scoped": key.is_scoped,
            "perms": load_user_key_permissions(key),
        }
    return rv


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

        if id == f"org.{org.id}":
            grainy_perms[org.grainy_namespace] = permissions
            grainy_perms[f"{org.grainy_namespace}.network.*.poc_set.private"] = (
                permissions
            )
        elif id == f"org.{org.id}.users":
            grainy_perms[f"{org.grainy_namespace}.users"] = permissions
        elif id == "net":
            grainy_perms[f"{org.grainy_namespace}.network"] = permissions
            grainy_perms[f"{org.grainy_namespace}.network.*.poc_set.private"] = (
                permissions
            )
        elif id == "ix":
            grainy_perms[f"{org.grainy_namespace}.internetexchange"] = permissions
        elif id == "fac":
            grainy_perms[f"{org.grainy_namespace}.facility"] = permissions
        elif id == "carrier":
            grainy_perms[f"{org.grainy_namespace}.carrier"] = permissions
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
            elif id[0] == "carrier":
                grainy_perms[f"{org.grainy_namespace}.carrier.{id[1]}"] = permissions

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
            "is_readonly": key.is_readonly,
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
                "is_readonly": api_key.is_readonly,
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

    return JsonResponse({"status": "ok", "is_readonly": key.is_readonly})


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

    return JsonResponse({"status": "ok", "is_readonly": key.is_readonly})


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


@login_required
def user_key_permissions(request, **kwargs):
    """
    Returns the current scoping for one of the requesting user's own
    API keys.

    Only ever operates on keys owned by request.user - there is no
    org-admin equivalent here since these are personal keys.
    """

    prefix = request.GET.get("prefix")

    try:
        key = UserAPIKey.objects.get(user=request.user, prefix=prefix)
    except UserAPIKey.DoesNotExist:
        return JsonResponse({"non_field_errors": [_("Key not found")]}, status=404)

    return JsonResponse(
        {
            "status": "ok",
            "is_scoped": key.is_scoped,
            "permissions": load_user_key_permissions(key),
        }
    )


@login_required
@csrf_protect
@transaction.atomic
def user_key_permission_update(request, **kwargs):
    """
    Add a scoping entry to one of the requesting user's own API keys.

    entity = permission id (e.g. "net.5", "org.3")

    Scoping is additive from the caller's perspective (add this one
    entity to the key's scope) but implemented as a full replace
    under the hood via `save_user_key_permissions`, since a key's
    scope has to be recomputed as a whole to stay consistent - the
    existing entries are read back out with `load_user_key_permissions`
    first so this call doesn't clobber them.
    """

    prefix = request.POST.get("key_prefix")

    try:
        key = UserAPIKey.objects.get(user=request.user, prefix=prefix)
    except UserAPIKey.DoesNotExist:
        return JsonResponse({"non_field_errors": [_("Key not found")]}, status=404)

    form = UserAPIKeyPermissionForm(request.POST)
    if not form.is_valid():
        return JsonResponse(form.errors, status=400)

    entity = form.cleaned_data.get("entity")
    entity_ids = list(load_user_key_permissions(key).keys())
    if entity not in entity_ids:
        entity_ids.append(entity)

    namespaces, errors = save_user_key_permissions(request.user, key, entity_ids)

    if errors:
        return JsonResponse({"non_field_errors": list(errors.values())}, status=400)

    return JsonResponse(
        {
            "status": "ok",
            "is_scoped": key.is_scoped,
            "permissions": load_user_key_permissions(key),
        }
    )


@login_required
@csrf_protect
@transaction.atomic
def user_key_permission_remove(request, **kwargs):
    """
    Remove a scoping entry from one of the requesting user's own API
    keys.

    entity = permission id

    Removing the last remaining scoping entry restores the key to
    its unscoped state (full inherited user permissions, or
    read-only-everything if `readonly` is also set) - it does not
    leave the key able to see nothing, since an empty
    `grainy_permissions` set is exactly what `return_user_api_key_perms`
    treats as "not scoped".
    """

    prefix = request.POST.get("key_prefix")
    entity = request.POST.get("entity")

    try:
        key = UserAPIKey.objects.get(user=request.user, prefix=prefix)
    except UserAPIKey.DoesNotExist:
        return JsonResponse({"non_field_errors": [_("Key not found")]}, status=404)

    entity_ids = list(load_user_key_permissions(key).keys())
    if entity in entity_ids:
        entity_ids.remove(entity)
        namespaces, errors = save_user_key_permissions(request.user, key, entity_ids)
        if errors:
            return JsonResponse(
                {"non_field_errors": list(errors.values())}, status=400
            )

    return JsonResponse(
        {
            "status": "ok",
            "is_scoped": key.is_scoped,
            "permissions": load_user_key_permissions(key),
        }
    )
