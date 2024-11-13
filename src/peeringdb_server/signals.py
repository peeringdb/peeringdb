"""
Django signal handlers

- org usergroup creation
- entity count updates (fac_count, net_count etc.)
- geocode when address model (org, fac) is saved
- verification queue creation on new objects
- asn rdap automation to automatically grant org / network to user
- user to org affiliation handling when targeted org has no users
  - notify admin-com
- CORS enabling for GET api requests

"""

from math import atan2, cos, radians, sin, sqrt
from urllib.parse import urljoin

import django.urls
import reversion
import structlog
from allauth.account.signals import email_confirmed, user_signed_up
from corsheaders.signals import check_request_enabled
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.template import loader
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import override
from django_elasticsearch_dsl.signals import RealTimeSignalProcessor
from django_grainy.models import Group, GroupPermission
from django_peeringdb.const import REGION_MAPPING
from django_peeringdb.models.abstract import AddressModel
from grainy.const import PERM_CRUD, PERM_READ

import peeringdb_server.settings as pdb_settings
from peeringdb_server.deskpro import (
    ticket_queue,
    ticket_queue_asnauto_affil,
    ticket_queue_asnauto_create,
    ticket_queue_vqi_notify,
)
from peeringdb_server.inet import (
    RdapException,
    RdapInvalidRange,
    RdapLookup,
    rdap_pretty_error_message,
    rir_status_is_ok,
)
from peeringdb_server.models import (
    QUEUE_ENABLED,
    QUEUE_NOTIFY,
    Campus,
    EmailAddressData,
    Facility,
    Network,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    UserOrgAffiliationRequest,
    VerificationQueueItem,
)
from peeringdb_server.util import disable_auto_now_and_save

log = structlog.getLogger("django")


def update_network_attribute(instance, attribute):
    """Updates 'attribute' field in Network whenever it's called."""
    if getattr(instance, "id"):
        network = instance.network
        setattr(network, attribute, timezone.now())
        disable_auto_now_and_save(network)


def network_post_revision_commit(**kwargs):
    for vs in kwargs.get("versions"):
        # ignore objects that don't have the HandleRef meta class
        if not hasattr(vs.object, "HandleRef"):
            continue

        if vs.object.HandleRef.tag in ["netixlan", "poc", "netfac"]:
            update_network_attribute(vs.object, f"{vs.object.HandleRef.tag}_updated")


reversion.signals.post_revision_commit.connect(network_post_revision_commit)


def update_counts_for_netixlan(netixlan):
    """
    Whenever a netixlan is saved, update the ix_count for the related Network
    and update net_count for the related InternetExchange.
    """
    if getattr(netixlan, "id"):
        network = netixlan.network

        network.ix_count = (
            network.netixlan_set_active.aggregate(
                ix_count=Count("ixlan__ix_id", distinct=True)
            )
        )["ix_count"]

        disable_auto_now_and_save(network)

        ix = netixlan.ixlan.ix
        ix.net_count = (
            NetworkIXLan.objects.filter(ixlan__ix_id=ix.id, status="ok").aggregate(
                net_count=Count("network_id", distinct=True)
            )
        )["net_count"]
        disable_auto_now_and_save(ix)


def update_counts_for_netfac(netfac):
    """
    Whenever a netfac is saved, update the fac_count for the related Network
    and update net_count for the related Facility.
    """
    if getattr(netfac, "id"):
        network = netfac.network

        network.fac_count = network.netfac_set_active.count()

        disable_auto_now_and_save(network)

        facility = netfac.facility
        facility.net_count = facility.netfac_set_active.count()
        disable_auto_now_and_save(facility)


def update_counts_for_ixfac(ixfac):
    """
    Whenever a ixfac is saved, update the fac_count for the related Exchange
    and update ix_count for the related Facility.
    """
    if getattr(ixfac, "id"):
        ix = ixfac.ix

        ix.fac_count = ix.ixfac_set_active.count()

        disable_auto_now_and_save(ix)

        facility = ixfac.facility
        facility.ix_count = facility.ixfac_set_active.count()
        disable_auto_now_and_save(facility)


def connector_objects_post_revision_commit(**kwargs):
    for vs in kwargs.get("versions"):
        # ignore objects that don't have the HandleRef meta class
        if not hasattr(vs.object, "HandleRef"):
            continue

        if vs.object.HandleRef.tag == "netixlan":
            update_counts_for_netixlan(vs.object)
        if vs.object.HandleRef.tag == "netfac":
            update_counts_for_netfac(vs.object)
        if vs.object.HandleRef.tag == "ixfac":
            update_counts_for_ixfac(vs.object)


reversion.signals.post_revision_commit.connect(connector_objects_post_revision_commit)


def netixlan_sync_asn_on_save(sender, instance, **kwargs):
    """
    When a networkixlan is saved, sync the asn field with the network's asn.
    """
    if instance.asn != instance.network.asn:
        instance.asn = instance.network.asn
        instance.save()


post_save.connect(netixlan_sync_asn_on_save, sender=NetworkIXLan)


def netfac_sync_local_asn_on_save(sender, instance, **kwargs):
    """
    When a networkfacility is saved, sync the local_asn field with the network's asn.
    """
    if instance.local_asn != instance.network.asn:
        instance.local_asn = instance.network.asn
        instance.save()


post_save.connect(netfac_sync_local_asn_on_save, sender=NetworkFacility)


def addressmodel_save(sender, instance=None, **kwargs):
    """
    Mark address model objects for geocode sync if one of the address
    fields is updated.
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


def set_campus_to_facility(sender, instance=None, **kwargs):
    """
    Whenever a facility is saved, check the distance between
    two facilities and validate if it falls within a CAMPUS_MAX_DISTANCE,
    also check if latitude and longitude are in the facility or not
    """
    # Approximate radius of earth in km
    R = 6373.0
    if instance.campus_id:
        if not (instance.latitude and instance.longitude):
            raise ValidationError(
                _(
                    "Facility cannot be made part of a campus as it is missing its geolocation coordinates"
                )
            )

        latitude = radians(instance.latitude)
        longitude = radians(instance.longitude)

        fac = Facility.objects.filter(campus_id=instance.campus_id)

        if fac:
            for obj in fac:
                prev_lat, prev_long = radians(obj.latitude), radians(obj.longitude)
                dlat, dlon = prev_lat - latitude, prev_long - longitude

                a = (
                    sin(dlat / 2) ** 2
                    + cos(latitude) * cos(prev_lat) * sin(dlon / 2) ** 2
                )
                c = 2 * atan2(sqrt(a), sqrt(1 - a))

                distance = R * c

                if distance > settings.CAMPUS_MAX_DISTANCE:
                    raise ValidationError(
                        _(
                            f"Facility out of campus bounds (max. {settings.CAMPUS_MAX_DISTANCE}km)"
                        )
                    )


pre_save.connect(set_campus_to_facility, sender=Facility)


def propagate_campus_status(sender, instance=None, **kwargs):
    if instance and instance.campus_id:
        instance.campus.save()


post_save.connect(propagate_campus_status, sender=Facility)


def campus_status(sender, instance=None, **kwargs):
    """
    Whenever a campus is saved, set the status of
    the campus object based on link facilities
    """

    if instance.status == "deleted":
        # when the campus is deleted make sure all facilities
        # are removed from it
        if instance.id:
            Facility.objects.filter(campus=instance).update(campus=None)
        return
    if instance.id:
        if instance.fac_set.filter(status="ok").count() < 2:
            instance.status = "pending"
        else:
            instance.status = "ok"
    else:
        instance.status = "pending"


pre_save.connect(campus_status, sender=Campus)


def org_save(sender, **kwargs):
    """
    Create a user group for an organization when that
    organization is created.
    """

    inst = kwargs.get("instance")

    # make the general member group for the org
    try:
        Group.objects.get(name=inst.group_name)
    except Group.DoesNotExist:
        group = Group(name=inst.group_name)
        group.save()

        perm = GroupPermission(
            group=group, namespace=inst.grainy_namespace, permission=PERM_READ
        )
        perm.save()

        GroupPermission(
            group=group,
            namespace=f"{inst.grainy_namespace}.network.*.poc_set.private",
            permission=PERM_READ,
        ).save()

        GroupPermission(
            group=group,
            namespace=f"{inst.grainy_namespace}.internetexchange.*.ixf_ixp_member_list_url.private",
            permission=PERM_READ,
        ).save()

    # make the admin group for the org
    try:
        Group.objects.get(name=inst.admin_group_name)
    except Group.DoesNotExist:
        group = Group(name=inst.admin_group_name)
        group.save()

        perm = GroupPermission(
            group=group, namespace=inst.grainy_namespace, permission=PERM_CRUD
        )
        perm.save()

        GroupPermission(
            group=group, namespace=inst.grainy_namespace_manage, permission=PERM_CRUD
        ).save()

        GroupPermission(
            group=group,
            namespace=f"{inst.grainy_namespace}.network.*.poc_set.private",
            permission=PERM_CRUD,
        ).save()

        GroupPermission(
            group=group,
            namespace=f"{inst.grainy_namespace}.internetexchange.*.ixf_ixp_member_list_url.private",
            permission=PERM_CRUD,
        ).save()

    if inst.status == "deleted":
        for ar in inst.affiliation_requests.all():
            ar.delete()


post_save.connect(org_save, sender=Organization)


def org_delete(sender, instance, **kwargs):
    """
    When an organization is HARD deleted, remove any
    usergroups tied to the organization.
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
    group temporarily.

    If pdb_settings.AUTO_VERIFY_USERS is toggled on in the settings, users get automatically verified (Note: this does
    not include email verification, they will still need to do that).
    """

    if pdb_settings.AUTO_VERIFY_USERS:
        user.set_verified()
    else:
        user.set_unverified()


@receiver(email_confirmed, dispatch_uid="allauth.email_confirmed")
def recheck_ownership_requests(request, email_address, **kwargs):
    if request.user.is_authenticated:
        request.user.recheck_affiliation_requests()
    data, _ = EmailAddressData.objects.get_or_create(email=email_address)
    data.confirmed_date = timezone.now()
    data.save()


# USER TO ORGANIZATION AFFILIATION


def uoar_creation(sender, instance, created=False, **kwargs):
    """
    Notify the approporiate management entity when a user to organization affiliation request is created.

    Attempt to derive the targeted organization
    from the ASN the user provided.
    """

    if created:
        network = Network.objects.filter(asn=instance.asn).first()
        if network and network.status == "deleted":
            instance.deny()
            return

        if instance.asn and not instance.org_id:
            if network:
                # network with targeted asn found, set org
                instance.org = network.org

        instance.status = "pending"
        instance.save()

        if instance.org_id and instance.org.admin_usergroup.user_set.count() > 0:
            # check if user's email address matches org requirements
            if instance.org.restrict_user_emails:
                user_org_emails = instance.org.user_meets_email_requirements(
                    instance.user
                )
                if user_org_emails[0] and not user_org_emails[1]:
                    instance.deny()
                    return

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
                                "org_management_url": urljoin(
                                    settings.BASE_URL, f"/org/{instance.org.id}#users"
                                ),
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
                except RdapException:
                    instance.deny()
                    raise
                except Exception as exc:
                    # unhandled exception, deny request and log error
                    instance.deny()
                    log.error("rdap_error", exc=exc, asn=instance.asn)
                    raise RdapException(rdap_pretty_error_message(exc))

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

        # no contact point exists
        if not instance.user_id and not instance.org_key:
            return

        item = instance.item

        if type(item) in QUEUE_NOTIFY and not getattr(
            settings, "DISABLE_VERIFICATION_QUEUE_EMAILS", False
        ):
            if isinstance(item, Network):
                try:
                    rdap = RdapLookup().get_asn(item.asn)
                except (RdapException, RdapInvalidRange):
                    rdap = None
                except Exception as exc:
                    # unhandled exception, log error
                    log.error("rdap_error", exc=exc, asn=item.asn)
                    rdap = None
            else:
                rdap = None

            ticket_queue_vqi_notify(instance, rdap)
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


def auto_fill_region_continent(sender, instance, **kwargs):
    if instance.country.code:
        for region in REGION_MAPPING:
            if instance.country.code == region["code"]:
                instance.region_continent = region["continent"]


pre_save.connect(auto_fill_region_continent, sender=Facility)


class ESSilentRealTimeSignalProcessor(RealTimeSignalProcessor):
    """
    Elasticsearch real time signal processor that silently handles
    update errors
    """

    @property
    def log(self):
        if hasattr(self, "_log"):
            return self._log
        self._log = structlog.getLogger("django")
        return self._log

    def handle_save(self, sender, instance, **kwargs):
        try:
            super().handle_save(sender, instance, **kwargs)
        except Exception as e:
            self.log.error("ELASTICSEARCH", action="save", error=e, instance=instance)
            pass

    def handle_delete(self, sender, instance, **kwargs):
        try:
            super().handle_delete(sender, instance, **kwargs)
        except Exception as e:
            self.log.error("ELASTICSEARCH", action="delete", error=e, instance=instance)
            pass

    def handle_pre_delete(self, sender, instance, **kwargs):
        try:
            return super().handle_pre_delete(sender, instance, **kwargs)
        except Exception as e:
            self.log.error(
                "ELASTICSEARCH", action="pre_delete", error=e, instance=instance
            )
            pass


@receiver(pre_save, sender=Network)
def rir_status_initial(sender, instance=None, **kwargs):
    """
    Implements `Anytime` network update logic for RIR status handling
    laid out in https://github.com/peeringdb/peeringdb/issues/1280

    Anytime a network is saved:

    if an ASN is added, set rir_status="ok" and set `=created
    if an ASN is re-added, set rir_status="ok" and set rir_status_updated=updated
    """

    if not settings.AUTO_UPDATE_RIR_STATUS:
        return

    created = not instance.id

    # if an ASN is added, set rir_status=ok (reset) and set rir_status_updated=created

    if created:
        instance.rir_status = "pending"
        instance.rir_status_updated = timezone.now()

    else:
        old = Network.objects.get(id=instance.id)

        # if an ASN is re-added, set rir_status=ok (reset) and set rir_status_updated=updated

        if old.status == "deleted" and instance.status == "ok":
            instance.rir_status = "pending"
            instance.rir_status_updated = timezone.now()
