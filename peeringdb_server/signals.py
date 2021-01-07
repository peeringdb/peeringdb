from datetime import datetime, timezone
import django.urls
from django.db.models.signals import post_save, pre_delete, pre_save
from django.contrib.contenttypes.models import ContentType
from django_namespace_perms.models import Group, GroupPermission
from django_namespace_perms.constants import PERM_CRUD, PERM_READ
from django.template import loader
from django.conf import settings
from django.dispatch import receiver
import reversion
from allauth.account.signals import user_signed_up

from corsheaders.signals import check_request_enabled

from django_peeringdb.models.abstract import AddressModel

from peeringdb_server.inet import RdapLookup, RdapNotFoundError, RdapException

from peeringdb_server.deskpro import (
    ticket_queue,
    ticket_queue_asnauto_affil,
    ticket_queue_asnauto_create,
)

from peeringdb_server.models import (
    QUEUE_ENABLED,
    QUEUE_NOTIFY,
    UserOrgAffiliationRequest,
    is_suggested,
    VerificationQueueItem,
    Organization,
    InternetExchange,
    Facility,
    Network,
    NetworkContact,
    NetworkIXLan,
    NetworkFacility,
)

import peeringdb_server.settings as pdb_settings

from django.utils.translation import ugettext_lazy as _
from django.utils.translation import override


def disable_auto_now_and_save(entity):
    updated_field = entity._meta.get_field("updated")
    print("Disabling auto now")
    updated_field.auto_now = False
    entity.save()
    print("Re enabling auto now")
    updated_field.auto_now = True


def update_network_attribute(instance, attribute):
    """Updates 'attribute' field in Network whenever it's called."""
    if getattr(instance, "id"):
        network = instance.network
        setattr(network, attribute, datetime.now(timezone.utc))
        # disable_auto_now_and_save(network)


def netixlan_update(sender, instance=None, **kwargs):
    """
    Update "netixlan_updated" field of Network whenever a connected
    NetworkIXLan is updated
    """
    print(" - - ")
    print("Sending Netixlan signal")
    update_network_attribute(instance, "netixlan_updated")


def netfac_update(sender, instance=None, **kwargs):
    """
    Update "netfac_updated" field of Network whenever a connected
    NetworkFacility is updated
    """
    print(" - - ")
    print("Sending netfac signal")

    update_network_attribute(instance, "netfac_updated")


def poc_update(sender, instance=None, **kwargs):
    """
    Update "poc_updated" field of Network whenever a connected
    NetworkContact is updated
    """
    print(" - - ")
    print("Sending poc signal")

    update_network_attribute(instance, "poc_updated")


# post_save.connect(netixlan_update, sender=NetworkIXLan)
# post_save.connect(netfac_update, sender=NetworkFacility)
# post_save.connect(poc_update, sender=NetworkContact)


def addressmodel_save(sender, instance=None, **kwargs):
    """
    Mark address model objects for geocode sync if one of the address
    fields is updated
    """

    if instance.id:
        # instance is being updated
        old = sender.objects.get(id=instance.id)
        for field in AddressModel._meta.get_fields():
            if field.name in ["latitude", "longitude"]:
                continue
            a = getattr(instance, field.name)
            b = getattr(old, field.name)
            if a != b:
                # print("Change in field '%s' - '%s'(%s) to '%s'(%s) - marking %s for geocode sync" % (field.name, a, type(a), b, type(b), instance))
                # address model field has changed, mark for geocode sync
                instance.geocode_status = False


pre_save.connect(addressmodel_save, sender=Facility)


def org_save(sender, **kwargs):
    """
    we want to create a user group for an organization when that
    organization is created
    """

    inst = kwargs.get("instance")
    ix_namespace = InternetExchange.nsp_namespace_from_id(inst.id, "*")

    # make the general member group for the org
    try:
        group = Group.objects.get(name=inst.group_name)
    except Group.DoesNotExist:
        group = Group(name=inst.group_name)
        group.save()

        perm = GroupPermission(
            group=group, namespace=inst.nsp_namespace, permissions=PERM_READ
        )
        perm.save()

        GroupPermission(
            group=group,
            namespace=NetworkContact.nsp_namespace_from_id(inst.id, "*", "private"),
            permissions=PERM_READ,
        ).save()

        GroupPermission(
            group=group,
            namespace=f"{ix_namespace}.ixf_ixp_member_list_url.private",
            permissions=PERM_READ,
        ).save()

    # make the admin group for the org
    try:
        group = Group.objects.get(name=inst.admin_group_name)
    except Group.DoesNotExist:
        group = Group(name=inst.admin_group_name)
        group.save()

        perm = GroupPermission(
            group=group, namespace=inst.nsp_namespace, permissions=PERM_CRUD
        )
        perm.save()

        GroupPermission(
            group=group, namespace=inst.nsp_namespace_manage, permissions=PERM_CRUD
        ).save()

        GroupPermission(
            group=group,
            namespace=NetworkContact.nsp_namespace_from_id(inst.id, "*", "private"),
            permissions=PERM_CRUD,
        ).save()

        GroupPermission(
            group=group,
            namespace=f"{ix_namespace}.ixf_ixp_member_list_url.private",
            permissions=PERM_CRUD,
        ).save()

    if inst.status == "deleted":
        for ar in inst.affiliation_requests.all():
            ar.delete()


post_save.connect(org_save, sender=Organization)


def org_delete(sender, instance, **kwargs):
    """
    When an organization is HARD deleted we want to also remove any
    usergroups tied to the organization
    """

    try:
        instance.usergroup.delete()
    except Group.DoesNotExist:
        pass

    try:
        instance.admin_usergroup.delete()
    except Group.DoesNotExist:
        pass

    for ar in instance.affiliation_requests.all():
        ar.delete()


pre_delete.connect(org_delete, sender=Organization)


@receiver(user_signed_up, dispatch_uid="allauth.user_signed_up")
def new_user_to_guests(request, user, sociallogin=None, **kwargs):
    """
    When a user is created via oauth login put them in the guest
    group for now.

    Unless pdb_settings.AUTO_VERIFY_USERS is toggled on in settings, in which
    case users get automatically verified (note that this does
    not include email verification, they will still need to do that)
    """

    if pdb_settings.AUTO_VERIFY_USERS:
        user.set_verified()
    else:
        user.set_unverified()


# USER TO ORGANIZATION AFFILIATION


def uoar_creation(sender, instance, created=False, **kwargs):
    """
    When a user to organization affiliation request is created
    we want to notify the approporiate management entity

    We also want to attempt to derive the targeted organization
    from the ASN the user provided
    """

    if created:

        if instance.asn and not instance.org_id:
            network = Network.objects.filter(asn=instance.asn).first()
            if network:
                # network with targeted asn found, set org
                instance.org = network.org

        instance.status = "pending"
        instance.save()

        if instance.org_id and instance.org.admin_usergroup.user_set.count() > 0:

            # check that user is not already a member of that org
            if instance.user.groups.filter(name=instance.org.usergroup.name).exists():
                instance.approve()
                return

            # organization exists already and has admins, notify organization
            # admins
            for user in instance.org.admin_usergroup.user_set.all():
                with override(user.locale):
                    user.email_user(
                        _(
                            "User %(u_name)s wishes to be affiliated to your Organization"
                        )
                        % {"u_name": instance.user.full_name},
                        loader.get_template(
                            "email/notify-org-admin-user-affil.txt"
                        ).render(
                            {
                                "user": instance.user,
                                "org": instance.org,
                                "org_management_url": "%s/org/%d#users"
                                % (settings.BASE_URL, instance.org.id),
                            }
                        ),
                    )
        else:
            request_type = "be affiliated to"
            rdap_data = {"emails": []}
            org_created = False
            net_created = False
            rdap_lookup = None
            if instance.asn and not instance.org_id:
                # ASN specified in request, but no network found
                # Lookup RDAP information
                try:
                    rdap_lookup = rdap = RdapLookup().get_asn(instance.asn)
                    ok = rdap_lookup.emails
                except RdapException as inst:
                    instance.deny()
                    raise

                # create organization
                instance.org, org_created = Organization.create_from_rdap(
                    rdap, instance.asn, instance.org_name
                )
                instance.save()

                # create network
                net, net_created = Network.create_from_rdap(
                    rdap, instance.asn, instance.org
                )

                # if affiliate auto appove is on, auto approve at this point
                if pdb_settings.AUTO_APPROVE_AFFILIATION:
                    instance.approve()
                    return

                ticket_queue_asnauto_create(
                    instance.user,
                    instance.org,
                    net,
                    rdap,
                    net.asn,
                    org_created=org_created,
                    net_created=net_created,
                )

                # if user's relationship to network can be validated now
                # we can approve the ownership request right away
                if instance.user.validate_rdap_relationship(rdap):
                    instance.approve()
                    ticket_queue_asnauto_affil(instance.user, instance.org, net, rdap)
                    return

            if instance.org:
                # organization has been set on affiliation request
                entity_name = instance.org.name
                if not instance.org.owned:
                    # organization is currently not owned
                    request_type = "request ownership of"

                    # if affiliate auto appove is on, auto approve at this point
                    if pdb_settings.AUTO_APPROVE_AFFILIATION:
                        instance.approve()
                        return

                    # if user's relationship to the org can be validated by
                    # checking the rdap information of the org's networks
                    # we can approve the affiliation (ownership) request right away
                    for asn, rdap in list(instance.org.rdap_collect.items()):
                        rdap_data["emails"].extend(rdap.emails)
                        if instance.user.validate_rdap_relationship(rdap):
                            ticket_queue_asnauto_affil(
                                instance.user,
                                instance.org,
                                Network.objects.get(asn=asn),
                                rdap,
                            )
                            instance.approve()
                            return
            else:
                entity_name = instance.org_name

                if pdb_settings.AUTO_APPROVE_AFFILIATION:
                    org = Organization.objects.create(
                        name=instance.org_name, status="ok"
                    )
                    instance.org = org
                    instance.approve()
                    return

            # organization has no owners and RDAP information could not verify the user's relationship to the organization, notify pdb staff for review
            ticket_queue(
                "User %s wishes to %s %s"
                % (instance.user.username, request_type, entity_name),
                loader.get_template("email/notify-pdb-admin-user-affil.txt").render(
                    {
                        "user": instance.user,
                        "instance": instance,
                        "base_url": settings.BASE_URL,
                        "org_add_url": "%s%s"
                        % (
                            settings.BASE_URL,
                            django.urls.reverse(
                                "admin:peeringdb_server_organization_add"
                            ),
                        ),
                        "net_add_url": "%s%s"
                        % (
                            settings.BASE_URL,
                            django.urls.reverse("admin:peeringdb_server_network_add"),
                        ),
                        "review_url": "%s%s"
                        % (
                            settings.BASE_URL,
                            django.urls.reverse(
                                "admin:peeringdb_server_user_change",
                                args=(instance.user.id,),
                            ),
                        ),
                        "approve_url": "%s%s"
                        % (
                            settings.BASE_URL,
                            django.urls.reverse(
                                "admin:peeringdb_server_userorgaffiliationrequest_actions",
                                args=(instance.id, "approve_and_notify"),
                            ),
                        ),
                        "emails": list(set(rdap_data["emails"])),
                        "rdap_lookup": rdap_lookup,
                    }
                ),
                instance.user,
            )

    elif instance.status == "approved" and instance.org_id:

        # uoar was not created, and status is now approved, call approve
        # to finalize

        instance.approve()


post_save.connect(uoar_creation, sender=UserOrgAffiliationRequest)

# VERIFICATION QUEUE

if getattr(settings, "DISABLE_VERIFICATION_QUEUE", False) is False:

    def verification_queue_update(sender, instance, **kwargs):
        if instance.status == "pending":
            try:
                VerificationQueueItem.objects.get(
                    content_type=ContentType.objects.get_for_model(sender),
                    object_id=instance.id,
                )
            except VerificationQueueItem.DoesNotExist:
                q = VerificationQueueItem(item=instance)
                q.save()
        else:
            try:
                q = VerificationQueueItem.objects.get(
                    content_type=ContentType.objects.get_for_model(sender),
                    object_id=instance.id,
                )
                q.delete()
            except VerificationQueueItem.DoesNotExist:
                pass

    def verification_queue_delete(sender, instance, **kwargs):
        try:
            q = VerificationQueueItem.objects.get(
                content_type=ContentType.objects.get_for_model(sender),
                object_id=instance.id,
            )
            q.delete()
        except VerificationQueueItem.DoesNotExist:
            pass

    def verification_queue_notify(sender, instance, **kwargs):
        # notification was already sent
        if instance.notified:
            return

        # we don't sent notifications unless requesting user has been identified
        if not instance.user_id:
            return

        item = instance.item
        user = instance.user

        if type(item) in QUEUE_NOTIFY and not getattr(
            settings, "DISABLE_VERIFICATION_QUEUE_EMAILS", False
        ):

            if type(item) == Network:
                rdap = RdapLookup().get_asn(item.asn)
            else:
                rdap = None

            with override("en"):
                entity_type_name = str(instance.content_type)

            title = f"{entity_type_name} - {item}"

            if is_suggested(item):
                title = f"[SUGGEST] {title}"

            ticket_queue(
                title,
                loader.get_template("email/notify-pdb-admin-vq.txt").render(
                    {
                        "entity_type_name": entity_type_name,
                        "suggested": is_suggested(item),
                        "item": item,
                        "user": user,
                        "rdap": rdap,
                        "edit_url": "%s%s"
                        % (settings.BASE_URL, instance.item_admin_url),
                    }
                ),
                instance.user,
            )

            instance.notified = True
            instance.save()

    post_save.connect(verification_queue_notify, sender=VerificationQueueItem)

    for model in QUEUE_ENABLED:
        post_save.connect(verification_queue_update, sender=model)
        pre_delete.connect(verification_queue_delete, sender=model)


def cors_allow_api_get_to_everyone(sender, request, **kwargs):
    # FIXME: path name to look for should come from config
    return (
        request.path == "/api" or request.path.startswith("/api/")
    ) and request.method in ["GET", "OPTIONS"]


check_request_enabled.connect(cors_allow_api_get_to_everyone)
