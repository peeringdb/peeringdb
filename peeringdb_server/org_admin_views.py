"""
Views for organization administrative actions
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from django.http import JsonResponse
from django.template import loader
from django.conf import settings
from forms import OrgAdminUserPermissionForm

from peeringdb_server.models import (
    User, Organization, Network, NetworkContact, InternetExchange, Facility,
    UserOrgAffiliationRequest)

import django_namespace_perms.util as nsp
from django_namespace_perms.constants import *
from django_namespace_perms.models import UserPermission

from django_handleref.models import HandleRefModel

from django.utils.translation import ugettext_lazy as _
from django.utils.translation import override


def save_user_permissions(org, user, perms):
    """
    Save user permissions for the specified org and user

    perms should be a dict of permissioning ids and permission levels
    """

    # wipe all the user's perms for the targeted org

    user.userpermission_set.filter(
        namespace__startswith=org.nsp_namespace).delete()

    # collect permissioning namespaces from the provided permissioning ids

    nsp_perms = {}

    for id, permissions in perms.items():

        if not permissions & PERM_READ:
            permissions = permissions | PERM_READ

        if id == "org.%d" % org.id:
            nsp_perms[org.nsp_namespace] = permissions
            nsp_perms[NetworkContact.nsp_namespace_from_id(
                org.id, "*", "private")] = permissions
        elif id == "net":
            nsp_perms[Network.nsp_namespace_from_id(
                org.id, "*").strip(".*")] = permissions
            nsp_perms[NetworkContact.nsp_namespace_from_id(
                org.id, "*", "private")] = permissions
        elif id == "ix":
            nsp_perms[InternetExchange.nsp_namespace_from_id(
                org.id, "*").strip(".*")] = permissions
        elif id == "fac":
            nsp_perms[Facility.nsp_namespace_from_id(
                org.id, "*").strip(".*")] = permissions
        elif id.find(".") > -1:
            id = id.split(".")
            if id[0] == "net":
                nsp_perms[Network.nsp_namespace_from_id(org.id,
                                                        id[1])] = permissions
                nsp_perms[NetworkContact.nsp_namespace_from_id(
                    org.id, id[1], "private")] = permissions
            elif id[0] == "ix":
                nsp_perms[InternetExchange.nsp_namespace_from_id(
                    org.id, id[1])] = permissions
            elif id[0] == "fac":
                nsp_perms[Facility.nsp_namespace_from_id(org.id,
                                                         id[1])] = permissions

    # save
    for ns, p in nsp_perms.items():
        UserPermission.objects.create(namespace=ns, permissions=p, user=user)

    return nsp_perms


def load_all_user_permissions(org):
    """
    Returns dict of all users with all their permissions for
    the given org
    """

    rv = {}
    for user in org.usergroup.user_set.all():
        uperms, perms = load_user_permissions(org, user)
        rv[user.id] = {
            "id": user.id,
            "perms": perms,
            "name": "%s <%s> %s" % (user.full_name, user.email, user.username)
        }
    return rv


def load_user_permissions(org, user):
    """
    Returns user's permissions for the specified org
    """

    # load all of the user's permissions related to this org
    uperms = dict([(p.namespace, p.permissions)
                   for p in user.userpermission_set.filter(
                       namespace__startswith=org.nsp_namespace)])

    perms = {}

    extract_permission_id(uperms, perms, org, org)

    # extract user's permissioning ids from nsp_namespaces targeting
    # organization's entities
    for model in [Network, InternetExchange, Facility]:
        extract_permission_id(uperms, perms, model, org)

    # extract user's permissioning ids from nsp_namespaces targeting
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
        "ix": _("Any Exchange")
    }

    perms.update(
        dict([("net.%d" % net.id, _("Network - %(net_name)s") % {
            'net_name': net.name
        }) for net in org.net_set_active]))

    perms.update(
        dict([("ix.%d" % ix.id, _("Exchange - %(ix_name)s") % {
            'ix_name': ix.name
        }) for ix in org.ix_set_active]))

    perms.update(
        dict([("fac.%d" % fac.id, _("Facility - %(fac_name)s") % {
            'fac_name': fac.name
        }) for fac in org.fac_set_active]))

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
        k = entity.nsp_namespace
        j = "%s.%d" % (entity.ref_tag, entity.id)
    else:
        # class
        k = entity.nsp_namespace_from_id(org.id, "*").strip(".*")
        j = entity.handleref.tag
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
            if not nsp.has_perms(request.user, org.nsp_namespace_manage,
                                 "update"):
                return JsonResponse({}, status=403)
            kwargs["org"] = org
            return fnc(request, **kwargs)
        except Organization.DoesNotExist:
            return JsonResponse({
                "non_field_errors": [_("Invalid organization specified")]
            }, status=400)

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
def users(request, **kwargs):
    """
    Returns JsonResponse with a list of all users in the specified org
    """

    org = kwargs.get("org")

    rv = {
        "users": [{
            "id": user.id,
            "name": "%s <%s, %s>" % (user.full_name, user.email, user.username)
        } for user in org.usergroup.user_set.all()]
    }

    rv.update({"status": "ok"})

    return JsonResponse(rv)


@login_required
@org_admin_required
@target_user_validate
def manage_user_delete(request, **kwargs):
    """
    remove user from org
    """

    org = kwargs.get("org")
    user = kwargs.get("user")

    save_user_permissions(org, user, {})
    org.usergroup.user_set.remove(user)
    org.admin_usergroup.user_set.remove(user)

    return JsonResponse({"status": "ok"})


@login_required
@org_admin_required
@target_user_validate
def manage_user_update(request, **kwargs):
    """
    udpate a user in the org

    right now this only allows for moving the user either
    to admin or member group
    """

    org = kwargs.get("org")
    user = kwargs.get("user")
    group = request.POST.get("group")
    if group not in ["member", "admin"]:
        return JsonResponse({
            "group": _("Needs to be member or admin")
        }, status=400)

    if group == "admin":
        org.usergroup.user_set.remove(user)
        org.admin_usergroup.user_set.add(user)
    elif group == "member":
        org.usergroup.user_set.add(user)
        org.admin_usergroup.user_set.remove(user)

    return JsonResponse({"status": "ok"})


@login_required
@org_admin_required
def user_permissions(request, **kwargs):
    """
    Returns JsonRespone with list of user's permissions for the targeted
    org an entities under it

    Permisions are returned as a dict of permissioning ids and permission
    levels.

    Permissioning ids serve as a wrapper for actual permissioning namespaces
    so we can expose them to the organization admins for changes without allowing
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
@org_admin_required
@target_user_validate
def user_permission_update(request, **kwargs):
    """
    Update/Add a user's permission

    perms = permission level
    entity = permission id
    """

    org = kwargs.get("org")
    user = kwargs.get("user")

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
@org_admin_required
@target_user_validate
def user_permission_remove(request, **kwargs):
    """
    Remove a user's permission

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
    Returns list of permissioning ids with labels that
    are valid to be permissioned out to regular org users

    Permissioning ids serve as a wrapper for actual permissioning namespaces
    so we can expose them to the organization admins for changes without allowing
    them to set permissioning namespaces directly.
    """

    org = kwargs.get("org")

    perms = [{
        "id": id,
        "name": name
    } for id, name in permission_ids(org).items()]
    perms = sorted(perms, key=lambda x: x.get("name"))
    return JsonResponse({"status": "ok", "permissions": perms})


@login_required
@csrf_protect
@org_admin_required
def uoar_approve(request, **kwargs):
    """
    Approve a user request to affiliate with the organization
    """

    org = kwargs.get("org")

    try:
        uoar = UserOrgAffiliationRequest.objects.get(id=request.POST.get("id"))
        if uoar.org != org:
            return JsonResponse({}, status=403)

        try:
            user = uoar.user
        except User.DoesNotExist:
            uoar.delete()
            return JsonResponse({"status": "ok"})

        uoar.approve()

        # notify rest of org admins that the affiliation request has been
        # approved

        for admin_user in org.admin_usergroup.user_set.all():
            if admin_user != request.user:
                with override(admin_user.locale):
                    admin_user.email_user(
                        _("%(user_name)s's afilliation request has been approved"
                          ) % {'user_name': uoar.user.full_name},
                        loader.get_template(
                            'email/notify-org-admin-user-affil-approved.txt')
                        .render({
                            "user": request.user,
                            "uoar": uoar,
                            "org_management_url": '%s/org/%d#users' %
                                                  (settings.BASE_URL, org.id)
                        }))

        return JsonResponse({
            "status": "ok",
            "full_name": user.full_name,
            "id": user.id,
            "email": user.email
        })

    except UserOrgAffiliationRequest.DoesNotExist:
        return JsonResponse({"status": "ok"})

    return JsonResponse({"status": "ok"})


@login_required
@csrf_protect
@org_admin_required
def uoar_deny(request, **kwargs):
    """
    Approve a user request to affiliate with the organization
    """

    org = kwargs.get("org")

    try:
        uoar = UserOrgAffiliationRequest.objects.get(id=request.POST.get("id"))
        if uoar.org != org:
            return JsonResponse({}, status=403)

        try:
            user = uoar.user
            uoar.deny()

        except User.DoesNotExist:
            uoar.delete()
            return JsonResponse({"status": "ok"})

        # notify rest of org admins that the affiliation request has been
        # approved

        for user in org.admin_usergroup.user_set.all():
            if user != request.user:
                with override(user.locale):
                    user.email_user(
                        _("%(user_name)s's afilliation request has been denied"
                          ) % {'user_name': uoar.user.full_name},
                        loader.get_template(
                            'email/notify-org-admin-user-affil-denied.txt')
                        .render({
                            "user": request.user,
                            "uoar": uoar,
                            "org_management_url": '%s/org/%d#users' %
                                                  (settings.BASE_URL, org.id)
                        }))

    except UserOrgAffiliationRequest.DoesNotExist:
        return JsonResponse({"status": "ok"})

    return JsonResponse({"status": "ok"})
