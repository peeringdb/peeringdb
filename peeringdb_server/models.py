import re
import json
import datetime
from itertools import chain
import uuid
import ipaddress
import googlemaps.exceptions
import requests
import reversion

import django.urls
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.models import UserManager, Group
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core import validators
from django.core.mail.message import EmailMultiAlternatives
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.http import urlquote
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import override
from django.conf import settings
from django.template import loader
from django_namespace_perms.util import autodiscover_namespaces, has_perms
from django_handleref.models import (
    CreatedDateTimeField,
    UpdatedDateTimeField,
)
import django_peeringdb.models as pdb_models
from django_inet.models import ASNField

from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.socialaccount.models import SocialAccount
from passlib.hash import sha256_crypt

from peeringdb_server.inet import RdapLookup, RdapNotFoundError
from peeringdb_server.validators import (
    validate_address_space,
    validate_info_prefixes4,
    validate_info_prefixes6,
    validate_prefix_overlap,
    validate_phonenumber,
    validate_irr_as_set,
)

SPONSORSHIP_LEVELS = (
    (1, _("Silver")),
    (2, _("Gold")),
    (3, _("Platinum")),
    (4, _("Diamond")),
)

PARTNERSHIP_LEVELS = ((1, _("Data Validation")), (2, _("RIR")))

COMMANDLINE_TOOLS = (
    ("pdb_renumber_lans", _("Renumber IP Space")),
    ("pdb_fac_merge", _("Merge Facilities")),
    ("pdb_fac_merge_undo", _("Merge Facilities: UNDO")),
    ("pdb_undelete", _("Restore Object(s)")),
)


if settings.TUTORIAL_MODE:
    COMMANDLINE_TOOLS += (("pdb_wipe", _("Reset Environment")),)

COMMANDLINE_TOOLS += (("pdb_ixf_ixp_member_import", _("IX-F Import")),)


def debug_mail(*args):
    for arg in list(args):
        print(arg)
        print("-----------------------------------")


def make_relation_filter(field, filt, value, prefix=None):
    if prefix:
        field = re.sub("^%s__" % prefix, "", field)
        field = re.sub("^%s_" % prefix, "", field)
        if field == prefix:
            field = "id"
    if filt:
        filt = {"%s__%s" % (field, filt): value}
    else:
        filt = {field: value}
    filt.update(status="ok")
    return filt


def validate_PUT_ownership(user, instance, data, fields):
    """
    Helper function that checks if a user has write perms to
    the instance provided as well as write perms to any
    child instances specified by fields as they exist on
    the model and in data

    example:

    validate_PUT_ownership(
      request.user,
      network_contact,
      {
        "network": 123,
        ...
      },
      ["network"]
    )

    will check that the user has write perms to

      1. <NetworkContact> network_contact
      2. <Network> network_contact.network
      3. <Network> network(id=123)

    if any fail the permission check False is returned.
    """

    if not has_perms(user, instance, "update"):
        return False

    for fld in fields:
        if fld == "net":
            field_name = "network"
        elif fld == "fac":
            field_name = "facility"
        else:
            field_name = fld
        a = getattr(instance, field_name)
        try:
            s_id = int(data.get(fld, data.get("%s_id" % fld)))
        except ValueError:
            continue

        if a.id != s_id:
            try:
                other = a.__class__.objects.get(id=s_id)
                if not has_perms(user, other, "update"):
                    return False
            except ValueError:  # if id is not intable
                return False

    return True


def is_suggested(entity):
    """
    Check if the network, facility or exchange is a suggested
    entity (is it a memeber of the organization designated to
    hold suggested entities)
    """

    # if no org is specified, entity suggestion is turned
    # off
    if not getattr(settings, "SUGGEST_ENTITY_ORG", 0):
        return False

    org_id = getattr(entity, "org_id", 0)
    return org_id == settings.SUGGEST_ENTITY_ORG


class UTC(datetime.tzinfo):
    """
    UTC+0 tz for tz aware datetime fields
    """

    def utcoffset(self, d):
        return datetime.timedelta(seconds=0)


class URLField(pdb_models.URLField):
    """
    local defaults for URLField
    """

    pass

class ProtectedAction(ValueError):
    pass

class ProtectedMixin:

    """
    Mixin that implements checks for changing
    / deleting a model instance that will block
    such actions under certain circumstances
    """

    @property
    def deletable(self):
        """
        Should return whether the object is currently
        in a state where it can safely be soft-deleted

        If not not deletable, should specify reason in
        `_not_deletable_reason` property.

        If deletable should, set `_not_deletable_reason`
        property to None
        """
        return True

    @property
    def not_deletable_reason(self):
        return getattr(self, "_not_deletable_reason", None)

    def delete(self, hard=False, force=False):
        if not self.deletable and not force:
            raise ProtectedAction(self.not_deletable_reason)

        self.delete_cleanup()
        return super().delete(hard=hard)

    def delete_cleanup(self):
        """
        Runs cleanup before delete

        Override this in the class that uses this mixin (if needed)
        """
        return



class GeocodeBaseMixin(models.Model):
    """
    Mixin to use for geocode enabled entities
    Allows an entity to be geocoded with the pdb_geo_sync command
    """

    geocode_status = models.BooleanField(
        default=False,
        help_text=_(
            "Has this object's latitude and longitude been syncronized to it's address fields"
        ),
    )
    geocode_date = models.DateTimeField(
        blank=True, null=True, help_text=_("Last time of attempted geocode")
    )
    geocode_error = models.TextField(
        blank=True, null=True, help_text=_("Error message of previous geocode attempt")
    )

    class Meta(object):
        abstract = True

    @property
    def geocode_coordinates(self):
        """
        Return a tuple holding the latitude and longitude
        """
        if self.latitude is not None and self.longitude is not None:
            return (self.latitude, self.longitude)
        return None

    @property
    def geocode_address(self):
        """
        Returns an address string suitable for googlemaps query
        """
        # pylint: disable=missing-format-attribute
        return "{e.address1} {e.address2}, {e.city}, {e.state} {e.zipcode}".format(
            e=self
        )

    def geocode(self, gmaps, save=True):
        """
        Sets the latitude, longitude field values of this model by geocoding the
        address specified in the relevant fields.

        Argument(s):

            - gmaps: googlemaps instance
        """
        try:
            result = gmaps.geocode(
                self.geocode_address, components={"country": self.country.code}
            )
            if result and (
                "street_address" in result[0]["types"]
                or "establishment" in result[0]["types"]
                or "premise" in result[0]["types"]
                or "subpremise" in result[0]["types"]
            ):
                loc = result[0].get("geometry").get("location")
                self.latitude = loc.get("lat")
                self.longitude = loc.get("lng")
                self.geocode_error = None
            else:
                self.latitude = None
                self.longitude = None
                self.geocode_error = _("Address not found")
            self.geocode_status = True
            return result
        except (
            googlemaps.exceptions.HTTPError,
            googlemaps.exceptions.ApiError,
        ) as inst:
            self.geocode_error = str(inst)
            self.geocode_status = True
        except googlemaps.exceptions.Timeout as inst:
            self.geocode_error = _("API Timeout")
            self.geocode_status = False
        finally:
            self.geocode_date = datetime.datetime.now().replace(tzinfo=UTC())
            if save:
                self.save()


class UserOrgAffiliationRequest(models.Model):
    """
    Whenever a user requests to be affiliated to an Organization
    through an ASN the request is stored in this object.

    When an ASN is entered that is not in the database yet it will
    notify PDB staff

    When an ASN is entered that is already in the database the organzation
    adminstration is notified and they can then approve or deny
    the affiliation request themselves.

    Please look at signals.py for the logic of notification as
    well as deriving the organization from the ASN during creation.
    """

    org = models.ForeignKey(
        "peeringdb_server.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text=_(
            "This organization in our database that was derived from the provided ASN or organization name. If this is empty it means no matching organization was found."
        ),
        related_name="affiliation_requests",
    )

    org_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text=_("The organization name entered by the user"),
    )

    asn = ASNField(help_text=_("The ASN entered by the user"), null=True, blank=True)

    user = models.ForeignKey(
        "peeringdb_server.User",
        on_delete=models.CASCADE,
        help_text=_("The user that made the request"),
        related_name="affiliation_requests",
    )

    created = CreatedDateTimeField()

    status = models.CharField(
        max_length=254,
        choices=[
            ("pending", _("Pending")),
            ("approved", _("Approved")),
            ("denied", _("Denied")),
            ("canceled", _("Canceled")),
        ],
        help_text=_("Status of this request"),
    )

    class Meta(object):
        db_table = "peeringdb_user_org_affil_request"
        verbose_name = _("User to Organization Affiliation Request")
        verbose_name_plural = _("User to Organization Affiliation Requests")

    @property
    def name(self):
        """
        If org is set, returns the org's name otherwise returns the
        value specified in self.org_name
        """
        if self.org_id:
            return self.org.name
        elif self.org_name:
            return self.org_name
        return self.asn

    def approve(self):
        """
        approve request and add user to org's usergroup
        """

        if self.org_id:
            if (
                self.org.admin_usergroup.user_set.count() > 0
                or self.org.usergroup.user_set.count() > 0
            ):
                # if there are other users in this org, add user as normal
                # member
                self.org.usergroup.user_set.add(self.user)
            else:
                # if there are no other users in this org, add user as admin
                # member
                self.org.admin_usergroup.user_set.add(self.user)

            # we set user to verified
            if not self.user.is_verified_user:
                self.user.set_verified()

            # since it was approved, we dont need to keep the
            # request item around
            self.status = "approved"
            self.delete()

    def deny(self):
        """
        deny request, marks request as denied and keeps
        it around until requesting user deletes it
        """

        self.status = "denied"
        self.save()

    def cancel(self):
        """
        deny request, marks request as canceled and keeps
        it around until requesting user deletes it
        """
        self.status = "canceled"
        self.save()

    def notify_ownership_approved(self):
        """
        Sends a notification email to the requesting user
        """
        if not self.org:
            return
        # FIXME: why not have the `override` call in email_user in the first place?
        with override(self.user.locale):
            self.user.email_user(
                _('Your affiliation to Organization "{}" has been approved').format(
                    self.org.name
                ),
                loader.get_template(
                    "email/notify-user-uoar-ownership-approved.txt"
                ).render(
                    {
                        "uoar": self,
                        "org_url": "{}/org/{}".format(settings.BASE_URL, self.org.id),
                        "support_email": settings.DEFAULT_FROM_EMAIL,
                    }
                ),
            )


class VerificationQueueItem(models.Model):
    """
    Keeps track of new items created that need to be reviewed and approved
    by administrators

    Queue items are added through the create signals tied to the various
    objects (peeringdb_server/signals.py)
    """

    # reference to the item that requires review stored in generic fk
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")
    user = models.ForeignKey(
        "peeringdb_server.User",
        on_delete=models.CASCADE,
        related_name="vqitems",
        null=True,
        blank=True,
        help_text=_("The item that this queue is attached to was created by this user"),
    )
    created = CreatedDateTimeField()
    notified = models.BooleanField(default=False)

    class Meta(object):
        db_table = "peeringdb_verification_queue"
        unique_together = (("content_type", "object_id"),)

    @classmethod
    def get_for_entity(cls, entity):
        """
        Returns verification queue item for the provided
        entity if it exists, else raises a DoesNotExist
        exception
        """

        return cls.objects.get(
            content_type=ContentType.objects.get_for_model(type(entity)),
            object_id=entity.id,
        )

    @property
    def item_admin_url(self):
        """
        Return admin url for the object in the verification queue
        """
        return django.urls.reverse(
            "admin:%s_%s_change"
            % (self.content_type.app_label, self.content_type.model),
            args=(self.object_id,),
        )

    @property
    def approve_admin_url(self):
        """
        Return admin url for approval of the verification queue item
        """
        return django.urls.reverse(
            "admin:%s_%s_actions" % (self._meta.app_label, self._meta.model_name),
            args=(self.id, "vq_approve"),
        )

    @property
    def deny_admin_url(self):
        """
        Return admin url for denial of the verification queue item
        """
        return django.urls.reverse(
            "admin:%s_%s_actions" % (self._meta.app_label, self._meta.model_name),
            args=(self.id, "vq_deny"),
        )

    @reversion.create_revision()
    def approve(self):
        """
        Approve the verification queue item
        """
        if hasattr(self.item, "status"):
            self.item.status = "ok"
        if hasattr(self.item, "vq_approve"):
            self.item.vq_approve()

        self.item.save()

    def deny(self):
        """
        Deny the verification queue item
        """
        if hasattr(self.item, "vq_deny"):
            self.item.vq_deny()
        else:
            if hasattr(self.item, "ref_tag"):
                self.item.delete(hard=True)
            else:
                self.item.delete()


class DeskProTicket(models.Model):
    subject = models.CharField(max_length=255)
    body = models.TextField()
    user = models.ForeignKey("peeringdb_server.User", on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)
    published = models.DateTimeField(null=True)

    class Meta:
        verbose_name = _("DeskPRO Ticket")
        verbose_name_plural = _("DeskPRO Tickets")


@reversion.register
class Organization(ProtectedMixin, pdb_models.OrganizationBase):
    """
    Describes a peeringdb organization
    """

    # FIXME: change this to ImageField - keep
    # FileField for now as the server doesn't have all the
    # dependencies installedd (libjpeg / Pillow)
    logo = models.FileField(
        upload_to="logos/",
        null=True,
        blank=True,
        help_text=_(
            "Allows you to upload and set a logo image file for this organization"
        ),
    )

    @staticmethod
    def autocomplete_search_fields():
        return (
            "id__iexact",
            "name__icontains",
        )

    def __unicode__(self):
        return self.name

    def related_label(self):
        """
        Used by grappelli autocomplete for representation

        Since grappelli doesnt easily allow us to filter status
        during autocomplete lookup, we make sure the objects
        are marked accordingly in the result
        """
        if self.status == "deleted":
            return "[DELETED] {}".format(self)
        return "{}".format(self)

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity
        """
        return self.name

    @property
    def admin_url(self):
        """
        Return the admin url for this organization (in /cp)
        """
        return django.urls.reverse(
            "admin:peeringdb_server_organization_change", args=(self.id,)
        )

    @property
    def view_url(self):
        """
        Return the URL to this organizations web view
        """
        return "{}{}".format(
            settings.BASE_URL, django.urls.reverse("org-view", args=(self.id,))
        )

    @property
    def deletable(self):
        """
        Returns whether or not the organization is currently
        in a state where it can be marked as deleted.

        This will be False for organization's of which ANY
        of the following is True:

        - has a network under it with status=ok
        - has a facility under it with status=ok
        - has an exchange under it with status=ok
        """

        is_empty = (
            self.ix_set_active.count() == 0 and
            self.fac_set_active.count() == 0 and
            self.net_set_active.count() == 0
        )

        if not is_empty:
            self._not_deletable_reason = _(
                "Organization currently has one or more active " \
                "objects under it."
            )
            return False
        elif self.sponsorship and self.sponsorship.active:
            self._not_deletable_reason = _(
                "Organization is currently an active sponsor. "\
                "Please contact PeeringDB support to help facilitate "\
                "the removal of this organization."
            )
            return False
        else:
            self._not_deletable_reason = None
            return True

    @property
    def owned(self):
        """
        Returns whether or not the organization has been claimed
        by any users
        """
        return self.admin_usergroup.user_set.count() > 0

    @property
    def rdap_collect(self):
        """
        Fetche rdap results for all networks under this org and returns
        them by asn
        """
        r = {}
        for net in self.net_set_active:
            try:
                rdap = RdapLookup().get_asn(net.asn)
                if rdap:
                    r[net.asn] = rdap
            except RdapNotFoundError as inst:
                pass
        return r

    @property
    def urls(self):
        """
        Returns all the websites for the org based on it's
        website field and the website fields on all the entities it
        owns
        """
        rv = []
        if self.website:
            rv.append(self.website)
        for tag in ["ix", "net", "fac"]:
            for ent in getattr(self, "%s_set_active" % tag):
                if ent.website:
                    rv.append(ent.website)

        return list(set(rv))

    @property
    def nsp_namespace_manage(self):
        """
        Org administrators need CRUD to this namespace in order
        to execute administrative actions (user management, user permission
        management)
        """
        return "peeringdb.manage_organization.%s" % self.id

    @classmethod
    def nsp_namespace_from_id(cls, id):
        return "peeringdb.organization.%s" % id

    @property
    def pending_affiliations(self):
        """
        Returns queryset holding pending affiliations to this
        organization
        """
        return self.affiliation_requests.filter(status="pending")

    @property
    def net_set_active(self):
        """
        Returns queryset holding active networks in this organization
        """
        return self.net_set(manager="handleref").filter(status="ok")

    @property
    def fac_set_active(self):
        """
        Returns queryset holding active facilities in this organization
        """
        return self.fac_set(manager="handleref").filter(status="ok")

    @property
    def ix_set_active(self):
        """
        Returns queryset holding active exchanges in this organization
        """
        return self.ix_set(manager="handleref").filter(status="ok")

    @property
    def nsp_namespace(self):
        """
        Returns permissioning namespace for this organization
        """
        return self.__class__.nsp_namespace_from_id(self.id)

    @property
    def group_name(self):
        """
        Returns usergroup name for this organization
        """
        return "org.%s" % self.id

    @property
    def admin_group_name(self):
        """
        Returns admin usergroup name for this organization
        """
        return "%s.admin" % self.group_name

    @property
    def usergroup(self):
        """
        Returns the usergroup for this organization
        """
        return Group.objects.get(name=self.group_name)

    @property
    def admin_usergroup(self):
        """
        Returns the admin usergroup for this organization
        """
        return Group.objects.get(name=self.admin_group_name)

    @property
    def all_users(self):
        """
        returns a set of all users in the org's user and admin groups
        """
        users = {}
        for user in self.usergroup.user_set.all():
            users[user.id] = user
        for user in self.admin_usergroup.user_set.all():
            users[user.id] = user

        return sorted(list(users.values()), key=lambda x: x.full_name)

    @property
    def nsp_ruleset(self):
        """
        Returns a dict containing rules for django namespace perms
        to be used when applying perms to serialized oranization
        data
        """
        return {
            # since poc are stored in a list we need to specify a list
            # handler for it, its a class function on NetworkContact that
            # returns a relative permission namespace for each poc in the
            # list
            "list-handlers": {
                "poc_set": {"namespace": NetworkContact.nsp_namespace_in_list}
            }
        }

    @property
    def sponsorship(self):
        """
        Returns sponsorship object for this organization. If the organization
        has no sponsorship ongoing return None
        """
        now = datetime.datetime.now().replace(tzinfo=UTC())
        return (
            self.sponsorship_set.filter(start_date__lte=now, end_date__gte=now)
            .order_by("-start_date")
            .first()
        )

    @classmethod
    @reversion.create_revision()
    def create_from_rdap(cls, rdap, asn, org_name=None):
        """
        Creates organization from rdap result object
        """
        name = rdap.org_name
        if not name:
            name = org_name or ("AS%d" % (asn))
        if cls.objects.filter(name=name).exists():
            return cls.objects.get(name=name), False
        else:
            org = cls.objects.create(name=name, status="ok")
        return org, True

    def delete_cleanup(self, hard=False):
        for affiliation in self.affiliation_requests.filter(status="pending"):
            affiliation.cancel()

def default_time_s():
    """
    Returns datetime set to today with a time of 00:00:00
    """
    now = datetime.datetime.now()
    return now.replace(hour=0, minute=0, second=0, tzinfo=UTC())


def default_time_e():
    """
    Returns datetime set to today with a time of 23:59:59
    """
    now = datetime.datetime.now()
    return now.replace(hour=23, minute=59, second=59, tzinfo=UTC())


class Sponsorship(models.Model):
    """
    Allows an organization to be marked for sponsorship
    for a designated timespan
    """

    orgs = models.ManyToManyField(
        Organization,
        through="peeringdb_server.SponsorshipOrganization",
        related_name="sponsorship_set",
    )
    start_date = models.DateTimeField(
        _("Sponsorship starts on"), default=default_time_s
    )
    end_date = models.DateTimeField(_("Sponsorship ends on"), default=default_time_e)
    notify_date = models.DateTimeField(
        _("Expiration notification sent on"), null=True, blank=True
    )
    level = models.PositiveIntegerField(choices=SPONSORSHIP_LEVELS, default=1)

    class Meta:
        db_table = "peeringdb_sponsorship"
        verbose_name = _("Sponsorship")
        verbose_name_plural = _("Sponsorships")

    @classmethod
    def active_by_org(cls):
        """
        Yields (Organization, Sponsorship) for all currently
        active sponsorships
        """
        now = datetime.datetime.now().replace(tzinfo=UTC())
        qset = cls.objects.filter(start_date__lte=now, end_date__gte=now)
        qset = qset.prefetch_related("sponsorshiporg_set")
        for sponsorship in qset:
            for org in sponsorship.orgs.all():
                yield org, sponsorship

    @property
    def active(self):
        now = datetime.datetime.now().replace(tzinfo=UTC())
        return (self.start_date <= now and self.end_date >= now)

    @property
    def label(self):
        """
        Returns the label for this sponsorship's level
        """
        return dict(SPONSORSHIP_LEVELS).get(self.level)

    def notify_expiration(self):
        """
        Sends an expiration notice to SPONSORSHIPS_EMAIL

        Notification is only sent if notify_date < expiration_date
        """

        if self.notify_date is not None and self.notify_date >= self.end_date:
            return False
        msg = loader.get_template(
            "email/notify-sponsorship-admin-expiration.txt"
        ).render({"instance": self})

        org_names = ", ".join([org.name for org in self.orgs.all()])

        mail = EmailMultiAlternatives(
            ("{}: {}").format(_("Sponsorship Expired"), org_names),
            msg,
            settings.DEFAULT_FROM_EMAIL,
            [settings.SPONSORSHIPS_EMAIL],
        )
        mail.attach_alternative(msg.replace("\n", "<br />\n"), "text/html")
        mail.send(fail_silently=True)

        self.notify_date = datetime.datetime.now()
        self.save()

        return True


class SponsorshipOrganization(models.Model):
    """
    Describes an organization->sponsorship relationship
    """

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="sponsorshiporg_set"
    )
    sponsorship = models.ForeignKey(
        Sponsorship, on_delete=models.CASCADE, related_name="sponsorshiporg_set"
    )
    url = models.URLField(
        _("URL"),
        help_text=_(
            "If specified clicking the sponsorship will take the user to this location"
        ),
        blank=True,
        null=True,
    )

    logo = models.FileField(
        upload_to="logos/",
        null=True,
        blank=True,
        help_text=_(
            "Allows you to upload and set a logo image file for this sponsorship"
        ),
    )


class Partnership(models.Model):
    """
    Allows an organization to be marked as a partner

    It will appear on the "partners" page
    """

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="partnerships"
    )
    level = models.PositiveIntegerField(choices=PARTNERSHIP_LEVELS, default=1)
    url = models.URLField(
        _("URL"),
        help_text=_(
            "If specified clicking the partnership will take the user to this location"
        ),
        blank=True,
        null=True,
    )

    logo = models.FileField(
        upload_to="logos/",
        null=True,
        blank=True,
        help_text=_(
            "Allows you to upload and set a logo image file for this partnership"
        ),
    )

    class Meta:
        db_table = "peeringdb_partnership"
        verbose_name = _("Partnership")
        verbose_name_plural = _("Partnerships")

    @property
    def label(self):
        return dict(PARTNERSHIP_LEVELS).get(self.level)


class OrganizationMerge(models.Model):
    """
    When an organization is merged into another via admin.merge_organizations
    it is logged here, allowing the merge to be undone
    """

    from_org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="merged_to"
    )
    to_org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="merged_from"
    )
    created = models.DateTimeField(_("Merged on"), auto_now_add=True)

    class Meta:
        db_table = "peeringdb_organization_merge"
        verbose_name = _("Organization Merge")
        verbose_name_plural = _("Organization Merges")

    def log_entity(self, entity, note=""):
        """
        mark an entity as moved during this particular merge

        entity can be any handleref instance or a User instance
        """

        return OrganizationMergeEntity.objects.create(
            merge=self, entity=entity, note=note
        )

    def undo(self):
        """
        Undo this merge
        """

        # undelete original org
        self.from_org.status = "ok"
        self.from_org.save()

        for row in self.entities.all():
            entity = row.entity
            tag = getattr(entity, "ref_tag", None)
            if tag:
                # move handleref entity
                entity.org = self.from_org
                entity.save()
            else:
                # move user entity
                group = getattr(self.from_org, row.note)
                group.user_set.add(entity)

                self.to_org.usergroup.user_set.remove(entity)
                self.to_org.admin_usergroup.user_set.remove(entity)

        self.delete()


class OrganizationMergeEntity(models.Model):
    """
    This holds the entities moved during an
    organization merge stored in OrganizationMerge
    """

    merge = models.ForeignKey(
        OrganizationMerge, on_delete=models.CASCADE, related_name="entities"
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    entity = GenericForeignKey("content_type", "object_id")
    note = models.CharField(max_length=32, blank=True, null=True)

    class Meta:
        db_table = "peeringdb_organization_merge_entity"
        verbose_name = _("Organization Merge: Entity")
        verbose_name_plural = _("Organization Merge: Entities")


@reversion.register
class Facility(ProtectedMixin, pdb_models.FacilityBase, GeocodeBaseMixin):
    """
    Describes a peeringdb facility
    """

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="fac_set"
    )

    # FIXME: delete cascade needs to be fixed in django-peeringdb, can remove
    # this afterwards
    class HandleRef:
        tag = "fac"
        delete_cascade = ["ixfac_set", "netfac_set"]

    class Meta(pdb_models.FacilityBase.Meta):
        pass

    @staticmethod
    def autocomplete_search_fields():
        """
        Returns a tuple of field query strings to be used during quick search
        query
        """
        return (
            "id__iexact",
            "name__icontains",
        )

    @classmethod
    def nsp_namespace_in_list(cls):
        """
        Returns the permissioning namespace when a facility
        is contained in list
        """
        return str(cls.id)

    @classmethod
    def nsp_namespace_from_id(cls, org_id, fac_id):
        return "%s.facility.%s" % (Organization.nsp_namespace_from_id(org_id), fac_id)

    @classmethod
    def related_to_net(cls, value=None, filt=None, field="network_id", qset=None):
        """
        Returns queryset of Facility objects that
        are related to the network specified via net_id

        Relationship through netfac -> net
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)

        q = NetworkFacility.handleref.filter(**filt)
        return qset.filter(id__in=[i.facility_id for i in q])

    @classmethod
    def related_to_ix(cls, value=None, filt=None, field="ix_id", qset=None):
        """
        Returns queryset of Facility objects that
        are related to the ixwork specified via ix_id

        Relationship through ixfac -> ix
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)

        q = InternetExchangeFacility.handleref.filter(**filt)
        return qset.filter(id__in=[i.facility_id for i in q])

    @classmethod
    def overlapping_asns(cls, asns, qset=None):
        """
        Returns queryset of Facility objects
        that have a relationship to all asns specified in `asns`

        Relationship through netfac

        Arguments:
            - asns <list>: list of asns

        Keyword Arguments:
            - qset <Facility QuerySet>: if specified use as base query

        Returns:
            - Facility QuerySet
        """

        facilities = {}
        shared_facilities = []
        count = len(asns)

        if count == 1:
            raise ValidationError(_("Need to specify at least two asns"))

        if count > 25:
            raise ValidationError(_("Can only compare a maximum of 25 asns"))

        # fist we need to collect all active facilities related to any
        # of the specified asns
        for asn in asns:
            for netfac in NetworkFacility.objects.filter(
                network__asn=asn, status="ok"
            ).select_related("network"):
                if netfac.facility_id not in facilities:
                    facilities[netfac.facility_id] = {}
                facilities[netfac.facility_id][asn] = True

        # then we check for the facilities that have all of the asns
        # peering by comparing the counts of collected asns at each
        # facility with the count of asns provided
        for fac_id, collected_asns in list(facilities.items()):
            if len(list(collected_asns.keys())) == count:
                shared_facilities.append(fac_id)

        if not qset:
            qset = cls.handleref.undeleted()

        return qset.filter(id__in=shared_facilities)

    @property
    def nsp_namespace(self):
        """
        Returns permissioning namespace for this facility
        """
        return self.__class__.nsp_namespace_from_id(self.org_id, self.id)

    @property
    def sponsorship(self):
        """
        Returns sponsorship oject for this facility (through the owning org)
        """
        return self.org.sponsorship

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity
        """
        return self.name

    @property
    def netfac_set_active(self):
        """
        Returns queryset of active NetworkFacility ojects connected to this
        facility
        """
        return self.netfac_set.filter(status="ok")

    @property
    def ixfac_set_active(self):
        """
        Returns queryset of active InternetExchangeFacility objects connected
        to this facility
        """
        return self.ixfac_set.filter(status="ok")

    @property
    def net_count(self):
        """
        Returns number of Networks at this facility
        """
        return self.netfac_set_active.count()

    @property
    def view_url(self):
        """
        Return the URL to this facility's web view
        """
        return "{}{}".format(
            settings.BASE_URL, django.urls.reverse("fac-view", args=(self.id,))
        )

    @property
    def deletable(self):
        """
        Returns whether or not the facility is currently
        in a state where it can be marked as deleted.

        This will be False for facilites of which ANY
        of the following is True:

        - has a network facility under it with status=ok
        - has an exchange facility under it with status=ok
        """

        if self.ixfac_set_active.exists():
            self._not_deletable_reason = _(
                "Facility has active Exchange -> Facility connection"
            )
            return False
        elif self.netfac_set_active.exists():
            self._not_deletable_reason = _(
                "Facility has active Network -> Facility connection"
            )
            return False
        else:
            self._not_deletable_reason = None
            return True


    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["org"])

    def validate_phonenumbers(self):
        self.tech_phone = validate_phonenumber(self.tech_phone, self.country.code)
        self.sales_phone = validate_phonenumber(self.sales_phone, self.country.code)



@reversion.register
class InternetExchange(ProtectedMixin, pdb_models.InternetExchangeBase):
    """
    Describes a peeringdb exchange
    """

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="ix_set"
    )

    @staticmethod
    def autocomplete_search_fields():
        """
        Returns a tuple of field query strings to be used during quick search
        query
        """
        return (
            "id__iexact",
            "name__icontains",
        )

    def __unicode__(self):
        return self.name

    @classmethod
    def related_to_ixlan(cls, value=None, filt=None, field="ixlan_id", qset=None):
        """
        Returns queryset of InternetExchange objects that
        are related to IXLan specified by ixlan_id

        Relationship through ixlan
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value, prefix="ixlan")

        q = IXLan.handleref.filter(**filt)
        return qset.filter(id__in=[ix.ix_id for ix in q])

    @classmethod
    def related_to_ixfac(cls, value=None, filt=None, field="ixfac_id", qset=None):
        """
        Returns queryset of InternetExchange objects that
        are related to IXfac link specified by ixfac_id

        Relationship through ixfac
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value, prefix="ixfac")

        q = InternetExchangeFacility.handleref.filter(**filt)
        return qset.filter(id__in=[ix.ix_id for ix in q])

    @classmethod
    def related_to_fac(cls, filt=None, value=None, field="facility_id", qset=None):
        """
        Returns queryset of InternetExchange objects that
        are related to the facility specified by fac_id

        Relationship through ixfac -> fac
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)
        q = InternetExchangeFacility.handleref.filter(**filt)
        return qset.filter(id__in=[ix.ix_id for ix in q])

    @classmethod
    def related_to_net(cls, filt=None, value=None, field="network_id", qset=None):
        """
        Returns queryset of InternetExchange objects that
        are related to the network specified by network_id

        Relationship through netixlan -> ixlan
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)
        q = NetworkIXLan.handleref.filter(**filt).select_related("ixlan")
        return qset.filter(id__in=[nx.ixlan.ix_id for nx in q])

    @classmethod
    def related_to_ipblock(cls, ipblock, qset=None):
        """
        Returns queryset of InternetExchange objects that
        have ixlan prefixes matching the ipblock specified

        Relationship  through ixlan -> ixpfx
        """

        if not qset:
            qset = cls.handleref.undeleted()

        q = IXLanPrefix.objects.select_related("ixlan").filter(
            prefix__startswith=ipblock
        )

        return qset.filter(id__in=[pfx.ixlan.ix_id for pfx in q])

    @classmethod
    def overlapping_asns(cls, asns, qset=None):
        """
        Returns queryset of InternetExchange objects
        that have a relationship to all asns specified in `asns`

        Relationship through ixlan -> netixlan

        Arguments:
            - asns <list>: list of asns

        Keyword Arguments:
            - qset <InternetExchange QuerySet>: if specified use as base query

        Returns:
            - InternetExchange QuerySet
        """

        exchanges = {}
        shared_exchanges = []
        count = len(asns)

        if count == 1:
            raise ValidationError(_("Need to specify at least two asns"))

        if count > 25:
            raise ValidationError(_("Can only compare a maximum of 25 asns"))

        # fist we need to collect all active exchanges related to any
        # of the specified asns
        for asn in asns:
            for netixlan in NetworkIXLan.objects.filter(
                network__asn=asn, status="ok"
            ).select_related("network", "ixlan"):
                if netixlan.ixlan.ix_id not in exchanges:
                    exchanges[netixlan.ixlan.ix_id] = {}
                exchanges[netixlan.ixlan.ix_id][asn] = True

        # then we check for the exchanges that have all of the asns
        # peering by comparing the counts of collected asns at each
        # exchange with the count of asns provided
        for ix_id, collected_asns in list(exchanges.items()):
            if len(list(collected_asns.keys())) == count:
                shared_exchanges.append(ix_id)

        if not qset:
            qset = cls.handleref.undeleted()

        return qset.filter(id__in=shared_exchanges)

    @classmethod
    def filter_net_count(cls, filt=None, value=None, qset=None):

        """
        Filter ix queryset by network count value

        Keyword Arguments:
            - filt<str>: filter to apply: None, 'lt', 'gt', 'lte', 'gte'
            - value<int>: value to filter by
            - qset

        Returns:
            InternetExchange queryset
        """

        if not qset:
            qset = cls.objects.filter(status="ok")

        value = int(value)

        if filt == "lt":
            exchanges = [ix.id for ix in qset if ix.network_count < value]
        elif filt == "gt":
            exchanges = [ix.id for ix in qset if ix.network_count > value]
        elif filt == "gte":
            exchanges = [ix.id for ix in qset if ix.network_count >= value]
        elif filt == "lte":
            exchanges = [ix.id for ix in qset if ix.network_count <= value]
        else:
            exchanges = [ix.id for ix in qset if ix.network_count == value]

        return qset.filter(pk__in=exchanges)

    @classmethod
    def nsp_namespace_in_list(cls):
        return str(cls.id)

    @classmethod
    def nsp_namespace_from_id(cls, org_id, ix_id):
        """
        Returns permissioning namespace for an exchange
        """
        return "%s.internetexchange.%s" % (
            Organization.nsp_namespace_from_id(org_id),
            ix_id,
        )

    @property
    def ixlan(self):
        """
        Returns the ixlan for this exchange

        As per #21 each exchange will get one ixlan with a matching
        id, but the schema is to remain unchanged until a major
        version bump.
        """
        return self.ixlan_set.first()

    @property
    def networks(self):
        """
        Returns all active networks at this exchange
        """
        networks = []
        for ixlan in self.ixlan_set_active:
            for netixlan in ixlan.netixlan_set_active:
                networks.append(netixlan.network_id)
        return list(set(networks))

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity
        """
        return self.name

    @property
    def network_count(self):
        """
        Returns count of networks at this exchange
        """
        qset = NetworkIXLan.objects.filter(ixlan__ix_id=self.id, status="ok")
        qset = qset.values("network_id").annotate(count=models.Count("network_id"))
        return len(qset)

    @property
    def ixlan_set_active(self):
        """
        Returns queryset of active ixlan objects at this exchange
        """
        return self.ixlan_set(manager="handleref").filter(status="ok")

    @property
    def ixlan_set_active_or_pending(self):
        """
        Returns queryset of active or pending ixlan objects at
        this exchange
        """
        return self.ixlan_set(manager="handleref").filter(status__in=["ok", "pending"])

    @property
    def ixfac_set_active(self):
        """
        Returns queryset of active ixfac objects at this exchange
        """
        return (
            self.ixfac_set(manager="handleref")
            .select_related("facility")
            .filter(status="ok")
        )

    @property
    def nsp_namespace(self):
        """
        Returns permissioning namespace for this exchange
        """
        return self.__class__.nsp_namespace_from_id(self.org_id, self.id)

    @property
    def sponsorship(self):
        """
        Returns sponsorship object for this exchange (through owning org)
        """
        return self.org.sponsorship

    @property
    def view_url(self):
        """
        Return the URL to this facility's web view
        """
        return "{}{}".format(
            settings.BASE_URL, django.urls.reverse("ix-view", args=(self.id,))
        )


    @property
    def deletable(self):
        """
        Returns whether or not the exchange is currently
        in a state where it can be marked as deleted.

        This will be False for exchanges of which ANY
        of the following is True:

        - has netixlans connected to it
        """

        if self.network_count > 0:
            self._not_deletable_reason = _(
                "Exchange has active Exchange -> Network connection"
            )
            return False
        else:
            self._not_deletable_reason = None
            return True




    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["org"])

    def vq_approve(self):
        """
        Called when internet exchange is approved in verification
        queue
        """

        # since we are creating a pending ixland and prefix
        # during exchange creation, we need to make sure those
        # get approved as well when the exchange gets approved
        for ixlan in self.ixlan_set.filter(status="pending"):
            ixlan.status = "ok"
            ixlan.save()
            for ixpfx in ixlan.ixpfx_set.filter(status="pending"):
                ixpfx.status = "ok"
                ixpfx.save()

    def save(self, create_ixlan=True, **kwargs):
        """
        When an internet exchange is saved, make sure the ixlan for it
        exists

        Keyword Argument(s):

        - create_ixlan (`bool`=True): if True and the ix is missing
          it's ixlan, create it
        """
        r = super(InternetExchange, self).save(**kwargs)

        if not self.ixlan and create_ixlan:
            ixlan = IXLan(ix=self, status=self.status, mtu=0)

            # ixlan id will be set to match ix id in ixlan's clean()
            # call
            ixlan.clean()

            ixlan.save()

        return r

    def validate_phonenumbers(self):
        self.tech_phone = validate_phonenumber(self.tech_phone, self.country.code)
        self.policy_phone = validate_phonenumber(self.policy_phone, self.country.code)

    def clean(self):
        self.validate_phonenumbers()


@reversion.register
class InternetExchangeFacility(pdb_models.InternetExchangeFacilityBase):
    """
    Describes facility to exchange relationship
    """

    ix = models.ForeignKey(
        InternetExchange, on_delete=models.CASCADE, related_name="ixfac_set"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, default=0, related_name="ixfac_set"
    )

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the ixfac for logging purposes
        """
        return "ixfac{} {} <-> {}".format(self.id, self.ix.name, self.facility.name)

    @classmethod
    def nsp_namespace_from_id(cls, org_id, ix_id, id):
        """
        Returns permissioning namespace for an ixfac
        """
        return "%s.fac.%s" % (InternetExchange.nsp_namespace_from_id(org_id, ix_id), id)

    @property
    def nsp_namespace(self):
        """
        Returns permissioning namespace for this ixfac
        """
        return self.__class__.nsp_namespace_from_id(self.ix.org_id, self.ix.id, self.id)

    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["ix"])

    class Meta:
        unique_together = ("ix", "facility")
        db_table = "peeringdb_ix_facility"


@reversion.register
class IXLan(pdb_models.IXLanBase):
    """
    Describes a LAN at an exchange
    """

    # as we are preparing to drop IXLans from the schema, as an interim
    # step (#21) we are giving each ix one ixlan with matching ids, so we need
    # to have an id field that doesnt automatically increment
    id = models.IntegerField(primary_key=True)

    ix = models.ForeignKey(
        InternetExchange, on_delete=models.CASCADE, default=0, related_name="ixlan_set"
    )

    # IX-F import fields

    ixf_ixp_member_list_url = models.URLField(null=True, blank=True)
    ixf_ixp_import_enabled = models.BooleanField(default=False)
    ixf_ixp_import_error = models.TextField(
        _("IX-F error"),
        blank=True,
        null=True,
        help_text=_("Reason IX-F data could not be parsed")
    )
    ixf_ixp_import_error_notified = models.DateTimeField(
        _("IX-F error notification date"),
        help_text=_("Last time we notified the exchange about the IX-F parsing issue"),
        null=True,
        blank=True,
    )

    # FIXME: delete cascade needs to be fixed in django-peeringdb, can remove
    # this afterwards
    class HandleRef:
        tag = "ixlan"
        delete_cascade = ["ixpfx_set", "netixlan_set"]

    class Meta:
        db_table = "peeringdb_ixlan"

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the ixlan for logging purposes
        """
        return "ixlan{} {}".format(self.id, self.ix.name)

    @classmethod
    def nsp_namespace_from_id(cls, org_id, ix_id, id):
        """
        Returns permissioning namespace for an ixlan
        """
        return "%s.ixlan.%s" % (
            InternetExchange.nsp_namespace_from_id(org_id, ix_id),
            id,
        )

    @property
    def nsp_namespace(self):
        """
        Returns permissioning namespace for this ixlan
        """
        return self.__class__.nsp_namespace_from_id(self.ix.org_id, self.ix_id, self.id)

    @property
    def ixpfx_set_active(self):
        """
        Returns queryset of active prefixes at this ixlan
        """
        return self.ixpfx_set(manager="handleref").filter(status="ok")

    @property
    def ixpfx_set_active_or_pending(self):
        """
        Returns queryset of active or pending prefixes at this ixlan
        """
        return self.ixpfx_set(manager="handleref").filter(status__in=["ok", "pending"])

    @property
    def netixlan_set_active(self):
        """
        Returns queryset of active netixlan objects at this ixlan
        """
        return (
            self.netixlan_set(manager="handleref")
            .select_related("network")
            .filter(status="ok")
        )
        # q = NetworkIXLan.handleref.filter(ixlan_id=self.id).filter(status="ok")
        # return Network.handleref.filter(id__in=[i.network_id for i in
        # q]).filter(status="ok")

    @staticmethod
    def autocomplete_search_fields():
        """
        Used by grappelli autocomplete to determine what
        fields to search in
        """
        return ("ix__name__icontains",)


    def related_label(self):
        """
        Used by grappelli autocomplete for representation
        """
        return "{} IXLan ({})".format(self.ix.name, self.id)


    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["ix"])

    def test_ipv4_address(self, ipv4):
        """
        test that the ipv4 address exists in one of the prefixes in this ixlan
        """
        for pfx in self.ixpfx_set_active:
            if pfx.test_ip_address(ipv4):
                return True
        return False

    def test_ipv6_address(self, ipv6):
        """
        test that the ipv6 address exists in one of the prefixes in this ixlan
        """
        for pfx in self.ixpfx_set_active:
            if pfx.test_ip_address(ipv6):
                return True
        return False

    def clean(self):
        # id is set and does not match the parent ix id

        if self.id and self.id != self.ix.id:
            raise ValidationError({"id": _("IXLan id needs to match parent ix id")})

        # id is not set (new ixlan)

        if not self.id:

            # ixlan for ix already exists

            if self.ix.ixlan:
                raise ValidationError(_("Ixlan for exchange already exists"))

        # enforce correct id moving forward

        self.id = self.ix.id

        return super(IXLan, self).clean()

    @reversion.create_revision()
    def add_netixlan(self, netixlan_info, save=True, save_others=True):
        """
        This function allows for sane adding of netixlan object under
        this ixlan.

        It will take into account whether an ipaddress can be claimed from a
        soft-deleted netixlan or whether or not an object already exists
        that should be updated instead of creating a new netixlan instance.

        Arguments:
            - netixlan_info (NetworkIXLan): a netixlan instance describe the netixlan
                you want to add to this ixlan. Note that this instance will actually
                not be saved. It only serves as an information provider.

        Keyword Arguments:
            - save (bool): if true commit changes to db

        Returns:
            - {netixlan, created, changed, log}
        """

        log = []
        changed = []
        created = False
        ipv4 = netixlan_info.ipaddr4
        ipv6 = netixlan_info.ipaddr6
        asn = netixlan_info.asn
        ipv4_valid = False
        ipv6_valid = False

        def result(netixlan=None):
            return {
                "netixlan": netixlan,
                "created": created,
                "changed": changed,
                "log": log,
            }

        # check if either of the provided ip addresses are a fit for ANY of
        # the prefixes in this ixlan
        for pfx in self.ixpfx_set_active:
            if pfx.test_ip_address(ipv4):
                ipv4_valid = True
            if pfx.test_ip_address(ipv6):
                ipv6_valid = True

        # If neither ipv4 nor ipv6 match any of the prefixes, log the issue
        # and bail
        if (ipv4 and not ipv4_valid):
            raise ValidationError(
                f"IPv4 {ipv4} does not match any prefix "
                "on this ixlan"
            )
        if (ipv6 and not ipv6_valid):
            raise ValidationError(
                f"IPv6 {ipv6} does not match any prefix "
                "on this ixlan"
            )


        # Next we check if an active netixlan with the ipaddress exists in ANOTHER lan, and bail
        # if it does.
        if (
            ipv4
            and NetworkIXLan.objects.filter(status="ok", ipaddr4=ipv4)
            .exclude(ixlan=self)
            .count()
            > 0
        ):
            raise ValidationError(f"Ip address {ipv4} already exists in another lan")

        if (
            ipv6
            and NetworkIXLan.objects.filter(status="ok", ipaddr6=ipv6)
            .exclude(ixlan=self)
            .count()
            > 0
        ):
            raise ValidationError(f"Ip address {ipv6} already exists in another lan")

        # now we need to figure out if the ipaddresses already exist in this ixlan,
        # we need to check ipv4 and ipv6 separately as they might exist on different
        # netixlan objects.
        try:
            if ipv4:
                netixlan_existing_v4 = NetworkIXLan.objects.get(
                    ixlan=self, ipaddr4=ipv4
                )
            else:
                netixlan_existing_v4 = None
        except NetworkIXLan.DoesNotExist:
            netixlan_existing_v4 = None

        try:
            if ipv6:
                netixlan_existing_v6 = NetworkIXLan.objects.get(
                    ixlan=self, ipaddr6=ipv6
                )
            else:
                netixlan_existing_v6 = None
        except NetworkIXLan.DoesNotExist:
            netixlan_existing_v6 = None

        # once we have that information we determine which netixlan object to use
        if netixlan_existing_v4 and netixlan_existing_v6:
            # both ips already exist
            if netixlan_existing_v4 != netixlan_existing_v6:
                # but they exist on different netixlans, so we reset the v6 netixlan
                netixlan_existing_v6.ipaddr6 = None
                if save:
                    netixlan_existing_v6.save()
            # we use the existing v4 netixlan
            netixlan = netixlan_existing_v4
        elif netixlan_existing_v4:
            # the v4 address exsits, but v6 doesnt so we use the netixlan with the v4 match
            netixlan = netixlan_existing_v4
        elif netixlan_existing_v6:
            # the v6 address exists, but v4 does not so we use the netixlan with the v6 match
            netixlan = netixlan_existing_v6
        else:
            # neither address exists, create a new netixlan object
            netixlan = NetworkIXLan(
                ixlan=self, network=netixlan_info.network, status="ok"
            )
            created = True
            reason = "New ip-address"

        # now we sync the data to our determined netixlan instance

        # IPv4
        if ipv4 != netixlan.ipaddr4:

            # we need to check if this ipaddress exists on a
            # soft-deleted netixlan elsewhere, and
            # reset if so.

            for other in NetworkIXLan.objects.filter(
                ipaddr4=ipv4, status="deleted"
            ).exclude(asn=asn):
                other.ipaddr4 = None
                other.notes = f"Ip address {ipv4} was claimed by other netixlan"
                if save or save_others:
                    other.save()

            netixlan.ipaddr4 = ipv4
            changed.append("ipaddr4")

        # IPv6
        if ipv6 != netixlan.ipaddr6:

            # we need to check if this ipaddress exists on a
            # soft-deleted netixlan elsewhere, and
            # reset if so.

            for other in NetworkIXLan.objects.filter(
                ipaddr6=ipv6, status="deleted"
            ).exclude(asn=asn):
                other.ipaddr6 = None
                other.notes = f"Ip address {ipv6} was claimed by other netixlan"
                if save or save_others:
                   other.save()

            netixlan.ipaddr6 = ipv6
            changed.append("ipaddr6")

        # Is the netixlan a routeserver ?
        if netixlan_info.is_rs_peer != netixlan.is_rs_peer:
            netixlan.is_rs_peer = netixlan_info.is_rs_peer
            changed.append("is_rs_peer")

        # Speed
        if netixlan_info.speed != netixlan.speed and (
            netixlan_info.speed > 0 or netixlan.speed is None
        ):
            netixlan.speed = netixlan_info.speed
            changed.append("speed")

        # ASN
        if netixlan_info.asn != netixlan.asn:
            netixlan.asn = netixlan_info.asn
            changed.append("asn")

        # Network
        if netixlan_info.network.id != netixlan.network.id:
            netixlan.network = netixlan_info.network
            changed.append("network_id")

        # Finally we attempt to validate the data and then save the netixlan instance
        netixlan.full_clean()

        if save and changed:
            netixlan.status = "ok"
            netixlan.save()

        return result(netixlan)


class IXLanIXFMemberImportAttempt(models.Model):
    """
    Holds information about the most recent ixf member import
    attempt for an ixlan
    """

    ixlan = models.OneToOneField(
        IXLan,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="ixf_import_attempt",
    )
    updated = models.DateTimeField(auto_now=True)
    info = models.TextField(null=True, blank=True)


class IXLanIXFMemberImportLog(models.Model):
    """
    Import log of a IXF member import that changed or added at least one
    netixlan under the specified ixlans
    """

    ixlan = models.ForeignKey(
        IXLan, on_delete=models.CASCADE, related_name="ixf_import_log_set"
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta(object):
        verbose_name = _("IXF Import Log")
        verbose_name_plural = _("IXF Import Logs")

    @reversion.create_revision()
    def rollback(self):
        """
        Attempt to rollback the changes described in this log
        """

        for entry in self.entries.all():
            if entry.rollback_status() == 0:
                if entry.version_before:
                    entry.version_before.revert()
                elif entry.netixlan.status == "ok":
                    entry.netixlan.delete()


class IXLanIXFMemberImportLogEntry(models.Model):
    """
    IXF member import log entry that holds the affected netixlan and
    the netixlan's version after the change, which can be used to rollback
    the change
    """

    log = models.ForeignKey(
        IXLanIXFMemberImportLog, on_delete=models.CASCADE, related_name="entries"
    )
    netixlan = models.ForeignKey(
        "peeringdb_server.NetworkIXLan",
        on_delete=models.CASCADE,
        related_name="ixf_import_log_entries",
    )
    version_before = models.ForeignKey(
        reversion.models.Version,
        on_delete=models.CASCADE,
        null=True,
        related_name="ixf_import_log_before",
    )
    version_after = models.ForeignKey(
        reversion.models.Version,
        on_delete=models.CASCADE,
        related_name="ixf_import_log_after",
    )
    action = models.CharField(max_length=255, null=True, blank=True)
    reason = models.CharField(max_length=255, null=True, blank=True)

    class Meta(object):
        verbose_name = _("IXF Import Log Entry")
        verbose_name_plural = _("IXF Import Log Entries")



    @property
    def changes(self):
        """
        Returns a dict of changes between the netixlan version
        saved by the ix-f import and the version before

        Fields `created`, `updated` and `version` will be ignored
        """
        if not self.version_before:
            return {}
        data_before = self.version_before.field_dict
        data_after = self.version_after.field_dict
        rv = {}
        for k, v in list(data_after.items()):
            if k in ["created", "updated", "version"]:
                continue
            v2 = data_before.get(k)
            if v != v2:
                if isinstance(v, ipaddress.IPv4Address) or isinstance(
                    v, ipaddress.IPv6Address
                ):
                    rv[k] = str(v)
                else:
                    rv[k] = v

        return rv

    def rollback_status(self):
        recent_version = reversion.models.Version.objects.get_for_object(
            self.netixlan
        ).first()
        if self.version_after == recent_version:
            if self.netixlan.status == "deleted":
                conflict_v4, conflict_v6 = self.netixlan.ipaddress_conflict()
                if conflict_v4 or conflict_v6:
                    return 2
            return 0
        elif self.version_before == recent_version:
            return -1
        return 1


class IXFMemberData(pdb_models.NetworkIXLanBase):

    """
    Describes a potential data update that arose during an ix-f import
    attempt for a specific member (asn, ip4, ip6) to netixlan
    (asn, ip4, ip6) where the importer could not complete the
    update automatically.
    """

    data = models.TextField(
        null=False, default="{}",
        help_text=_(
            "JSON snapshot of the ix-f member data that " \
            "created this entry"
        )
    )

    log = models.TextField(blank=True, help_text=_(
        "Activity for this entry"
    ))

    dismissed = models.BooleanField(default=False, help_text=_(
        "Network's dismissal of this proposed change, which will hide it until" \
        " from the customer facing network view"
    ))

    error = models.TextField(null=True, blank=True, help_text=_(
        "Trying to apply data to peeringdb raised an issue"
    ))
    reason = models.CharField(max_length=255, default="")

    fetched = models.DateTimeField(
        _("Last Fetched"),
    )

    ixlan = models.ForeignKey(
        IXLan,
        related_name="ixf_set",
        on_delete=models.CASCADE
    )

    # field names of fields that can receive
    # modifications from ix-f

    data_fields = [
        "speed",
        "operational",
        "is_rs_peer",
    ]

    class Meta:
        db_table = "peeringdb_ixf_member_data"
        verbose_name = _("IXF Member Data")
        verbose_name_plural = _("IXF Member Data")

    class HandleRef:
        tag = "ixfmember"

    @classmethod
    def id_filters(cls, asn, ipaddr4, ipaddr6):
        """
        returns a dict of filters to use with a
        IXFMemberData or NetworkIXLan query set
        to retrieve a unique entry
        """

        filters = {"asn": asn}

        if ipaddr4 is None:
            filters["ipaddr4__isnull"] = True
        else:
            filters["ipaddr4"] = ipaddr4


        if ipaddr6 is None:
            filters["ipaddr6__isnull"] = True
        else:
            filters["ipaddr6"] = ipaddr6

        return filters


    @classmethod
    def instantiate(cls, asn, ipaddr4, ipaddr6, ixlan, **kwargs):
        """
        Returns an IXFMemberData object.

        It will take into consideration whether or not an instance
        for this object already exists (as identified by asn and ip
        addresses)

        It will also update the value of `fetched` to now

        Keyword Argument(s):

        - speed(int=0) : network speed (mbit)
        - operational(bool=True): peer is operational
        - is_rs_peer(bool=False): peer is route server
        """

        fetched = datetime.datetime.now().replace(tzinfo=UTC())

        try:
            instance = cls.objects.get(**cls.id_filters(asn, ipaddr4, ipaddr6))
            for field in cls.data_fields:
                setattr(instance, f"previous_{field}", getattr(instance,field))

            instance.previous_data = instance.data

            instance.fetched = fetched
            instance._meta.get_field("updated").auto_now = False
            instance.save()
            instance._meta.get_field("updated").auto_now = True

        except cls.DoesNotExist:
            instance = cls(asn=asn, ipaddr4=ipaddr4, ipaddr6=ipaddr6, status="ok")


        instance.speed = kwargs.get("speed", 0)
        instance.operational = kwargs.get("operational", True)
        instance.is_rs_peer = kwargs.get("is_rs_peer", False)
        instance.ixlan = ixlan
        instance.fetched = fetched

        if "data" in kwargs:
            instance.set_data(kwargs.get("data"))

        return instance


    @classmethod
    def get_for_network(cls, net):
        """
        Returns aueryset for IXFMemberData objects that match
        a network's asn

        Argument(s):

        - net(Network)
        """
        return cls.objects.filter(asn = net.asn)


    @classmethod
    def dismissed_for_network(cls, net):
        """
        Returns queryset for IXFMemberData objects that match
        a network's asn and are currenlty flagged as dismissed

        Argument(s):

        - net(Network)
        """
        qset = cls.get_for_network(net).select_related("ixlan", "ixlan__ix")
        qset = qset.filter(dismissed=True)

        dismissed = {}

        for ixf_member_data in qset:

            ix = ixf_member_data.ix
            if ix.id not in dismissed:
                dismissed[ix.id] = ix

        return dismissed


    @classmethod
    def proposals_for_network(cls, net):
        """
        Returns a dict containing actionable proposals for
        a network

        ```
        {
          <ix_id>: {
            "ix": InternetExchange,
            "add" : list(IXFMemberData),
            "modify" : list(IXFMemberData),
            "delete" : list(IXFMemberData),
          }
        }
        ```

        Argument(s):

        - net(Network)
        """

        qset = cls.get_for_network(net).select_related("ixlan", "ixlan__ix")

        proposals = {}

        for ixf_member_data in qset:

            action = ixf_member_data.action
            error = ixf_member_data.error

            if action == "noop":
                continue

            if not ixf_member_data.actionable_for_network:
                continue

            if ixf_member_data.dismissed:
                continue


            ix_id = ixf_member_data.ix.id

            if ix_id not in proposals:
                proposals[ix_id] = {
                    "ix": ixf_member_data.ix,
                    "add": [],
                    "delete": [],
                    "modify": [],
                }

            proposals[ix_id][action].append(ixf_member_data)

        return proposals

    @property
    def json(self):
        """
        Returns dict for self.data
        """
        return json.loads(self.data)


    @property
    def net(self):
        """
        Returns the Network instance related to
        this entry
        """

        if not hasattr(self, "_net"):
            self._net = Network.objects.get(asn=self.asn)
        return self._net

    @property
    def actionable_for_network(self):
        """
        Returns whether or not the proposed action by
        this IXFMemberData instance is actionable by
        the network
        """
        error = self.error

        if error and "address outside of prefix" in error:
            return False

        return True


    @property
    def net_contacts(self):
        """
        Returns a list of email addresses that
        are suitable contact points for conflict resolution
        at the network's end
        """
        qset = self.net.poc_set_active.exclude(email="")
        qset = qset.exclude(email__isnull=True)

        role_priority = ["Policy", "Technical", "NOC", "Maintenance"]

        contacts = []

        for role in role_priority:
            for poc in qset.filter(role=role):
                contacts.append(poc.email)
            if contacts:
                break

        return list(set(contacts))


    @property
    def ix_contacts(self):
        """
        Returns a list of email addresses that
        are suitable contact points for conflict resolution
        at the exchange end
        """
        return [self.ix.tech_email or self.ix.policy_email]


    @property
    def ix(self):
        """
        Returns the InternetExchange instance related to
        this entry
        """

        if not hasattr(self, "_ix"):
            self._ix = self.ixlan.ix
        return self._ix


    @property
    def ixf_id(self):

        """
        Returns a tuple that identifies the ix-f member
        as a unqiue record by asn, ip4 and ip6 address
        """

        return (self.asn, self.ipaddr4, self.ipaddr6)

    @property
    def ixf_id_pretty_str(self):
        ipaddr4 = self.ipaddr4 or _("IPv4 not set")
        ipaddr6 = self.ipaddr6 or _("IPv6 not set")

        return f"AS{self.asn} - {ipaddr4} - {ipaddr6}"

    @property
    def changes(self):

        """
        Returns a dict of changes (field, value)
        between this entry and the related netixlan

        If an empty dict is returned that means no changes

        ```
        {
            <field_name> : {
                "from" : <value>,
                "to : <value>
            }
        }
        ```
        """

        netixlan = self.netixlan
        changes = {}

        if self.marked_for_removal:
            return changes

        if netixlan.is_rs_peer != self.is_rs_peer:
            changes.update(
                is_rs_peer = {
                    "from": netixlan.is_rs_peer,
                    "to": self.is_rs_peer
                }
            )

        if netixlan.speed != self.speed:
            changes.update(
                speed = {"from":netixlan.speed, "to": self.speed}
            )

        if netixlan.operational != self.operational:
            changes.update(
                operational = {
                    "from": netixlan.operational,
                    "to": self.operational
                }
            )

        if netixlan.status != self.status:
            changes.update(
                status = {"from": netixlan.status, "to": self.status}
            )

        return changes

    @property
    def changed_fields(self):
        """
        Returns a comma separated string of field names
        for changes proposed by this IXFMemberData instance
        """
        return ", ".join(list(self.changes.keys()))

    @property
    def remote_changes(self):
        """
        Returns a dict of changed fields between previously
        fetched IX-F data and current IX-F data

        If an empty dict is returned that means no changes

        ```
        {
            <field_name> : {
                "from" : <value>,
                "to : <value>
            }
        }
        ```
        """
        if not self.id and self.netixlan.id:
            return {}

        changes = {}

        for field in self.data_fields:
            old_v = getattr(self, f"previous_{field}", None)
            v = getattr(self, field)
            if old_v is not None and v != old_v:
                changes[field] = {"from": old_v, "to": v}

        return changes

    @property
    def remote_data_missing(self):
        """
        Returns whether or not this IXFMemberData entry
        had data at the IX-F source.

        If not it indicates that it does not exist at the
        ix-f source
        """

        return (self.data == "{}" or not self.data)

    @property
    def marked_for_removal(self):
        """
        Returns whether or not this entry implies that
        the related netixlan should be removed.

        We do this by checking if the ix-f data was provided
        or not
        """

        if not self.netixlan.id or self.netixlan.status == "deleted":

            # edge-case that should not really happen
            # non-existing netixlan cannot be removed

            return False

        return self.remote_data_missing

    @property
    def net_present_at_ix(self):
        """
        Returns whether or not the network associated with
        this IXFMemberData instance currently has a presence
        at the exchange associated with this IXFMemberData
        instance
        """
        return NetworkIXLan.objects.filter(
            ixlan=self.ixlan,
            network=self.net,
            status="ok"
        ).exists()


    @property
    def action(self):
        """
        Returns the implied action of applying this
        entry to peeringdb

        Will return either "add", "modify", "delete" or "noop"
        """

        has_data = (self.remote_data_missing == False)

        if has_data:
            if not self.netixlan.id:
                return "add"

            if self.status == "ok" and self.netixlan.status == "deleted":
                return "add"

            if self.changes:
                return "modify"
        else:
            if self.marked_for_removal:
                return "delete"

        return "noop"

    @property
    def netixlan(self):

        """
        Will either return a matching existing netixlan
        instance (asn,ip4,ip6) or a new netixlan if
        a matching netixlan does not currently exist.

        Any new netixlan will NOT be saved at this point.

        Note that the netixlan that matched may be currently
        soft-deleted (status=="deleted")
        """

        if not hasattr(self, "_netixlan"):
            try:

                filters = {"asn": self.asn}

                if self.ipaddr4 is None:
                    filters["ipaddr4__isnull"] = True
                else:
                    filters["ipaddr4"] = self.ipaddr4


                if self.ipaddr6 is None:
                    filters["ipaddr6__isnull"] = True
                else:
                    filters["ipaddr6"] = self.ipaddr6

                self._netixlan = NetworkIXLan.objects.get(**filters)
            except NetworkIXLan.DoesNotExist:
                self._netixlan = NetworkIXLan(
                    ipaddr4 = self.ipaddr4,
                    ipaddr6 = self.ipaddr6,
                    speed = self.speed,
                    asn = self.asn,
                    operational = self.operational,
                    is_rs_peer = self.is_rs_peer,
                    ixlan=self.ixlan,
                    network=self.net,
                    status="ok"
                )

        return self._netixlan

    @property
    def netixlan_exists(self):
        """
        Returns whether or not an active netixlan exists
        for this IXFMemberData instance.
        """
        return (self.netixlan.id and self.netixlan.status != "deleted")

    @property
    def ticket_user(self):
        """
        Returns the User instance for the user to use
        to create DeskPRO tickets
        """
        if not hasattr(self, "_ticket_user"):
            self._ticket_user =  User.objects.get(username="ixf_importer")
        return self._ticket_user

    def __str__(self):
        parts = [
            self.ixlan.ix.name,
            f"AS{self.asn}",
        ]

        if self.ipaddr4:
            parts.append(f"{self.ipaddr4}")
        else:
            parts.append("No IPv4")

        if self.ipaddr6:
            parts.append(f"{self.ipaddr6}")
        else:
            parts.append("No IPv6")

        return " ".join(parts)


    @reversion.create_revision()
    def apply(self, user=None, comment=None, save=True):
        """
        Applies the data.

        This will either create, update or delete a netixlan
        object

        Will return a dict containing action and netixlan
        affected

        ```
        {
            "action": <action(str)>
            "netixlan": <NetworkIXLan>
        }
        ```

        Keyword Argument(s):

        - user(User): if set will set the user on the
          reversion revision
        - comment(str): if set will set the comment on the
          reversion revision
        - save(bool=True): only persist changes to the database
          if this is True
        """

        if user:
            reversion.set_user(user)

        if comment:
            reversion.set_comment(comment)

        action = self.action
        netixlan = self.netixlan
        changes = self.changes

        if action == "add":
            result = self.ixlan.add_netixlan(
                netixlan,
                save=save,
                save_others=save
            )
            self._netixlan = netixlan = result["netixlan"]
        elif action == "modify":
            netixlan.speed = self.speed
            netixlan.is_rs_peer = self.is_rs_peer
            netixlan.operational = self.operational
            netixlan.full_clean()
            if save:
                netixlan.save()
        elif action == "delete":
            if save:
                netixlan.delete()

        if save:
            self.set_resolved()

        return {"action":action, "netixlan":netixlan}

    def save_without_update(self):
        self._meta.get_field("updated").auto_now = False
        self.save()
        self._meta.get_field("updated").auto_now = True

    def grab_validation_errors(self):
        """
        This will attempt to validate the netixlan associated
        with this IXFMemberData instance.

        Any validation errors will be stored to self.error
        """
        try:
            self.netixlan.full_clean()
        except ValidationError as exc:
            self.error = f"{exc}"


    def set_resolved(self, save=True):
        """
        Marks this IXFMemberData instance as resolved and
        send out notifications to ac,ix and net if
        warranted

        this will delete the IXFMemberData instance
        """
        if self.id and save:
            self.notify_resolve(ac=True, ix=True, net=True)
            self.delete(hard=True)

    def set_conflict(self, error=None, save=True):
        """
        Persist this IXFMemberData instance and send out notifications
        for conflict (validation issues) for modifications proposed
        to the corresponding netixlan to ac, ix and net as warranted
        as warranted
        """
        if (self.remote_changes or (error and not self.error)) and save:
            self.error = error
            self.dismissed = False
            self.save()
            self.notify_update(ac=True, ix=True, net=True)
        elif self.previous_data != self.data:

            # since remote_changes only tracks changes to the
            # relevant data fields speed, operational and is_rs_peer
            # we check if the remote data has changed in general
            # and force a save if it did

            self.save_without_update()


    def set_update(self, save=True, reason=""):
        """
        Persist this IXFMemberData instance and send out notifications
        for proposed modification to the corresponding netixlan
        instance to ac, ix and net as warranted
        """
        self.reason = reason
        if ((self.changes and not self.id) or self.remote_changes) and save:
            self.grab_validation_errors()
            self.dismissed = False
            self.save()
            self.notify_update(ac=True, ix=True, net=True)
        elif self.previous_data != self.data:

            # since remote_changes only tracks changes to the
            # relevant data fields speed, operational and is_rs_peer
            # we check if the remote data has changed in general
            # and force a save if it did

            self.save_without_update()



    def set_add(self, save=True, reason=""):
        """
        Persist this IXFMemberData instance and send out notifications
        for proposed creation of netixlan instance to ac, ix and net
        as warranted
        """
        self.reason = reason
        if not self.id and save:
            self.grab_validation_errors()
            self.save()
            if self.net_present_at_ix:
                self.notify_add(ac=True, ix=True, net=True)
            else:
                self.notify_add(net=True)

        elif self.previous_data != self.data:

            # since remote_changes only tracks changes to the
            # relevant data fields speed, operational and is_rs_peer
            # we check if the remote data has changed in general
            # and force a save if it did

            self.save_without_update()


    def set_remove(self, save=True, reason=""):
        """
        Persist this IXFMemberData instance and send out notifications
        for proposed removal of netixlan instance to ac, net and ix
        as warranted
        """
        self.reason = reason

        # we perist this ix-f member data that proposes removal
        # if any of these conditions are met

        # marked for removal, but not saved

        not_saved = (not self.id and self.marked_for_removal)

        # was in remote-data last time, gone now

        gone = (self.id and getattr(self, "previous_data", "{}") != "{}" and self.remote_data_missing)

        if (not_saved or gone) and save:
            self.set_data({})
            self.save()
            self.notify_remove(ac=True, ix=True, net=True)



    def set_data(self, data):
        """
        Stores a dict in self.data as a json string
        """
        self.data = json.dumps(data)

    def notify(self, template_file, recipient, subject, context=None):
        """
        Send notification

        Returns a dict containing information about the notification

        - contacts(list)
        - subject(str)
        - message(str)

        Argument(s):

        - template_file(str): email template file
        - recipient(str): ac, ix or net
        - subject(str): subject text, this will only be used if
          this IXFMemberData instance does not have a valid
          asn, ip4, ip6 identifier
        - context(dict): if set will update the template context
          from this
        """
        _context = {
            "instance": self,
            "recipient": recipient,
            "ixf_url": self.ixlan.ixf_ixp_member_list_url,
        }
        if context:
            _context.update(context)

        template = loader.get_template(template_file)
        message = template.render(_context)

        if self.asn and (self.ipaddr4 or self.ipaddr6):
            subject = f"{settings.EMAIL_SUBJECT_PREFIX}[IX-F] {self}"
        else:
            subject = f"{settings.EMAIL_SUBJECT_PREFIX}[IX-F] {subject}"

        contacts = []

        if recipient == "ac":
            contacts = [DeskProTicket.objects.create(
                subject = subject,
                body = message,
                user = self.ticket_user,
            )]
        elif recipient == "net" and self.actionable_for_network:
            contacts = self.net_contacts
            self._email(subject, message, contacts)
        elif recipient == "ix":
            contacts = self.ix_contacts
            self._email(subject, message, contacts)

        return {
            "contacts": contacts,
            "subject": subject,
            "message": message
        }


    def _email(self, subject, message, recipients):
        """
        Send email

        Honors the MAIL_DEBUG setting

        Called by self.notify depending on recipient
        type
        """
        if not getattr(settings, "MAIL_DEBUG", False):
            raise Exception("NOPE")
            mail = EmailMultiAlternatives(
                subject,
                strip_tags(message),
                settings.DEFAULT_FROM_EMAIL,
                recipients,
            )
            mail.send(fail_silently=False)
        else:
            debug_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                recipients,
            )


    def _notify(self, template_file, subject, context=None, save=True, **recipients):

        """
        Send notification to multiple recipient types

        Argument(s):

        - template_file(str): email template file
        - subject(str): subject text, this will only be used if
          this IXFMemberData instance does not have a valid
          asn, ip4, ip6 identifier
        - context(dict): if set will update the template context
          from this
        - save(bool=True): if True will save this IXFMemberData instance
          (self.log will have been updated with notification lines)

        Keyword Argument(s):

        - ac(bool): if True send notification to admin committee
        - net(bool): if True send notification to network
        - ix(bool): if True send notification to exchange
        """

        log = []
        now = datetime.datetime.now().replace(tzinfo=UTC())


        for recipient in ["ac", "ix", "net"]:
            if not recipients.get(recipient):
                continue
            result = self.notify(
                template_file,
                recipient,
                subject,
                context,
            )

            if result["contacts"]:
                log.append(f"[{now}] notified {recipient} ({result['contacts']}) about {subject}")
            else:
                log.append(f"[{now}] could not notify {recipient} about {subject}: no suitable contacts found")

        self.log = "\n".join(log) + "\n" + self.log

        if save:
            self.save()

    def notify_resolve(self, **kwargs):
        return self._notify(
            "email/notify-ixf-resolved.txt", "Resolved", **kwargs
        )

    def notify_remote_changes(self, **kwargs):
        return self._notify(
            "email/notify-ixf-update.txt", _("IX-F changed"), **kwargs
        )

    def notify_update(self, **kwargs):
        return self._notify(
            "email/notify-ixf-update.txt", _("Modify"), **kwargs
        )

    def notify_add(self,  **kwargs):
        return self._notify(
            "email/notify-ixf-add.txt", _("Add"), **kwargs
        )

    def notify_remove(self, **kwargs):
        return self._notify(
            "email/notify-ixf-remove.txt", _("Remove"), **kwargs
        )

    @property
    def ac_netixlan_url(self):
        if not self.netixlan.id:
            return ""
        path = django.urls.reverse(
            "admin:peeringdb_server_networkixlan_change",
            args=(self.netixlan.id,),
        )
        return f"{settings.BASE_URL}{path}"


    @property
    def ac_url(self):
        if not self.id:
            return ""
        path = django.urls.reverse(
            "admin:peeringdb_server_ixfmemberdata_change",
            args=(self.id,),
        )
        return f"{settings.BASE_URL}{path}"



# read only, or can make bigger, making smaller could break links
# validate could check


@reversion.register
class IXLanPrefix(ProtectedMixin, pdb_models.IXLanPrefixBase):
    """
    Descries a Prefix at an Exchange LAN
    """

    ixlan = models.ForeignKey(
        IXLan, on_delete=models.CASCADE, default=0, related_name="ixpfx_set"
    )

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the ixpfx for logging purposes
        """
        return "ixpfx{} {}".format(self.id, self.prefix)

    @classmethod
    def nsp_namespace_from_id(cls, org_id, ix_id, ixlan_id, id):
        """
        Returns permissioning namespace for an ixpfx
        """
        return "%s.prefix.%s" % (
            IXLan.nsp_namespace_from_id(org_id, ix_id, ixlan_id),
            id,
        )

    @classmethod
    def related_to_ix(cls, value=None, filt=None, field="ix_id", qset=None):
        """
        Filter queryset of ixpfx objects related to exchange via ix_id match
        according to filter

        Relationship through ixlan -> ix
        """
        if not qset:
            qset = cls.handleref.undeleted()
        filt = make_relation_filter("ixlan__%s" % field, filt, value)
        return qset.filter(**filt)

    @classmethod
    def whereis_ip(cls, ipaddr, qset=None):
        """
        Filter queryset of ixpfx objects where the prefix contains
        the supplied ipaddress
        """

        if not qset:
            qset = cls.handleref.undeleted()

        ids = []

        ipaddr = ipaddress.ip_address(ipaddr)

        for ixpfx in qset:
            if ipaddr in ixpfx.prefix:
                ids.append(ixpfx.id)

        return qset.filter(id__in=ids)

    @property
    def nsp_namespace(self):
        """
        Returns permissioning namespace for this ixpfx
        """
        return self.nsp_namespace_from_id(
            self.ixlan.ix.org_id, self.ixlan.ix.id, self.ixlan.id, self.id
        )

    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["ixlan"])

    def test_ip_address(self, addr):
        """
        Checks if this prefix can contain the specified ip address

        Arguments:
            - addr (ipaddress.IPv4Address or ipaddress.IPv6Address or unicode): ip address
                to check, can be either ipv4 or 6 but should be pre-validated to be in the
                correct format as this function will simply return False incase of format
                validation errors.

        Returns:
            - bool: True if prefix can contain the specified address
            - bool: False if prefix cannot contain the specified address
        """

        try:
            if not addr:
                return False
            if isinstance(addr, str):
                addr = ipaddress.ip_address(addr)
            return addr in ipaddress.ip_network(self.prefix)
        except ipaddress.AddressValueError:
            return False

        except ValueError as inst:
            return False

    @property
    def deletable(self):
        """
        Returns whether or not the prefix is currently
        in a state where it can be marked as deleted.

        This will be False for prefixes of which ANY
        of the following is True:

        - parent ixlan has netixlans that fall into
          it's address space
        """

        prefix = self.prefix
        can_delete = True
        for netixlan in self.ixlan.netixlan_set_active:
            if self.protocol == "IPv4":
                if netixlan.ipaddr4 and netixlan.ipaddr4 in prefix:
                    can_delete = False
                    break

            if self.protocol == "IPv6":
                if netixlan.ipaddr6 and netixlan.ipaddr6 in prefix:
                    can_delete = False
                    break


        if not can_delete:
            self._not_deletable_reason = _(
                "There are active peers at this exchange that fall into " \
                "this address space"
            )
        else:
            self._not_deletable_reason = None

        return can_delete

    def clean(self):
        """
        Custom model validation
        """
        # validate the specified prefix address
        validate_address_space(self.prefix)
        validate_prefix_overlap(self.prefix)
        return super(IXLanPrefix, self).clean()


@reversion.register
class Network(pdb_models.NetworkBase):
    """
    Describes a peeringdb network
    """

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="net_set"
    )
    allow_ixp_update = models.BooleanField(
        null=False,
        default=False,
        help_text=_(
            "Sepcifies whether an ixp is allowed to add a netixlan entry for this network via their ixp_member data"
        ),
    )

    @staticmethod
    def autocomplete_search_fields():
        return (
            "id__iexact",
            "name__icontains",
        )

    def __unicode__(self):
        return self.name

    @classmethod
    @reversion.create_revision()
    def create_from_rdap(cls, rdap, asn, org):
        """
        Creates network from rdap result object
        """
        name = rdap.name
        if not rdap.name:
            name = "AS%d" % (asn)
        if cls.objects.filter(name=name).exists():
            net = cls.objects.create(org=org, asn=asn, name="%s !" % name, status="ok")
        else:
            net = cls.objects.create(org=org, asn=asn, name=name, status="ok")
        return net, True

    @classmethod
    def nsp_namespace_from_id(cls, org_id, net_id):
        return "%s.network.%s" % (Organization.nsp_namespace_from_id(org_id), net_id)

    @classmethod
    def related_to_fac(cls, value=None, filt=None, field="facility_id", qset=None):
        """
        Filter queryset of Network objects related to the facility
        specified by fac_id

        Relationship through netfac -> fac
        """
        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)

        q = NetworkFacility.handleref.filter(**filt)
        return qset.filter(id__in=[i.network_id for i in q])

    @classmethod
    def not_related_to_fac(cls, value=None, filt=None, field="facility_id", qset=None):
        """
        Filter queryset of Network objects NOT related to the facility
        specified by fac_id (as in networks NOT present at the facility)

        Relationship through netfac -> fac
        """
        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)

        q = NetworkFacility.handleref.filter(**filt)
        return qset.exclude(id__in=[i.network_id for i in q])

    @classmethod
    def related_to_netfac(cls, value=None, filt=None, field="id", qset=None):
        """
        Filter queryset of Network objects related to the netfac link
        specified by netfac_id

        Relationship through netfac
        """
        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value, prefix="netfac")
        q = NetworkFacility.handleref.filter(**filt)
        return qset.filter(id__in=[i.network_id for i in q])

    @classmethod
    def related_to_netixlan(cls, value=None, filt=None, field="id", qset=None):
        """
        Filter queryset of Network objects related to the netixlan link
        specified by netixlan_id

        Relationship through netixlan
        """
        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value, prefix="netixlan")

        q = NetworkIXLan.handleref.filter(**filt)
        return qset.filter(id__in=[i.network_id for i in q])

    @classmethod
    def related_to_ixlan(cls, value=None, filt=None, field="ixlan_id", qset=None):
        """
        Filter queryset of Network objects related to the ixlan
        specified by ixlan_id

        Relationship through netixlan -> ixlan
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)
        q = NetworkIXLan.handleref.filter(**filt)
        return qset.filter(id__in=[i.network_id for i in q])

    @classmethod
    def related_to_ix(cls, value=None, filt=None, field="ix_id", qset=None):
        """
        Filter queryset of Network objects related to the ix
        specified by ix_id

        Relationship through netixlan -> ixlan -> ix
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter("ixlan__%s" % field, filt, value)
        q = NetworkIXLan.handleref.select_related("ixlan").filter(**filt)
        return qset.filter(id__in=[i.network_id for i in q])

    @classmethod
    def not_related_to_ix(cls, value=None, filt=None, field="ix_id", qset=None):
        """
        Filter queryset of Network objects not related to the ix
        specified by ix_id (as in networks not present at the exchange)

        Relationship through netixlan -> ixlan -> ix
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter("ixlan__%s" % field, filt, value)
        q = NetworkIXLan.handleref.select_related("ixlan").filter(**filt)
        return qset.exclude(id__in=[i.network_id for i in q])

    @classmethod
    def as_set_map(cls, qset=None):
        """
        Returns a dict mapping asns to their irr_as_set value
        """
        if not qset:
            qset = cls.objects.filter(status="ok").order_by("asn")
        return dict([(net.asn, net.irr_as_set) for net in qset])

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity
        """

        return "%s (%s)" % (self.name, self.asn)

    @property
    def netfac_set_active(self):
        return self.netfac_set(manager="handleref").filter(status="ok")

    @property
    def netixlan_set_active(self):
        return self.netixlan_set(manager="handleref").filter(status="ok")

    @property
    def ixlan_set_active(self):
        """
        Returns IXLan queryset for ixlans connected to this network
        through NetworkIXLan
        """
        ixlan_ids = []
        for netixlan in self.netixlan_set_active:
            if netixlan.ixlan_id not in ixlan_ids:
                ixlan_ids.append(netixlan.ixlan_id)
        return IXLan.objects.filter(id__in=ixlan_ids)

    @property
    def ixlan_set_ixf_enabled(self):
        """
        Returns IXLan queryset for IX-F import enabled ixlans connected
        to this network throught NetworkIXLan
        """
        qset = self.ixlan_set_active.filter(ixf_ixp_import_enabled=True)
        qset = qset.exclude(ixf_ixp_member_list_url__isnull=True)
        return qset

    @property
    def poc_set_active(self):
        return self.poc_set(manager="handleref").filter(status="ok")

    @property
    def nsp_namespace(self):
        """
        Returns a custom permission namespace for an instance of this
        model
        """

        return self.__class__.nsp_namespace_from_id(self.org_id, self.id)

    @property
    def nsp_ruleset(self):
        """
        Ruleset to apply when applying permissions to the serialized
        data of this model
        """

        return {
            # we require explicit perms to private network contacts
            "require": {"poc_set.users": 0x01, "poc_set.private": 0x01},
            # since poc are stored in a list we need to specify a list
            # handler for it, its a class function on NetworkContact that
            # returns a relative permission namespace for each poc in the
            # list
            "list-handlers": {
                "poc_set": {"namespace": NetworkContact.nsp_namespace_in_list}
            },
        }

    @property
    def sponsorship(self):
        return self.org.sponsorship

    @property
    def view_url(self):
        """
        Return the URL to this networks web view
        """
        return "{}{}".format(
            settings.BASE_URL, django.urls.reverse("net-view", args=(self.id,))
        )


    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["org"])

    def clean(self):
        """
        Custom model validation
        """

        try:
            validate_info_prefixes4(self.info_prefixes4)
        except ValidationError as exc:
            raise ValidationError({"info_prefixes4": exc})

        try:
            validate_info_prefixes6(self.info_prefixes6)
        except ValidationError as exc:
            raise ValidationError({"info_prefixes6": exc})

        try:
            if self.irr_as_set:
                self.irr_as_set = validate_irr_as_set(self.irr_as_set)
        except ValidationError as exc:
            raise ValidationError({"irr_as_set": exc})


        return super(Network, self).clean()



# class NetworkContact(HandleRefModel):
@reversion.register
class NetworkContact(pdb_models.ContactBase):
    """
    Describes a contact point (phone, email etc.) for a network
    """

    # id = models.AutoField(primary_key=True)
    network = models.ForeignKey(
        Network, on_delete=models.CASCADE, default=0, related_name="poc_set"
    )

    class Meta:
        db_table = "peeringdb_network_contact"

    @classmethod
    def nsp_namespace_in_list(cls, **kwargs):
        """
        This is used to build a relative namespace for this model if it is contained
        within a list. The preceding namespace part will be provided by the container
        element.

        So in this case we just want to return the value of the visible attribute
        """
        if "obj" in kwargs:
            return "%s" % kwargs.get("obj")
        return kwargs.get("visible")

    @classmethod
    def nsp_namespace_from_id(cls, org_id, net_id, vis):
        """
        Returns permissioning namespace for a network contact
        """
        return "%s.poc_set.%s" % (Network.nsp_namespace_from_id(org_id, net_id), vis)

    @property
    def nsp_namespace(self):
        """
        Returns a custom namespace for an instance of this model
        """
        return self.__class__.nsp_namespace_from_id(
            self.network.org_id, self.network.id, self.visible
        )

    @property
    def nsp_require_explicit_read(self):
        """
        Make sure non-public instances of this models are always requiring
        explicit permissions to view
        """
        return self.visible != "Public"

    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["net"])

    def clean(self):
        self.phone = validate_phonenumber(self.phone)


@reversion.register
class NetworkFacility(pdb_models.NetworkFacilityBase):
    """
    Describes a network <-> facility relationship
    """

    network = models.ForeignKey(
        Network, on_delete=models.CASCADE, default=0, related_name="netfac_set"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, default=0, related_name="netfac_set"
    )

    class Meta:
        db_table = "peeringdb_network_facility"
        unique_together = ("network", "facility", "local_asn")

    @classmethod
    def nsp_namespace_from_id(cls, org_id, net_id, fac_id):
        """
        Returns permissioning namespace for a netfac
        """
        return "%s.fac.%s" % (Network.nsp_namespace_from_id(org_id, net_id), fac_id)

    @property
    def nsp_namespace(self):
        """
        Returns permissioning namespace for this netfac
        """
        return self.__class__.nsp_namespace_from_id(
            self.network.org_id, self.network_id, self.facility_id
        )

    @classmethod
    def related_to_name(cls, value=None, filt=None, field="facility__name", qset=None):
        """
        Filter queryset of netfac objects related to facilities with name match
        in facility__name according to filter

        Relationship through facility
        """
        if not qset:
            qset = cls.handleref.undeleted()
        return qset.filter(**make_relation_filter(field, filt, value))

    @classmethod
    def related_to_country(
        cls, value=None, filt=None, field="facility__country", qset=None
    ):
        """
        Filter queryset of netfac objects related to country via match
        in facility__country according to filter

        Relationship through facility
        """
        if not qset:
            qset = cls.handleref.filter(status="ok")
        return qset.filter(**make_relation_filter(field, filt, value))

    @classmethod
    def related_to_city(cls, value=None, filt=None, field="facility__city", qset=None):
        """
        Filter queryset of netfac objects related to city via match
        in facility__city according to filter

        Relationship through facility
        """
        if not qset:
            qset = cls.handleref.undeleted()
        return qset.filter(**make_relation_filter(field, filt, value))

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the netfac for logging purposes
        """
        return "netfac{} AS{} {} <-> {}".format(
            self.id, self.network.asn, self.network.name, self.facility.name
        )

    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["net"])

    def clean(self):

        # when validating an existing netfac that has a mismatching
        # local_asn value raise a validation error stating that it needs
        # to be moved
        #
        # this is to catch and force correction of instances where they
        # could not be migrated automatically during rollout of #168
        # because the targeted local_asn did not exist in peeringdb

        if self.id and self.local_asn != self.network.asn:
            raise ValidationError(
                _(
                    "This entity was created for the ASN {} - please remove it from this network and recreate it under the correct network"
                ).format(self.local_asn)
            )

        # `local_asn` will eventually be dropped from the schema
        # for now make sure it is always a match to the related
        # network (#168)

        self.local_asn = self.network.asn


# validate:
# ip in prefix
# prefix on lan
# FIXME - need unique constraint at save time, allow empty string for ipv4/ipv6
@reversion.register
class NetworkIXLan(pdb_models.NetworkIXLanBase):
    """
    Describes a network relationship to an IX through an IX Lan
    """

    network = models.ForeignKey(
        Network, on_delete=models.CASCADE, default=0, related_name="netixlan_set"
    )
    ixlan = models.ForeignKey(
        IXLan, on_delete=models.CASCADE, default=0, related_name="netixlan_set"
    )

    class Meta:
        db_table = "peeringdb_network_ixlan"
        constraints = [
            models.UniqueConstraint(fields=["ipaddr4"], name="unique_ipaddr4"),
            models.UniqueConstraint(fields=["ipaddr6"], name="unique_ipaddr6"),
        ]

    @property
    def name(self):
        return ""

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the netixlan for logging purposes
        """
        return "netixlan{} AS{} {} {}".format(
            self.id, self.asn, self.ipaddr4, self.ipaddr6
        )

    @property
    def ix_name(self):
        """
        Returns the exchange name for this netixlan
        """
        return self.ixlan.ix.name

    @property
    def ix_id(self):
        """
        Returns the exchange id for this netixlan
        """
        return self.ixlan.ix_id

    @property
    def ixf_id(self):

        """
        Returns a tuple that identifies the netixlan
        in the context of an ix-f member data entry

        as a unqiue record by asn, ip4 and ip6 address
        """

        return (self.asn, self.ipaddr4, self.ipaddr6)

    # FIXME
    # permission namespacing
    # right now it is assumed that the network owns the netixlan
    # this needs to be discussed further

    @classmethod
    def nsp_namespace_from_id(cls, org_id, net_id, ixlan_id):
        """
        Returns permissioning namespace for a netixlan
        """
        return "%s.ixlan.%s" % (Network.nsp_namespace_from_id(org_id, net_id), ixlan_id)

    @property
    def nsp_namespace(self):
        """
        Returns permissioning namespace for this netixlan
        """
        return self.__class__.nsp_namespace_from_id(
            self.network.org_id, self.network.id, self.ixlan_id
        )

    def nsp_has_perms_PUT(self, user, request):
        return validate_PUT_ownership(user, self, request.data, ["net"])

    @classmethod
    def related_to_ix(cls, value=None, filt=None, field="ix_id", qset=None):
        """
        Filter queryset of netixlan objects related to the ix
        specified by ix_id

        Relationship through ixlan -> ix
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)

        q = IXLan.handleref.select_related("ix").filter(**filt)
        return qset.filter(ixlan_id__in=[i.id for i in q])

    @classmethod
    def related_to_name(cls, value=None, filt=None, field="ix__name", qset=None):
        """
        Filter queryset of netixlan objects related to exchange via a name match
        according to filter

        Relationship through ixlan -> ix
        """
        return cls.related_to_ix(value=value, filt=filt, field=field, qset=qset)

    def ipaddress_conflict(self):
        """
        Checks whether the ip addresses specified on this netixlan
        exist on another netixlan (with status="ok")

        Returns:
            - tuple(bool, bool): tuple of two booleans, first boolean is
                true if there was a conflict with the ip4 address, second
                boolean is true if there was a conflict with the ip6
                address
        """

        ipv4 = NetworkIXLan.objects.filter(ipaddr4=self.ipaddr4, status="ok").exclude(
            id=self.id
        )
        ipv6 = NetworkIXLan.objects.filter(ipaddr6=self.ipaddr6, status="ok").exclude(
            id=self.id
        )
        conflict_v4 = self.ipaddr4 and ipv4.exists()
        conflict_v6 = self.ipaddr6 and ipv6.exists()
        return (conflict_v4, conflict_v6)

    def validate_ipaddr4(self):
        if self.ipaddr4 and not self.ixlan.test_ipv4_address(self.ipaddr4):
            raise ValidationError(_("IPv4 address outside of prefix"))

    def validate_ipaddr6(self):
        if self.ipaddr6 and not self.ixlan.test_ipv6_address(self.ipaddr6):
            raise ValidationError(_("IPv6 address outside of prefix"))

    def clean(self):
        """
        Custom model validation
        """
        errors = {}

        # check that the ip address can be validated agaisnt
        # at least one of the prefix on the parent ixlan

        try:
            self.validate_ipaddr4()
        except ValidationError as exc:
            errors["ipaddr4"] = exc.message

        try:
            self.validate_ipaddr6()
        except ValidationError as exc:
            errors["ipaddr6"] = exc.message

        if errors:
            raise ValidationError(errors)

        # make sure this ip address is not claimed anywhere else

        conflict_v4, conflict_v6 = self.ipaddress_conflict()
        if conflict_v4:
            errors["ipaddr4"] = _("Ip address already exists elsewhere")
        if conflict_v6:
            errors["ipaddr6"] = _("Ip address already exists elsewhere")

        if errors:
            raise ValidationError(errors)

        # when validating an existing netixlan that has a mismatching
        # asn value raise a validation error stating that it needs
        # to be moved
        #
        # this is to catch and force correction of instances where they
        # could not be migrated automatically during rollout of #168
        # because the targeted asn did not exist in peeringdb

        if self.id and self.asn != self.network.asn:
            raise ValidationError(
                _(
                    "This entity was created for the ASN {} - please remove it from this network and recreate it under the correct network"
                ).format(self.asn)
            )

        # `asn` will eventually be dropped from the schema
        # for now make sure it is always a match to the related
        # network (#168)

        self.asn = self.network.asn

    def ipaddr(self, version):
        """
        Return the netixlan's ipaddr for ip version
        """
        if version == 4:
            return self.ipaddr4
        elif version == 6:
            return self.ipaddr6
        raise ValueError("Invalid ip version {}".format(version))

    def descriptive_name_ipv(self, version):
        """
        Returns a descriptive label of the netixlan for logging purposes
        Will only contain the ipaddress matching the specified version
        """
        return "netixlan{} AS{} {}".format(self.id, self.asn, self.ipaddr(version))


class User(AbstractBaseUser, PermissionsMixin):
    """
    proper length fields user
    """

    username = models.CharField(
        _("username"),
        max_length=254,
        unique=True,
        help_text=_("Required. Letters, digits and [@.+-/_=|] only."),
        validators=[
            validators.RegexValidator(
                r"^[\w\.@+-=|/]+$",
                _("Enter a valid username."),
                "invalid",
                flags=re.UNICODE,
            )
        ],
    )
    email = models.EmailField(_("email address"), max_length=254)
    first_name = models.CharField(_("first name"), max_length=254, blank=True)
    last_name = models.CharField(_("last name"), max_length=254, blank=True)
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. Unselect this instead of deleting accounts."
        ),
    )
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    created = CreatedDateTimeField()
    updated = UpdatedDateTimeField()
    status = models.CharField(_("status"), max_length=254, default="ok")
    locale = models.CharField(_("language"), max_length=62, blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        db_table = "peeringdb_user"
        verbose_name = _("user")
        verbose_name_plural = _("users")


    @property
    def pending_affiliation_requests(self):
        """
        Returns the currently pending user -> org affiliation
        requests for this user
        """
        return self.affiliation_requests.filter(status="pending").order_by("-created")

    @property
    def affiliation_requests_available(self):
        """
        Returns whether the user currently has any affiliation request
        slots available, by checking that the number of pending affiliation requests
        the user has is lower than MAX_USER_AFFILIATION_REQUESTS
        """
        return (self.pending_affiliation_requests.count() < settings.MAX_USER_AFFILIATION_REQUESTS)

    @property
    def organizations(self):
        """
        Returns all organizations this user is a member of
        """
        ids = []
        for group in self.groups.all():
            m = re.match(r"^org\.(\d+).*$", group.name)
            if m and int(m.group(1)) not in ids:
                ids.append(int(m.group(1)))

        return [org for org in Organization.objects.filter(id__in=ids, status="ok")]

    @property
    def networks(self):
        """
        Returns all networks this user is a member of
        """
        return list(
            chain.from_iterable(org.net_set_active.all() for org in self.organizations)
        )

    @property
    def full_name(self):
        return "%s %s" % (self.first_name, self.last_name)

    @property
    def has_oauth(self):
        return SocialAccount.objects.filter(user=self).count() > 0

    @property
    def email_confirmed(self):
        """
        Returns True if the email specified by the user has
        been confirmed, False if not
        """

        try:
            email = EmailAddress.objects.get(user=self, email=self.email, primary=True)
        except EmailAddress.DoesNotExist:
            return False

        return email.verified

    @property
    def is_verified_user(self):
        """
        Returns whether the user is verified (eg has been validated
        by pdb staff)

        right now this is accomplished by checking if the user
        has been added to the 'user' user group
        """

        group = Group.objects.get(id=settings.USER_GROUP_ID)
        return group in self.groups.all()

    @staticmethod
    def autocomplete_search_fields():
        """
        Used by grappelli autocomplete to determine what
        fields to search in
        """
        return ("username__icontains", "email__icontains", "last_name__icontains")


    def related_label(self):
        """
        Used by grappelli autocomplete for representation
        """
        return "{} <{}> ({})".format(self.username, self.email, self.id)


    def flush_affiliation_requests(self):
        """
        Removes all user -> org affiliation requests for this user
        that have been denied or canceled
        """

        UserOrgAffiliationRequest.objects.filter(
            user=self, status__in=["denied","canceled"]
        ).delete()

    def get_locale(self):
        "Returns user preferred language."
        return self.locale

    def set_locale(self, locale):
        "Returns user preferred language."
        self.locale = locale
        self.save()

    def get_absolute_url(self):
        return "/users/%s/" % urlquote(self.email)

    def get_full_name(self):
        """
        Returns the first_name plus the last_name, with a space in between.
        """
        full_name = "%s %s" % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def email_user(self, subject, message, from_email=settings.DEFAULT_FROM_EMAIL):
        """
        Sends an email to this User.
        """
        if not getattr(settings, "MAIL_DEBUG", False):
            mail = EmailMultiAlternatives(
                subject,
                message,
                from_email,
                [self.email],
                headers={"Auto-Submitted": "auto-generated", "Return-Path": "<>"},
            )
            mail.send(fail_silently=False)
        else:
            debug_mail(subject, message, from_email, [self.email])

    def set_unverified(self):
        """
        Remove user from 'user' group
        Add user to 'guest' group
        """
        guest_group = Group.objects.get(id=settings.GUEST_GROUP_ID)
        user_group = Group.objects.get(id=settings.USER_GROUP_ID)
        groups = self.groups.all()
        if guest_group not in groups:
            guest_group.user_set.add(self)
        if user_group in groups:
            user_group.user_set.remove(self)
        self.status = "pending"
        self.save()

    def set_verified(self):
        """
        Add user to 'user' group
        Remove user from 'guest' group
        """
        guest_group = Group.objects.get(id=settings.GUEST_GROUP_ID)
        user_group = Group.objects.get(id=settings.USER_GROUP_ID)
        groups = self.groups.all()
        if guest_group in groups:
            guest_group.user_set.remove(self)
        if user_group not in groups:
            user_group.user_set.add(self)
        self.status = "ok"
        self.save()

    def send_email_confirmation(self, request=None, signup=False):
        """
        Use allauth email-confirmation process to make user
        confirm that the email they provided is theirs.
        """

        # check if there is actually an email set on the user
        if not self.email:
            return None

        # allauth supports multiple email addresses per user, however
        # we dont need that, so we check for the primary email address
        # and if it already exist we make sure to update it to the
        # email address currently specified on the user instance
        try:
            email = EmailAddress.objects.get(email=self.email)
            email.email = self.email
            email.user = self
            email.verified = False
            try:
                EmailConfirmation.objects.get(email_address=email).delete()
            except EmailConfirmation.DoesNotExist:
                pass
        except EmailAddress.DoesNotExist:
            if EmailAddress.objects.filter(user=self).exists():
                EmailAddress.objects.filter(user=self).delete()
            email = EmailAddress(user=self, email=self.email, primary=True)

        email.save()

        email.send_confirmation(request=request, signup=signup)

        return email

    def password_reset_complete(self, token, password):
        if self.password_reset.match(token):
            self.set_password(password)
            self.save()
            self.password_reset.delete()

    def password_reset_initiate(self):
        """
        Initiate the password reset process for the user
        """

        # pylint: disable=access-member-before-definition

        if self.id:

            try:
                self.password_reset.delete()
            except UserPasswordReset.DoesNotExist:
                pass

            token, hashed = password_reset_token()

            self.password_reset = UserPasswordReset.objects.create(
                user=self, token=hashed
            )
            template = loader.get_template("email/password-reset.txt")
            with override(self.locale):
                self.email_user(
                    _("Password Reset Initiated"),
                    template.render(
                        {
                            "user": self,
                            "token": token,
                            "password_reset_url": settings.PASSWORD_RESET_URL,
                        }
                    ),
                )
            return token, hashed
        return None, None

    def vq_approve(self):
        self.set_verified()

    def is_org_member(self, org):
        return self.groups.filter(id=org.usergroup.id).exists()

    def is_org_admin(self, org):
        return self.groups.filter(id=org.admin_usergroup.id).exists()

    def validate_rdap_relationship(self, rdap):
        """
        #Domain only matching
        email_domain = self.email.split("@")[1]
        for email in rdap.emails:
            try:
                domain = email.split("@")[1]
                if email_domain == domain:
                    return True
            except IndexError, inst:
                pass
        """
        # Exact email matching
        for email in rdap.emails:
            if email.lower() == self.email.lower():
                return True
        return False


def password_reset_token():

    token = str(uuid.uuid4())
    hashed = sha256_crypt.hash(token)
    return token, hashed


class UserPasswordReset(models.Model):
    class Meta:
        db_table = "peeringdb_user_password_reset"

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, primary_key=True, related_name="password_reset"
    )
    token = models.CharField(max_length=255)
    created = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        valid_until = self.created + datetime.timedelta(hours=2)
        if datetime.datetime.now().replace(tzinfo=UTC()) > valid_until:
            return False
        return True

    def match(self, token):
        return sha256_crypt.verify(token, self.token)


class CommandLineTool(models.Model):
    """
    Describes command line tool execution by a staff user inside the
    control panel (admin)
    """

    tool = models.CharField(
        max_length=255, help_text=_("name of the tool"), choices=COMMANDLINE_TOOLS
    )
    arguments = models.TextField(
        help_text=_("json serialization of arguments and options passed")
    )
    result = models.TextField(null=True, blank=True, help_text=_("result log"))
    description = models.CharField(
        max_length=255,
        help_text=_("Descriptive text of command that can be searched"),
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        help_text=_("the user that ran this command"),
        related_name="clt_history",
    )
    created = models.DateTimeField(
        auto_now_add=True, help_text=_("command was run at this date and time")
    )

    status = models.CharField(
        max_length=255,
        default="done",
        choices=[
            ("done", _("Done")),
            ("waiting", _("Waiting")),
            ("running", _("Running")),
        ],
    )

    def __str__(self):
        return "{}: {}".format(self.tool, self.description)

    def set_waiting(self):
        self.status = "waiting"

    def set_done(self):
        self.status = "done"

    def set_running(self):
        self.status = "running"


REFTAG_MAP = dict(
    [
        (cls.handleref.tag, cls)
        for cls in [
            Organization,
            Network,
            Facility,
            InternetExchange,
            InternetExchangeFacility,
            NetworkFacility,
            NetworkIXLan,
            NetworkContact,
            IXLan,
            IXLanPrefix,
        ]
    ]
)


QUEUE_ENABLED = []
QUEUE_NOTIFY = []

if not getattr(settings, "DISABLE_VERIFICATION_QUEUE", False):
    # enable verification queue for these models
    QUEUE_ENABLED = (User, InternetExchange, Network, Facility, Organization)

    if not getattr(settings, "DISABLE_VERIFICATION_QUEUE_EMAILS", False):
        # send admin notification emails for these models
        QUEUE_NOTIFY = (InternetExchange, Network, Facility, Organization)

autodiscover_namespaces(Network, Facility, InternetExchange)
