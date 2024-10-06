"""
View for organization administrative actions (/org endpoint).
"""

from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.template import loader
from django.utils.translation import gettext_lazy as _
from django.utils.translation import override
from django.views.decorators.csrf import csrf_protect
from django_grainy.models import UserPermission
from django_handleref.models import HandleRefModel
from grainy.const import PERM_READ

from peeringdb_server.models import (
    Carrier,
    Facility,
    InternetExchange,
    Network,
    Organization,
    User,
    UserOrgAffiliationRequest,
)
from peeringdb_server.util import check_permissions

from .forms import OrgAdminUserPermissionForm, OrgUserOptions


def save_user_permissions(org, user, perms):
    """
    Save user permissions for the specified org and user.

    Perms should be a dict of permissioning ids and permission levels.
    """

    # wipe all the user's perms for the targeted org

    user.grainy_permissions.filter(namespace__startswith=org.grainy_namespace).delete()

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
        elif id == "carrier":
            grainy_perms[f"{org.grainy_namespace}.carrier"] = permissions
        elif id == "sessions":
            grainy_perms[f"{org.grainy_namespace}.network.*.sessions"] = permissions
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
            elif id[0] == "sessions":
                grainy_perms[f"{org.grainy_namespace}.network.{id[1]}.sessions"] = (
                    permissions
                )

    # save
    for ns, p in list(grainy_perms.items()):
        UserPermission.objects.create(namespace=ns, permission=p, user=user)

    return grainy_perms


def load_all_user_permissions(org):
    """
    Return dict of all users with all their permissions for
    the given org.
    """

    rv = {}
    for user in org.usergroup.user_set.all():
        uperms, perms = load_entity_permissions(org, user)
        rv[user.id] = {
            "id": user.id,
            "perms": perms,
            "name": f"{user.full_name} <{user.email}> {user.username}",
        }
    return rv


def load_user_permissions(org, user):
    return load_entity_permissions(org, user)


def load_entity_permissions(org, entity):
    """
    Return entity's permissions for the specified org.
    """

    # load all of the entity's permissions related to this org
    entity_perms = {
        p.namespace: p.permission
        for p in entity.grainy_permissions.filter(
            namespace__startswith=org.grainy_namespace
        )
    }

    perms = {}

    extract_permission_id(entity_perms, perms, org, org)
    # extract session for any network
    extract_permission_id(entity_perms, perms, "sessions", org)

    # extract entity's permissioning ids from grainy_namespaces targeting
    # organization's entities
    for model in [Network, InternetExchange, Facility, Carrier]:
        extract_permission_id(entity_perms, perms, model, org)

    # extract entity's permissioning ids from grainy_namespaces targeting
    # organization's entities by their id (eg entity has perms only
    # to THAT specific network)
    for net in org.net_set_active:
        extract_permission_id(entity_perms, perms, net, org)
        # extract session per network
        extract_permission_id(entity_perms, perms, net, org, True)

    for ix in org.ix_set_active:
        extract_permission_id(entity_perms, perms, ix, org)

    for fac in org.fac_set_active:
        extract_permission_id(entity_perms, perms, fac, org)

    for carrier in org.carrier_set_active:
        extract_permission_id(entity_perms, perms, carrier, org)
    return entity_perms, perms


def permission_ids(org):
    """
    Return a dict of a valid permissioning ids for
    the specified organization.
    """

    perms = {
        "org.%d" % org.id: _("Organization and all Entities it owns"),
        "net": _("Any Network"),
        "fac": _("Any Facility"),
        "ix": _("Any Exchange"),
        "carrier": _("Any Carrier"),
        "sessions": _("Manage peering sessions - Any Network"),
    }

    perms.update(
        {
            "sessions.%d" % net.id: _("Manage peering sessions - %(net_name)s")
            % {"net_name": net.name}
            for net in org.net_set_active
        }
    )

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

    perms.update(
        {
            "carrier.%d" % carrier.id: _("Carrier - %(carrier_name)s")
            % {"carrier_name": carrier.name}
            for carrier in org.carrier_set_active
        }
    )

    return perms


def extract_permission_id(source, dest, entity, org, is_session=False):
    """
    Extract a user's permissioning id for the specified
    entity from source <dict> and store it in dest <dict>.

    Source should be a dict containing django-namespace-perms
    (namespace, level) items.

    Dest should be a dict where permission ids are to be
    exracted to.

    Entity can either be a HandleRef instance or class or str.

    Org must be an Organization instance that owns the
    entity.

    is_session to handle the peering sessions permission
    """

    if isinstance(entity, HandleRefModel):
        if not is_session:
            # instance
            k = entity.grainy_namespace
            j = "%s.%d" % (entity.ref_tag, entity.id)
        else:
            j = "sessions.%d" % (entity.id)
            k = f"{entity.grainy_namespace}.sessions"
    elif entity == "sessions":
        j = "sessions"
        k = f"{org.grainy_namespace}.network.*.sessions"
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
    has administrative rights to the targeted organization.

    Also sets "org" in kwargs.
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
    is a member of the targeted organization.

    Should be below org_admin_required.

    Also sets "user" in kwargs.
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
def users(request, **kwargs):
    """
    Returns JsonResponse with a list of all users in the specified org.
    """

    org = kwargs.get("org")

    rv = {
        "users": [
            {
                "id": user.id,
                "name": f"{user.full_name} <{user.email}, {user.username}>",
            }
            for user in org.usergroup.user_set.all()
        ]
    }

    rv.update({"status": "ok"})

    return JsonResponse(rv)


@login_required
@org_admin_required
def update_user_options(request, **kwargs):
    org = kwargs.get("org")

    form = OrgUserOptions(request.POST, instance=org)

    if not form.is_valid():
        return JsonResponse(form.errors, status=400)

    form.save()

    return JsonResponse({"status": "ok"})


@login_required
@transaction.atomic
@org_admin_required
@target_user_validate
def manage_user_delete(request, **kwargs):
    """
    Remove user from org.
    """

    org = kwargs.get("org")
    user = kwargs.get("user")
    save_user_permissions(org, user, {})
    org.usergroup.user_set.remove(user)
    org.admin_usergroup.user_set.remove(user)

    return JsonResponse({"status": "ok"})


@login_required
@transaction.atomic
@org_admin_required
@target_user_validate
def manage_user_update(request, **kwargs):
    """
    Udpate a user in the org.

    Currently, this only allows moving the user to either
    admin or member group.
    """

    org = kwargs.get("org")
    user = kwargs.get("user")
    group = request.POST.get("group")
    if group not in ["member", "admin"]:
        return JsonResponse({"group": _("Needs to be member or admin")}, status=400)

    if group == "admin":
        org.usergroup.user_set.remove(user)
        org.admin_usergroup.user_set.add(user)
        # remove granular permissions user has to the org
        # since user is now an organization admin (#1157)
        user.grainy_permissions.filter(
            namespace__startswith=f"peeringdb.organization.{org.id}."
        ).delete()
    elif group == "member":
        org.usergroup.user_set.add(user)
        org.admin_usergroup.user_set.remove(user)

    return JsonResponse({"status": "ok"})


@login_required
@org_admin_required
def user_permissions(request, **kwargs):
    """
    Return JsonRespone with list of user's permissions for the targeted
    org an entities under it.

    Permisions are returned as a dict of permissioning ids and permission
    levels.

    Permissioning ids serve as a wrapper for actual permissioning namespaces
    so they can be exposed to the organization admins for changes without allowing
    them to set permissioning namespaces directly.
    """

    org = kwargs.get("org")
    perms_rv = {}
    for user in org.usergroup.user_set.all():
        uperms, perms = load_user_permissions(org, user)
        perms_rv[user.id] = perms

    return JsonResponse({"status": "ok", "user_permissions": perms_rv})


@login_required
@csrf_protect
@transaction.atomic
@org_admin_required
@target_user_validate
def user_permission_update(request, **kwargs):
    """
    Update/Add a user's permission.

    perms = permission level
    entity = permission id
    """

    org = kwargs.get("org")
    user = kwargs.get("user")

    # cannot manage permissions for organization admins (#1157)
    if user.is_org_admin(org):
        return JsonResponse(
            {
                "non_field_errors": [
                    _("Cannot manage permissions for organization admins")
                ]
            },
            status=400,
        )

    uperms, perms = load_user_permissions(org, user)
    form = OrgAdminUserPermissionForm(request.POST)
    if not form.is_valid():
        return JsonResponse(form.errors, status=400)

    level = form.cleaned_data.get("perms")
    entity = form.cleaned_data.get("entity")
    perms[entity] = level
    save_user_permissions(org, user, perms)

    return JsonResponse({"status": "ok"})


@login_required
@csrf_protect
@transaction.atomic
@org_admin_required
@target_user_validate
def user_permission_remove(request, **kwargs):
    """
    Remove a user's permission.

    entity = permission id
    """

    org = kwargs.get("org")
    user = kwargs.get("user")
    entity = request.POST.get("entity")
    uperms, perms = load_user_permissions(org, user)
    if entity in perms:
        del perms[entity]
        save_user_permissions(org, user, perms)

    return JsonResponse({"status": "ok"})


@login_required
@org_admin_required
def permissions(request, **kwargs):
    """
    Return list of permissioning ids with labels that
    are valid to be permissioned out to regular org users.

    Permissioning ids serve as a wrapper for actual permissioning namespaces
    so they can be exposed to the organization admins for changes without allowing
    them to set permissioning namespaces directly.
    """

    org = kwargs.get("org")

    perms = [{"id": id, "name": name} for id, name in list(permission_ids(org).items())]
    perms = sorted(perms, key=lambda x: x.get("name"))
    return JsonResponse({"status": "ok", "permissions": perms})


@login_required
@csrf_protect
@transaction.atomic
@org_admin_required
def uoar_approve(request, **kwargs):
    """
    Approve a user request to affiliate with the organization.
    """

    org = kwargs.get("org")

    if request.user.is_staff:
        req_user = "PeeringDB Support"
    else:
        req_user = request.user.full_name

    try:
        uoar = UserOrgAffiliationRequest.objects.get(id=request.POST.get("id"))
        if uoar.org != org:
            return JsonResponse({}, status=403)

        try:
            user = uoar.user
        except User.DoesNotExist:
            uoar.delete()
            return JsonResponse({"status": "ok"})

        if org.require_2fa:
            if not uoar.user.has_2fa:
                message = (
                    f"User {uoar.user.full_name} requests affiliation with Organization {uoar.org.name} "
                    f"but has not enabled 2FA. Org {uoar.org.name} does not allow users to affiliate "
                    f"unless they have enabled 2FA on their account. You will be able to approve an "
                    f"affiliation request from User {uoar.user.full_name}, and assign permissions to "
                    f"them, when they have enabled 2FA."
                )
                return JsonResponse({"message": message}, status=403)

        uoar.approve()

        # notify rest of org admins that the affiliation request has been
        # approved

        for admin_user in org.admin_usergroup.user_set.all():
            if admin_user != request.user:
                with override(admin_user.locale):
                    admin_user.email_user(
                        _("%(user_name)s's affiliation request has been approved")
                        % {"user_name": uoar.user.full_name},
                        loader.get_template(
                            "email/notify-org-admin-user-affil-approved.txt"
                        ).render(
                            {
                                "user": req_user,
                                "uoar": uoar,
                                "org_management_url": urljoin(
                                    settings.BASE_URL, f"/org/{org.id}#users"
                                ),
                            }
                        ),
                    )

        return JsonResponse(
            {
                "status": "ok",
                "full_name": user.full_name,
                "id": user.id,
                "email": user.email,
            }
        )

    except UserOrgAffiliationRequest.DoesNotExist:
        return JsonResponse({"status": "ok"})


@login_required
@csrf_protect
@transaction.atomic
@org_admin_required
def uoar_deny(request, **kwargs):
    """
    Deny a user request to affiliate with the organization.
    """
    org = kwargs.get("org")

    if request.user.is_staff:
        req_user = "PeeringDB Support"
    else:
        req_user = request.user.full_name

    try:
        uoar = UserOrgAffiliationRequest.objects.get(id=request.POST.get("id"))

        if uoar.org != org:
            return JsonResponse({}, status=403)
        try:
            uoar.user
            uoar.deny()

        except User.DoesNotExist:
            uoar.delete()
            return JsonResponse({"status": "ok"})

        # notify rest of org admins that the affiliation request has been
        # denied

        for user in org.admin_usergroup.user_set.all():
            if user != request.user:
                with override(user.locale):
                    user.email_user(
                        _("%(user_name)s's affiliation request has been denied")
                        % {"user_name": uoar.user.full_name},
                        loader.get_template(
                            "email/notify-org-admin-user-affil-denied.txt"
                        ).render(
                            {
                                "user": req_user,
                                "uoar": uoar,
                                "org_management_url": urljoin(
                                    settings.BASE_URL, f"/org/{org.id}#users"
                                ),
                            }
                        ),
                    )

    except UserOrgAffiliationRequest.DoesNotExist:
        return JsonResponse({"status": "ok"})

    return JsonResponse({"status": "ok"})
