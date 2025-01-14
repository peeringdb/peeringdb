"""
Django model definitions (database schema).

## django-peeringdb

peeringdb_server uses the abstract models from django-peeringdb.

Often, it makes the most sense for a field to be added to the abstraction
in django-peeringdb, so it can be available for people using local snapshots of the databases.

Generally speaking, if the field is to be added to the REST API output,
it should be added through django-peeringdb.

Fields to facilitate internal operations of peeringdb on the other hand, DO NOT need to be added to django-peeringdb.

## migrations

For concrete models, django-peeringdb and peeringdb_server maintain separate model migrations.

When adding new fields to django-peeringdb make sure migration files for the schema changes exist in both places.

Please open a merge request in peeringdb/django-peeringdb for the field addition as well.
"""

import datetime
import ipaddress
import json
import logging
import re
import uuid
from itertools import chain
from urllib.parse import quote as urlquote
from urllib.parse import urljoin

import django.urls
import django_peeringdb.models as pdb_models
import oauth2_provider.models as oauth2
import reversion
from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    AnonymousUser,
    Group,
    PermissionsMixin,
    UserManager,
)
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core import validators
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail.message import EmailMultiAlternatives
from django.db import models, transaction
from django.template import loader
from django.utils import timezone
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.utils.translation import override
from django_grainy.decorators import grainy_model
from django_grainy.models import Permission, PermissionManager
from django_grainy.util import check_permissions
from django_handleref.models import CreatedDateTimeField, UpdatedDateTimeField
from django_inet.models import ASNField
from passlib.hash import sha256_crypt
from rest_framework_api_key.models import AbstractAPIKey
from reversion.models import Version

import peeringdb_server.geo as geo
from peeringdb_server.context import current_request
from peeringdb_server.inet import RdapLookup, RdapNotFoundError
from peeringdb_server.managers import CustomManager
from peeringdb_server.request import bypass_validation
from peeringdb_server.validators import (
    validate_address_space,
    validate_api_rate,
    validate_bool,
    validate_email_domains,
    validate_info_prefixes4,
    validate_info_prefixes6,
    validate_irr_as_set,
    validate_phonenumber,
    validate_poc_visible,
    validate_prefix_overlap,
)

API_KEY_STATUS = (
    ("active", _("Active")),
    ("inactive", _("Inactive")),
)

SPONSORSHIP_LEVELS = (
    (1, _("Silver")),
    (2, _("Gold")),
    (3, _("Platinum")),
    (4, _("Diamond")),
)

SPONSORSHIP_CSS = (
    (1, "silver"),
    (2, "gold"),
    (3, "platinum"),
    (4, "diamond"),
)

PARTNERSHIP_LEVELS = ((1, _("Data Validation")), (2, _("RIR")))

COMMANDLINE_TOOLS = (
    ("pdb_renumber_lans", _("Renumber IP Space")),
    ("pdb_fac_merge", _("Merge Facilities")),
    ("pdb_fac_merge_undo", _("Merge Facilities: UNDO")),
    ("pdb_undelete", _("Restore Object(s)")),
    ("pdb_validate_data", _("Validate Data")),
)

REAUTH_PERIODS = (
    ("1w", _("1 Week")),
    ("2w", _("2 Weeks")),
    ("1m", _("1 Month")),
    ("3m", _("3 Month")),
    ("6m", _("6 Months")),
    ("1y", _("1 Year")),
)


if settings.TUTORIAL_MODE:
    COMMANDLINE_TOOLS += (("pdb_wipe", _("Reset Environment")),)

COMMANDLINE_TOOLS += (("pdb_ixf_ixp_member_import", _("IX-F Import")),)

logger = logging.getLogger(__name__)


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
        filt = {f"{field}__{filt}": value}
    else:
        filt = {field: value}
    filt.update(status="ok")
    return filt


def validate_PUT_ownership(permission_holder, instance, data, fields):
    """
    Helper function that checks if a user or API key has write perms to
    the instance provided as well as write perms to any
    child instances specified by fields as they exist on
    the model and in data.

    Example:

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

    if not check_permissions(permission_holder, instance, "u"):
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
                if not check_permissions(permission_holder, other, "u"):
                    return False
            except ValueError:  # if id is not intable
                return False

    return True


def is_suggested(entity):
    """
    Check if the network, facility or exchange is a suggested
    entity (is it a memeber of the organization designated to
    hold suggested entities).
    """

    # if no org is specified, entity suggestion is turned
    # off
    if not getattr(settings, "SUGGEST_ENTITY_ORG", 0):
        return False

    org_id = getattr(entity, "org_id", 0)
    return org_id == settings.SUGGEST_ENTITY_ORG


class ParentStatusException(IOError):
    """
    Throw this when an object cannot be created because its parent is
    either status pending or deleted.
    """

    def __init__(self, parent, typ):
        if parent.status == "pending":
            super().__init__(
                _(
                    "Object of type '%(type)s' cannot be saved because its parent entity '%(parent_tag)s/%(parent_id)s' has not yet been approved"
                )
                % {"type": typ, "parent_tag": parent.ref_tag, "parent_id": parent.id}
            )
        elif parent.status == "deleted":
            super().__init__(
                _(
                    "Object of type '%(type)s' cannot be saved because its parent entity '%(parent_tag)s/%(parent_id)s' has been marked as deleted"
                )
                % {"type": typ, "parent_tag": parent.ref_tag, "parent_id": parent.id}
            )


class UTC(datetime.tzinfo):
    """
    UTC+0 tz for tz aware datetime fields.
    """

    def utcoffset(self, d):
        return datetime.timedelta(seconds=0)


class URLField(pdb_models.URLField):
    """
    Local defaults for URLField.
    """


class ValidationErrorEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ValidationError):
            if hasattr(obj, "error_dict"):
                return obj.error_dict
            return obj.message
        elif isinstance(obj, Promise):
            return f"{obj}"
        return super().default(obj)


class ProtectedAction(ValueError):
    def __init__(self, obj):
        super().__init__(obj.not_deletable_reason)
        self.protected_object = obj


class StripFieldMixin(models.Model):
    """
    Mixin to remove whitespace at the beginning and end of string fields
    """

    class Meta:
        abstract = True

    def strip_string_fields(self):
        """
        Strip value in string fields
        """
        for field in self._meta.fields:
            if isinstance(field, (models.CharField, models.TextField)):
                value = getattr(self, field.name)
                if value and type(value) is str:
                    setattr(self, field.name, value.strip())

    def clean(self):
        # strip string fields in model clean validation
        self.strip_string_fields()
        super().clean()

    def save(self, *args, **kwargs):
        # strip string fields when save or update object
        self.strip_string_fields()
        super().save(*args, **kwargs)


class ParentStatusCheckMixin:
    """
    Mixin that implements checks for creating
    / updating an instance that will raise
    exception under certain criteria
    """

    def validate_parent_status(self):
        """
        Validate parent status against object (child) status

        A child cannot be `ok` or `pending` if the parent is `deleted`
        A child cannot be `ok` if the parent is `pending`

        Will raise ParentStatus exception on invalid status.

        Can be disabled by setting `DATA_QUALITY_VALIDATE_PARENT_STATUS` to False

        :return:
        """

        if not settings.DATA_QUALITY_VALIDATE_PARENT_STATUS:
            return

        for field_name in self.parent_relations:
            if (
                getattr(self, field_name).status == "deleted"
                and self.status != "deleted"
            ):
                raise ParentStatusException(
                    getattr(self, field_name), self.HandleRef.tag
                )
            elif getattr(self, field_name).status == "pending" and self.status == "ok":
                raise ParentStatusException(
                    getattr(self, field_name), self.HandleRef.tag
                )

    def validate_status_change(self):
        """
        Validate status changes:
        - Prevent changing from 'ok' to 'pending'
        """
        if self._state.adding:
            return

        original = self.__class__.objects.get(pk=self.pk)
        if original.status == "ok" and self.status == "pending":
            raise ValidationError("Cannot change status from 'ok' to 'pending'")

    def clean(self):
        self.validate_status_change()
        super().clean()


class ProtectedMixin:
    """
    Mixin that implements checks for changing
    / deleting a model instance that will block
    such actions under certain circumstances.
    """

    @property
    def deletable(self):
        """
        Should return whether the object is currently
        in a state where it can safely be soft-deleted.

        If not deletable, should specify reason in
        `_not_deletable_reason` property.

        If deletable, should set `_not_deletable_reason`
        property to None.
        """
        return True

    @property
    def not_deletable_reason(self):
        return getattr(self, "_not_deletable_reason", None)

    def delete(self, hard=False, force=False):
        if self.status in ["ok", "pending"]:
            if (
                not self.deletable
                and not force
                and not bypass_validation(check_admin=True)
            ):
                raise ProtectedAction(self)

        self.delete_cleanup()
        return super().delete(hard=hard)

    def delete_cleanup(self):
        """
        Runs cleanup before delete.

        Override this in the class that uses this mixin (if needed).
        """
        return

    def save_without_timestamp(self):
        self._meta.get_field("updated").auto_now = False
        try:
            self.save()
        finally:
            self._meta.get_field("updated").auto_now = True


class SocialMediaMixin(models.Model):
    def save(self, *args, **kwargs):
        # Check if social_media is null, and if so, set it to [{}]
        if self.social_media is None:
            self.social_media = {}
        super().save(*args, **kwargs)

    class Meta:
        abstract = True


class GeocodeBaseMixin(models.Model):
    """
    Mixin to use for geocode enabled entities.
    Allows an entity to be geocoded with the pdb_geo_sync command.
    """

    geocode_status = models.BooleanField(
        default=False,
        help_text=_(
            "Has this object's address been normalized with a call to the Google Maps API"
        ),
    )
    geocode_date = models.DateTimeField(
        blank=True, null=True, help_text=_("Last time of attempted geocode")
    )

    class Meta:
        abstract = True

    @property
    def geocode_coordinates(self):
        """
        Return a tuple holding the latitude and longitude.
        """
        if self.latitude is not None and self.longitude is not None:
            return (self.latitude, self.longitude)
        return None

    @property
    def geocode_address(self):
        """
        Returns an address string suitable for geo API query.
        """
        # pylint: disable=missing-format-attribute
        return (
            f"{self.address1} {self.address2}, {self.city}, {self.state} {self.zipcode}"
        )

    def process_geo_location(self, geocode=True, save=True):
        """
        Sets longitude and latitude.

        Will return a dict containing normalized address
        data.
        """

        melissa = geo.Melissa(settings.MELISSA_KEY, timeout=5)
        gmaps = geo.GoogleMaps(settings.GOOGLE_GEOLOC_API_KEY, timeout=5)

        # geocode using google

        use_melissa_coords = False

        try:
            if geocode:
                gmaps.geocode(self)
        except geo.Timeout:
            raise ValidationError(_("Geo coding timed out"))
        except geo.RequestError as exc:
            raise ValidationError(_("Geo coding failed: {}").format(exc))
        except geo.NotFound:
            use_melissa_coords = True

        # address normalization using melissa
        #
        # note: `sanitized` will be an empty dict if melissa
        # could not normalize a valid address

        try:
            sanitized = melissa.sanitize_address_model(self)
        except geo.Timeout:
            raise ValidationError(_("Geo location lookup timed out"))
        except geo.RequestError as exc:
            raise ValidationError(_("Geo location lookup failed: {}").format(exc))

        # update latitude and longitude

        if use_melissa_coords and sanitized:
            self.latitude = sanitized["latitude"]
            self.longitude = sanitized["longitude"]

        if geocode and (not use_melissa_coords or sanitized):
            self.geocode_status = True
            self.geocode_date = datetime.datetime.now(datetime.timezone.utc)
            if sanitized:
                sanitized["geocode_status"] = True
                sanitized["geocode_date"] = self.geocode_date

        if save:
            self.save()

        return sanitized

    def clean(self):
        """
        As per #1482 the floor field is being deprecated
        and only empty values are allowed.
        """
        super().clean()
        if self.floor:
            err_msg = (
                _("Field is being deprecated.")
                + " "
                + _("Please move this data to the suite field and remove it from here.")
            )
            raise ValidationError({"floor": err_msg})


class GeoCoordinateCache(StripFieldMixin):
    """
    Stores geocoordinates for address lookups.
    """

    country = pdb_models.CountryField()
    city = models.CharField(max_length=255, null=True, blank=True)
    address1 = models.CharField(max_length=255, null=True, blank=True)
    state = models.CharField(max_length=255, null=True, blank=True)
    zipcode = models.CharField(max_length=255, null=True, blank=True)

    latitude = models.DecimalField(
        _("Latitude"), max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        _("Longitude"), max_digits=9, decimal_places=6, null=True, blank=True
    )

    fetched = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "peeringdb_geocoord_cache"
        verbose_name = _("Geocoordinate Cache")
        verbose_name_plural = _("Geocoordinate Cache Entries")

    @classmethod
    def request_coordinates(cls, **kwargs):
        address_fields = [
            "address1",
            "zipcode",
            "state",
            "city",
            "country",
        ]

        # we only request geo-coordinates if country and
        # city/state are specified

        if not kwargs.get("country"):
            return None

        if not kwargs.get("city") and not kwargs.get("state"):
            return None

        # address string passed to google for lookup
        address = []

        # filters passed to GeoCoordinateCache for cache retrieval
        filters = {}

        # attributes passed to GeoCoordinateCache for cache creation
        params = {}

        # prepare geo-coordinate filters, params and lookup

        for field in address_fields:
            value = kwargs.get(field, None)
            if value and isinstance(value, list):
                value = value[0]
            if field != "country" and value:
                address.append(f"{value}")
            else:
                country = value

            params[field] = value

            if value:
                filters[field] = value
            else:
                filters[f"{field}__isnull"] = True

        # attempt to retrieve a valid cache

        cache = cls.objects.filter(**filters).order_by("-fetched").first()

        if cache:
            tdiff = timezone.now() - cache.fetched

            # check if cache is past expiry date, and expire it if so

            if tdiff.total_seconds() > settings.GEOCOORD_CACHE_EXPIRY:
                cache.delete()
                cache = None

        if not cache:
            # valid geo-coord cache does not exist, request coordinates
            # from google and create a cache entry

            address = " ".join(address)
            google = geo.GoogleMaps(settings.GOOGLE_GEOLOC_API_KEY)
            try:
                if params.get("address1"):
                    typ = "premise"
                elif params.get("zipcode"):
                    typ = "postal"
                elif params.get("city"):
                    typ = "city"
                elif params.get("state"):
                    typ = "state"
                else:
                    typ = "country"

                coords = google.geocode_address(address, country, typ=typ)
                cache = cls.objects.create(
                    latitude=coords["lat"], longitude=coords["lng"], **params
                )
            except geo.NotFound:
                # google could not find address
                # we still create a cache entry with null coordinates.

                cls.objects.create(**params)
                raise

        return {"longitude": cache.longitude, "latitude": cache.latitude}


@reversion.register()
class UserOrgAffiliationRequest(StripFieldMixin):
    """
    Whenever a user requests to be affiliated to an Organization
    through an ASN the request is stored in this object.

    When an ASN is entered that is not yet in the database it will
    notify PDB staff.

    When an ASN is entered that is already in the database the organization
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

    class Meta:
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
        Approve request and add user to org's usergroup.
        """

        if self.org_id:
            if self.user.is_org_admin(self.org) or self.user.is_org_member(self.org):
                self.delete()
                return

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

            self.track_approval()

            # since it was approved, we don't need to keep the
            # request item around
            self.status = "approved"
            self.delete()

    @reversion.create_revision()
    def track_approval(self):
        with current_request() as request:
            # reversion does not track object deletions directly (which is what happens
            # when the reuqest is approved, so we do a preliminary save to make sure a
            # revision is created for the approval action)
            if request:
                reversion.set_user(request.user)
            reversion.set_comment(
                f"Approval of affiliation request from {self.user.full_name} to {self.org} by {reversion.get_user()}"
            )
            self.status = "processing-approval"
            self.save()

    @reversion.create_revision()
    def deny(self):
        """
        Deny request, marks request as denied and keeps
        it around until requesting user deletes it.
        """

        if self.user and self.org:
            if self.user.is_org_admin(self.org) or self.user.is_org_member(self.org):
                self.delete()
                return

        with current_request() as request:
            if request:
                reversion.set_user(request.user)
            reversion.set_comment(
                f"Denial of affiliation request from {self.user.full_name} to {self.org} by {reversion.get_user()}"
            )

        self.status = "denied"
        self.save()

    def cancel(self):
        """
        Deny request, marks request as canceled and keeps
        it around until requesting user deletes it.
        """
        self.status = "canceled"
        self.save()

    def notify_ownership_approved(self):
        """
        Sends a notification email to the requesting user.
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
                        "org_url": urljoin(
                            settings.BASE_URL,
                            django.urls.reverse("org-view", args=(self.org.id,)),
                        ),
                        "support_email": settings.DEFAULT_FROM_EMAIL,
                    }
                ),
            )


class UserOrgAffiliationRequestHistory(Version, StripFieldMixin):
    """
    Proxy model for reversion Version to track changes in
    UserOrgAffiliationRequest objects in django-admin
    """

    class Meta:
        proxy = True
        verbose_name = _("User to Organization Affiliation Request History")
        verbose_name_plural = _("User to Organization Affiliation Request History")


class VerificationQueueItem(StripFieldMixin):
    """
    Keeps track of new items created that need to be reviewed and approved
    by administrators.

    Queue items are added through the create signals tied to the various
    objects (peeringdb_server/signals.py).
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
    org_key = models.ForeignKey(
        "peeringdb_server.OrganizationAPIKey",
        on_delete=models.CASCADE,
        related_name="vqitems",
        null=True,
        blank=True,
        help_text=_(
            "The item that this queue is attached to was created by this organization api key"
        ),
    )

    created = CreatedDateTimeField()
    notified = models.BooleanField(default=False)

    class Meta:
        db_table = "peeringdb_verification_queue"
        unique_together = (("content_type", "object_id"),)

    @classmethod
    def get_for_entity(cls, entity):
        """
        Returns verification queue item for the provided
        entity if it exists or raises a DoesNotExist
        exception.
        """

        return cls.objects.get(
            content_type=ContentType.objects.get_for_model(type(entity)),
            object_id=entity.id,
        )

    @property
    def item_admin_url(self):
        """
        Return admin url for the object in the verification queue.
        """
        return django.urls.reverse(
            "admin:%s_%s_change"
            % (self.content_type.app_label, self.content_type.model),
            args=(self.object_id,),
        )

    @property
    def approve_admin_url(self):
        """
        Return admin url for approval of the verification queue item.
        """
        return django.urls.reverse(
            f"admin:{self._meta.app_label}_{self._meta.model_name}_actions",
            args=(self.id, "vq_approve"),
        )

    @property
    def deny_admin_url(self):
        """
        Return admin url for denial of the verification queue item.
        """
        return django.urls.reverse(
            f"admin:{self._meta.app_label}_{self._meta.model_name}_actions",
            args=(self.id, "vq_deny"),
        )

    @reversion.create_revision()
    @transaction.atomic()
    def approve(self):
        """
        Approve the verification queue item.
        """
        if hasattr(self.item, "status"):
            self.item.status = "ok"
        if hasattr(self.item, "vq_approve"):
            self.item.vq_approve()

        self.item.save()

    def deny(self):
        """
        Deny the verification queue item.
        """
        if hasattr(self.item, "vq_deny"):
            self.item.vq_deny()
        else:
            if hasattr(self.item, "ref_tag"):
                self.item.delete(hard=True)
            else:
                self.item.delete()


class DeskProTicket(StripFieldMixin):
    subject = models.CharField(max_length=255)
    body = models.TextField()
    user = models.ForeignKey(
        "peeringdb_server.User", on_delete=models.CASCADE, null=True, blank=True
    )
    email = models.EmailField(_("email address"), null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    published = models.DateTimeField(null=True, blank=True)

    deskpro_ref = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text=_("Ticket reference on the DeskPRO side"),
    )

    deskpro_id = models.IntegerField(
        null=True, blank=True, help_text=_("Ticket id on the DeskPRO side")
    )

    class Meta:
        verbose_name = _("DeskPRO Ticket")
        verbose_name_plural = _("DeskPRO Tickets")


class DeskProTicketCC(StripFieldMixin):
    """
    Describes a contact to be cc'd on the deskpro ticket.
    """

    ticket = models.ForeignKey(
        DeskProTicket,
        on_delete=models.CASCADE,
        related_name="cc_set",
    )
    email = models.EmailField()

    class Meta:
        unique_together = (("ticket", "email"),)
        verbose_name = _("DeskPRO Ticket CC Contact")
        verbose_name_plural = _("Deskpro Ticket CC Contacts")


@grainy_model(namespace="peeringdb.organization")
@reversion.register
class Organization(
    ProtectedMixin,
    pdb_models.OrganizationBase,
    GeocodeBaseMixin,
    SocialMediaMixin,
    StripFieldMixin,
    ParentStatusCheckMixin,
):
    """
    Describes a peeringdb organization.
    """

    objects = CustomManager()

    # FIXME: change this to ImageField - keep
    # FileField for now as the server doesn't have all the
    # dependencies installedd (libjpeg / Pillow)
    logo = models.FileField(
        upload_to="logos_user_supplied/",
        null=True,
        blank=True,
        help_text=_(
            "Allows you to upload and set a logo image file for this organization"
        ),
    )

    # restrict users in the organization to be required
    # to have an email address at the domains specified in `email_domains`.
    restrict_user_emails = models.BooleanField(
        default=False,
        help_text=_(
            "Require users in your organization to have email addresses within your specified domains."
        ),
    )
    email_domains = models.TextField(
        null=True,
        blank=True,
        validators=[
            validate_email_domains,
        ],
        help_text=_(
            "If user email restriction is enabled: only allow users with emails in these domains. One domain per line, in the format of '@xyz.com'"
        ),
    )

    # require users in this organization to periodically reconfirm their
    # email addresses associated with the organization.

    periodic_reauth = models.BooleanField(
        default=False,
        help_text=_(
            "Require users in this organization to periodically re-authenticate"
        ),
    )
    periodic_reauth_period = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        choices=REAUTH_PERIODS,
        default="3m",
        help_text=_(
            "Range of options is available:\n"
            "1 Week, 2 Weeks, 1 Month, \n"
            "3 Month, 6 Month, 1 Year"
        ),
    )

    # Delete childless org objects #838
    # Flag any childless orgs for deletion
    flagged = models.BooleanField(
        null=True, blank=True, help_text="Flag the organization for deletion"
    )
    flagged_date = models.DateTimeField(
        null=True,
        blank=True,
        auto_now=False,
        auto_now_add=False,
        help_text="Date when the organization was flagged",
    )

    # restrict users in the organization to be required
    # to always activate 2FA.
    require_2fa = models.BooleanField(
        default=False,
        help_text=_("Require users in your organization to activate 2FA."),
    )
    last_notified = models.DateTimeField(
        null=True,
        blank=True,
        auto_now=False,
        auto_now_add=False,
        help_text="Date when the organization admins were notified about 2FA",
    )

    class Meta(pdb_models.OrganizationBase.Meta):
        indexes = [models.Index(fields=["status"], name="org_status")]

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
        Used by grappelli autocomplete for representation.

        Since grappelli doesn't easily allow one to filter status
        during autocomplete lookup, make sure the objects
        are marked accordingly in the result.
        """
        if self.status == "deleted":
            return f"[DELETED] {self}"
        return f"{self}"

    @property
    def email_domains_list(self):
        if not self.email_domains:
            return []
        return self.email_domains.split("\n")

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity.
        """
        return self.name

    @property
    def admin_url(self):
        """
        Return the admin URL for this organization (in /cp).
        """
        return django.urls.reverse(
            "admin:peeringdb_server_organization_change", args=(self.id,)
        )

    @property
    def view_url(self):
        """
        Return the URL to this organizations web view.
        """
        return urljoin(
            settings.BASE_URL, django.urls.reverse("org-view", args=(self.id,))
        )

    @property
    def deletable(self):
        """
        Returns whether or not the organization is currently
        in a state where it can be marked as deleted.

        This will be False for organizations of which ANY
        of the following is True:

        - has a network under it with status=ok
        - has a facility under it with status=ok
        - has an exchange under it with status=ok
        """

        is_empty = (
            self.ix_set_active.count() == 0
            and self.fac_set_active.count() == 0
            and self.net_set_active.count() == 0
        )

        if not is_empty:
            self._not_deletable_reason = _("Organization has active objects under it.")
            return False
        elif self.sponsorship and self.sponsorship.active:
            self._not_deletable_reason = _(
                "Organization is currently an active sponsor. "
                "Please contact PeeringDB support to help facilitate "
                "the removal of this organization."
            )
            return False
        else:
            self._not_deletable_reason = None
            return True

    @property
    def is_empty(self):
        """
        Returns whether or not the organization is empty

        An empty organization means an organization that does not
        have any objects with status ok or pending under it
        """

        return (
            not self.ix_set.filter(status__in=["ok", "pending"]).exists()
            and not self.fac_set.filter(status__in=["ok", "pending"]).exists()
            and not self.net_set.filter(status__in=["ok", "pending"]).exists()
        )

    @property
    def owned(self):
        """
        Returns whether or not the organization has been claimed
        by any users.
        """
        return self.admin_usergroup.user_set.count() > 0

    @property
    def rdap_collect(self):
        """
        Fetche rdap results for all networks under this org and returns
        them by asn.
        """
        r = {}
        for net in self.net_set_active:
            try:
                rdap = RdapLookup().get_asn(net.asn)
                if rdap:
                    r[net.asn] = rdap
            except RdapNotFoundError:
                pass
            except Exception as exc:
                logger.error(exc)
        return r

    @property
    def urls(self):
        """
        Returns all the websites for the org based on its
        website field and the website fields on all the entities it
        owns.
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
    def grainy_namespace_manage(self):
        """
        Org administrators need CRUD to this namespace in order
        to execute administrative actions (user management, user permission
        management).
        """
        return f"peeringdb.manage_organization.{self.id}"

    @property
    def pending_affiliations(self):
        """
        Returns queryset holding pending affiliations to this
        organization.
        """
        return self.affiliation_requests.filter(status="pending")

    @property
    def net_set_active(self):
        """
        Returns queryset holding active networks in this organization.
        """
        return self.net_set(manager="handleref").filter(status="ok")

    @property
    def fac_set_active(self):
        """
        Returns queryset holding active facilities in this organization.
        """
        return self.fac_set(manager="handleref").filter(status="ok")

    @property
    def ix_set_active(self):
        """
        Returns queryset holding active exchanges in this organization.
        """
        return self.ix_set(manager="handleref").filter(status="ok")

    @property
    def carrier_set_active(self):
        """
        Returns queryset holding active carrier in this organization.
        """
        return self.carrier_set(manager="handleref").filter(status="ok")

    @property
    def campus_set_active(self):
        """
        Returns queryset holding active campus in this organization.
        """
        return self.campus_set(manager="handleref").filter(status="ok")

    @property
    def group_name(self):
        """
        Returns usergroup name for this organization.
        """
        return "org.%s" % self.id

    @property
    def admin_group_name(self):
        """
        Returns admin usergroup name for this organization.
        """
        return "%s.admin" % self.group_name

    @property
    def usergroup(self):
        """
        Returns the usergroup for this organization.
        """
        return Group.objects.get(name=self.group_name)

    @property
    def admin_usergroup(self):
        """
        Returns the admin usergroup for this organization.
        """
        return Group.objects.get(name=self.admin_group_name)

    @property
    def all_users(self):
        """
        Returns a set of all users in the org's user and admin groups.
        """
        users = {}
        for user in self.usergroup.user_set.all():
            users[user.id] = user
        for user in self.admin_usergroup.user_set.all():
            users[user.id] = user

        return sorted(list(users.values()), key=lambda x: x.full_name)

    @property
    def sponsorship(self):
        """
        Returns sponsorship object for this organization. If the organization
        has no sponsorship ongoing return None.
        """
        now = datetime.datetime.now().replace(tzinfo=UTC())
        return (
            self.sponsorship_set.filter(start_date__lte=now, end_date__gte=now)
            .order_by("-start_date")
            .first()
        )

    @property
    def active_or_pending_sponsorship(self):
        """
        Returns sponsorship object for this organization. If the organization
        has no sponsorship ongoing or pending return None.
        """
        now = datetime.datetime.now().replace(tzinfo=UTC())
        return (
            self.sponsorship_set.filter(end_date__gte=now)
            .order_by("-start_date")
            .first()
        )

    @classmethod
    @reversion.create_revision()
    @transaction.atomic()
    def create_from_rdap(cls, rdap, asn, org_name=None):
        """
        Creates organization from rdap result object.
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

        # Remove users from user and admin usergroups
        aug = self.admin_usergroup.user_set
        for user in aug.all():
            aug.remove(user)
            user.save()

        ug = self.usergroup.user_set

        for user in ug.all():
            ug.remove(user)
            user.save()

    def reauth_period_to_days(self):
        m = re.match(r"(\d+)([dwmy])", self.periodic_reauth_period)

        num = int(m.group(1))
        unit = m.group(2)

        if unit == "d":
            return num
        if unit == "w":
            return num * 7
        if unit == "m":
            return num * 30
        if unit == "y":
            return num * 365

        raise ValueError("Invalid format")

    def user_meets_email_requirements(self, user) -> tuple[list, list]:
        """
        If organization has `restrict_user_emails` set to true
        this will check the specified user's email addresses against
        the values stored in `email_domains`.

        If the user has no email address that falls within the specified
        domain restrictions this will return `[]` and all associated user's email
        addresses in `List`.

        If the user has at least one email address that falls within the specified
        domain restrictions this will return all restricted email addresses in `List`
        and all associated user's email addresses in `List`.
        """

        email_list = list(
            EmailAddress.objects.filter(user=user)
            .order_by("-verified")
            .values_list("email", flat=True)
        )
        if not email_list:
            if not user.email:
                # currently its still possible to null a users email address
                # via django-admin / db and this is done in some edge cases where
                # user objects are created for internal operational purposes.
                #
                # For now just gracefully handle this case and return an empty
                return ([], [])
            email_list = [user.email]

        if not self.restrict_user_emails or not self.email_domains:
            return ([], email_list)

        email_domains = self.email_domains.split("\n")
        valid_email = []
        invalid_email = []
        for email in email_list:
            domain = email.split("@")[1]
            if f"{domain}".lower() in email_domains:
                valid_email.append(email)
            else:
                invalid_email.append(email)
        return (invalid_email, valid_email)

    def user_requires_reauth(self, user):
        """
        Returns whether the specified user requires re-authentication according
        to this organizations's periodic_reauth settings.
        """

        # re-auth is turned off either through django settings or on the org
        # itself.

        if not settings.PERIODIC_REAUTH_ENABLED or not self.periodic_reauth:
            return False

        # get best email address on the user's account for this org

        restricted_mail, email_list = self.user_meets_email_requirements(user)
        email_list += restricted_mail

        email = email_list[0]

        # will raise an error if not exists
        email = user.emailaddress_set.get(email=email)

        # check if the email address has been confirmed within the specified
        # period.
        #
        # Initiate re-confirmation process if needed.

        period = datetime.timedelta(days=self.reauth_period_to_days())

        try:
            email.data
            requires_reauth = email.data.confirmed_date + period <= timezone.now()
        except Exception:
            requires_reauth = True

        if not email.verified:
            requires_reauth = True

        if requires_reauth:
            if email.verified:
                # set email to be unverified so user needs to re-confirm it

                email.verified = False
                email.save()

                # send confirmation process to user

                user.send_email_confirmation(email=email.email)

            # keep track on user object which organizations are requesting
            # re-authentication to the user.

            if not hasattr(user, "orgs_require_reauth"):
                user.orgs_require_reauth = [(self, email.email)]
            else:
                user.orgs_require_reauth.append((self, email.email))

        return requires_reauth

    def adjust_permissions_for_periodic_reauth(self, user, perms):
        """
        Will strip users permission for the org if the org currently
        flags the user as needing re-authentication
        """

        if self.user_requires_reauth(user):
            for namespace in list(perms.pset.namespaces):
                if f"peeringdb.organization.{self.id}." in namespace:
                    del perms.pset[namespace]


def default_time_s():
    """
    Returns datetime set to today with a time of 00:00:00.
    """
    now = datetime.datetime.now()
    return now.replace(hour=0, minute=0, second=0, tzinfo=UTC())


def default_time_e():
    """
    Returns datetime set to today with a time of 23:59:59.
    """
    now = datetime.datetime.now()
    return now.replace(hour=23, minute=59, second=59, tzinfo=UTC())


class OrganizationAPIKey(AbstractAPIKey, StripFieldMixin):
    """
    An API Key managed by an organization.
    """

    org = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    email = models.EmailField(
        _("email address"), max_length=254, null=False, blank=False
    )

    status = models.CharField(max_length=16, choices=API_KEY_STATUS, default="active")

    class Meta(AbstractAPIKey.Meta):
        verbose_name = "Organization API key"
        verbose_name_plural = "Organization API keys"
        db_table = "peeringdb_org_api_key"


class OrganizationAPIPermission(Permission, StripFieldMixin):
    """
    Describes permission for a OrganizationAPIKey.
    """

    class Meta:
        verbose_name = _("Organization API key Permission")
        verbose_name_plural = _("Organization API key Permission")
        base_manager_name = "objects"

    org_api_key = models.ForeignKey(
        OrganizationAPIKey, related_name="grainy_permissions", on_delete=models.CASCADE
    )
    objects = PermissionManager()


class Sponsorship(StripFieldMixin):
    """
    Allows an organization to be marked for sponsorship
    for a designated timespan.
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
        active sponsorships.
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
        return self.start_date <= now and self.end_date >= now

    @property
    def label(self):
        """
        Returns the label for this sponsorship's level.
        """
        return dict(SPONSORSHIP_LEVELS).get(self.level)

    @property
    def css(self):
        """
        Returns the css class for this sponsorship's level
        """
        return dict(SPONSORSHIP_CSS).get(self.level)

    def __str__(self):
        return f"Sponsorship ID#{self.id} {self.start_date} - {self.end_date}"

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

        self.notify_date = datetime.datetime.now(tz=datetime.timezone.utc)
        self.save()

        return True


class SponsorshipOrganization(StripFieldMixin):
    """
    Describes an organization->sponsorship relationship.
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


class Partnership(StripFieldMixin):
    """
    Allows an organization to be marked as a partner.

    It will appear on the "partners" page.
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


class OrganizationMerge(StripFieldMixin):
    """
    When an organization is merged into another via admin.merge_organizations
    it is logged here, allowing the merge to be undone.
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
        Mark an entity as moved during this particular merge.

        Entity can be any handleref instance or a User instance.
        """

        return OrganizationMergeEntity.objects.create(
            merge=self, entity=entity, note=note
        )

    def undo(self):
        """
        Undo this merge.
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
            elif isinstance(entity, User):
                # move user entity
                group = getattr(self.from_org, row.note)
                group.user_set.add(entity)

                self.to_org.usergroup.user_set.remove(entity)
                self.to_org.admin_usergroup.user_set.remove(entity)
            elif isinstance(entity, Sponsorship):
                # reapply sponsorhip
                entity.orgs.remove(self.to_org)
                entity.orgs.add(self.from_org)

        self.delete()


class OrganizationMergeEntity(StripFieldMixin):
    """
    This holds the entities moved during an
    organization merge stored in OrganizationMerge.
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


@grainy_model(namespace="campus", parent="org")
@reversion.register
# TODO: UNCOMMENT when #389 is merged
# class Campus(ProtectedMixin, pdb_models.CampusBase, ParentStatusMixin):
class Campus(
    ProtectedMixin,
    pdb_models.CampusBase,
    SocialMediaMixin,
    StripFieldMixin,
):
    """
    Describes a peeringdb campus
    """

    org = models.ForeignKey(
        Organization,
        related_name="campus_set",
        verbose_name=_("Organization"),
        on_delete=models.CASCADE,
    )

    parent_relations = ["org"]

    def save(self, *args, **kwargs):
        """
        Save the current instance
        """
        # TODO: UNCOMMENT when #389 is merged
        # self.validate_parent_status()
        super().save(*args, **kwargs)

    @classmethod
    def related_to_facility(cls, value=None, filt=None, field="fac_set__id", qset=None):
        """
        Filter queryset of campus objects related to facilities with name match
        in fac_set__id according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.undeleted()

        return qset.filter(**make_relation_filter(field, filt, value))

    @property
    def city(self):
        """
        Return city of related facility object
        """
        if self.fac_set.exists():
            return self.fac_set.first().city
        return ""

    @property
    def country(self):
        """
        Return country of related facility object
        """
        if self.fac_set.exists():
            return self.fac_set.first().country
        return ""

    @property
    def state(self):
        """
        Return state of related facility object
        """
        if self.fac_set.exists():
            return self.fac_set.first().state
        return ""

    @property
    def zipcode(self):
        """
        Return zipcode of related facility object
        """
        if self.fac_set.exists():
            return self.fac_set.first().zipcode
        return ""

    @property
    def latitude(self):
        """
        Return latitude of related facility object
        """
        if self.fac_set.exists():
            return self.fac_set.first().latitude
        return ""

    @property
    def longitude(self):
        """
        Return longitude of related facility object
        """
        if self.fac_set.exists():
            return self.fac_set.first().longitude
        return ""

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity.
        """
        return self.name

    @property
    def view_url(self):
        """
        Return the URL to this campus's web view.
        """
        return urljoin(
            settings.BASE_URL, django.urls.reverse("campus-view", args=(self.id,))
        )


@grainy_model(namespace="facility", parent="org")
@reversion.register
class Facility(
    ProtectedMixin,
    pdb_models.FacilityBase,
    GeocodeBaseMixin,
    ParentStatusCheckMixin,
    SocialMediaMixin,
    StripFieldMixin,
):
    """
    Describes a peeringdb facility.
    """

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="fac_set"
    )
    campus = models.ForeignKey(
        Campus,
        related_name="fac_set",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    # TODO: why are we redefining this, seems same as the one
    # defined in django-peeringdb
    website = models.URLField(_("Website"), blank=True, default="")

    ix_count = models.PositiveIntegerField(
        _("number of exchanges at this facility"),
        help_text=_("number of exchanges at this facility"),
        null=False,
        default=0,
    )
    net_count = models.PositiveIntegerField(
        _("number of networks at this facility"),
        help_text=_("number of networks at this facility"),
        null=False,
        default=0,
    )

    notified_for_geocoords = models.BooleanField(
        default=False,
        help_text="Indicates whether the facility has been notified to update their geocoordinates.",
    )

    # FIXME: delete cascade needs to be fixed in django-peeringdb, can remove
    # this afterwards
    class HandleRef:
        tag = "fac"
        delete_cascade = ["ixfac_set", "netfac_set"]

    parent_relations = ["org"]

    class Meta(pdb_models.FacilityBase.Meta):
        indexes = [models.Index(fields=["status"], name="fac_status")]

    def save(self, *args, **kwargs):
        """
        Save the current instance
        """
        self.validate_parent_status()
        super().save(*args, **kwargs)

    @staticmethod
    def autocomplete_search_fields():
        """
        Returns a tuple of field query strings to be used during quick search
        query.
        """
        return (
            "id__iexact",
            "name__icontains",
        )

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
    def not_related_to_net(cls, value=None, filt=None, field="network_id", qset=None):
        """
        Returns queryset of Facility objects that
        are related to the network specified via net_id

        Relationship through netfac -> net
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)

        q = NetworkFacility.handleref.filter(**filt)
        return qset.exclude(id__in=[i.facility_id for i in q])

    @classmethod
    def related_to_multiple_networks(
        cls, value_list=None, field="network_id", qset=None
    ):
        """
        Returns queryset of Facility objects that
        are related to ALL networks specified in the value list
        (a list of integer network ids).

        Used in Advanced Search (ALL search).
        Relationship through netfac -> net
        """
        if not len(value_list):
            raise ValueError("List must contain at least one network id")

        if not qset:
            qset = cls.handleref.undeleted()

        value = value_list.pop(0)
        filt = make_relation_filter(field, None, value)
        netfac_qset = NetworkFacility.handleref.filter(**filt)
        final_queryset = qset.filter(id__in=[nf.facility_id for nf in netfac_qset])

        # Need the intersection of the next networks
        for value in value_list:
            filt = make_relation_filter(field, None, value)
            netfac_qset = NetworkFacility.handleref.filter(**filt)
            fac_qset = qset.filter(id__in=[nf.facility_id for nf in netfac_qset])
            final_queryset = final_queryset & fac_qset

        return final_queryset

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
    def not_related_to_ix(cls, value=None, filt=None, field="ix_id", qset=None):
        """
        Returns queryset of Facility objects that
        are related to the ixwork specified via ix_id

        Relationship through ixfac -> ix
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)

        q = InternetExchangeFacility.handleref.filter(**filt)
        return qset.exclude(id__in=[i.facility_id for i in q])

    @classmethod
    def overlapping_asns(cls, asns, qset=None):
        """
        Returns queryset of Facility objects
        that have a relationship to all asns specified in `asns`

        Relationship through netfac.

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
    def sponsorship(self):
        """
        Returns sponsorship oject for this facility (through the owning org).
        """
        return self.org.sponsorship

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity.
        """
        return self.name

    @property
    def netfac_set_active(self):
        """
        Returns queryset of active NetworkFacility objects connected to this
        facility.
        """
        return self.netfac_set.filter(status="ok")

    @property
    def ixfac_set_active(self):
        """
        Returns queryset of active InternetExchangeFacility objects connected
        to this facility.
        """
        return self.ixfac_set.filter(status="ok")

    @property
    def carrierfac_set_active(self):
        """
        Returns queryset of active CarrierFacility objects connected
        to this facility.
        """
        return self.carrierfac_set.filter(status="ok")

    @property
    def view_url(self):
        """
        Return the URL to this facility's web view.
        """
        return urljoin(
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
            facility_names = ", ".join(
                [ixfac.ix.name for ixfac in self.ixfac_set_active.all()[:5]]
            )
            self._not_deletable_reason = _(
                "Facility has active exchange presence(s): {} ..."
            ).format(facility_names)
            return False
        elif self.netfac_set_active.exists():
            network_names = ", ".join(
                [netfac.network.name for netfac in self.netfac_set_active.all()[:5]]
            )
            self._not_deletable_reason = _(
                "Facility has active network presence(s): {} ..."
            ).format(network_names)
            return False
        else:
            self._not_deletable_reason = None
            return True

    def validate_phonenumbers(self):
        try:
            self.tech_phone = validate_phonenumber(self.tech_phone, self.country.code)
        except ValidationError as exc:
            raise ValidationError({"tech_phone": exc})

        try:
            self.sales_phone = validate_phonenumber(self.sales_phone, self.country.code)
        except ValidationError as exc:
            raise ValidationError({"sales_phone": exc})


@grainy_model(namespace="internetexchange", parent="org")
@reversion.register
class InternetExchange(
    ProtectedMixin,
    pdb_models.InternetExchangeBase,
    ParentStatusCheckMixin,
    SocialMediaMixin,
    StripFieldMixin,
):
    """
    Describes a peeringdb exchange.
    """

    ixf_import_request = models.DateTimeField(
        _("Manual IX-F import request"),
        help_text=_("Date of most recent manual import request"),
        null=True,
        blank=True,
    )

    ixf_import_request_status = models.CharField(
        _("Manual IX-F import status"),
        help_text=_("The current status of the manual IX-F import request"),
        choices=(
            ("queued", _("Queued")),
            ("importing", _("Importing")),
            ("finished", _("Finished")),
            ("error", _("Import failed")),
        ),
        max_length=32,
        default="queued",
    )

    ixf_import_request_user = models.ForeignKey(
        "peeringdb_server.User",
        null=True,
        blank=True,
        help_text=_("The user that triggered the manual IX-F import request"),
        on_delete=models.SET_NULL,
        related_name="requested_ixf_imports",
    )

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="ix_set"
    )

    fac_count = models.PositiveIntegerField(
        _("number of facilities at this exchange"),
        help_text=_("number of facilities at this exchange"),
        null=False,
        default=0,
    )

    net_count = models.PositiveIntegerField(
        _("number of networks at this exchange"),
        help_text=_("number of networks at this exchange"),
        null=False,
        default=0,
    )

    class Meta(pdb_models.InternetExchangeBase.Meta):
        indexes = [models.Index(fields=["status"], name="ix_status")]

    parent_relations = ["org"]

    @staticmethod
    def autocomplete_search_fields():
        """
        Returns a tuple of field query strings to be used during quick search
        query.
        """
        return (
            "id__iexact",
            "name__icontains",
        )

    def __unicode__(self):
        return self.name

    def peer_exists_in_ixf_data(self, asn, ipaddr4, ipaddr6):
        """
        Checks if the combination of ip-address and asn exists
        in the internet exchange's IX-F data.

        Arguments:

        - asn (`int`)
        - ipaddr4 (`str`|`ipaddress.ip_address`)
        - ipaddr6 (`str`|`ipaddress.ip_address`)
        """

        url = self.ixlan.ixf_ixp_member_list_url

        if not url:
            # IX-F url not specified
            return (False, False)

        ixf_data = cache.get(f"IXF-CACHE-{url}")

        if not ixf_data:
            # IX-F cache doesnt exist
            return (False, False)

        ipaddr4_exists = False
        ipaddr6_exists = False

        if ipaddr4:
            ipaddr4 = ipaddress.ip_address(ipaddr4)

        if ipaddr6:
            ipaddr6 = ipaddress.ip_address(ipaddr6)

        for member in ixf_data.get("member_list") or []:
            if member.get("asnum") != asn:
                continue

            for connection in member.get("connection_list") or []:
                for vlan in connection.get("vlan_list") or []:
                    ixf_ip4 = (vlan.get("ipv4") or {}).get("address")
                    ixf_ip6 = (vlan.get("ipv6") or {}).get("address")

                    if ipaddr4 and ixf_ip4 and ipaddr4 == ipaddress.ip_address(ixf_ip4):
                        ipaddr4_exists = True

                    if ipaddr6 and ixf_ip6 and ipaddr6 == ipaddress.ip_address(ixf_ip6):
                        ipaddr6_exists = True

            if (not ipaddr4 or ipaddr4_exists) and (not ipaddr6 or ipaddr6_exists):
                break

        return (ipaddr4_exists, ipaddr6_exists)

    @classmethod
    def related_to_ixlan(cls, value=None, filt=None, field="ixlan_id", qset=None):
        """
        Returns queryset of InternetExchange objects that
        are related to IXLan specified by ixlan_id

        Relationship through ixlan.
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

        Relationship through ixfac.
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
    def related_to_multiple_networks(
        cls, value_list=None, field="network_id", qset=None
    ):
        """
        Returns queryset of InternetExchange objects that
        are related to ALL networks specified in the value list
        (a list of integer network ids).

        Used in Advanced Search (ALL search).
        Relationship through netixlan -> ixlan
        """
        if not len(value_list):
            raise ValueError("List must contain at least one network id")

        if not qset:
            qset = cls.handleref.undeleted()

        value = value_list.pop(0)
        filt = make_relation_filter(field, None, value)
        netixlan_qset = NetworkIXLan.handleref.filter(**filt).select_related("ixlan")
        final_queryset = qset.filter(id__in=[nx.ixlan.ix_id for nx in netixlan_qset])

        # Need the intersection of the next networks
        for value in value_list:
            filt = make_relation_filter(field, None, value)
            netixlan_qset = NetworkIXLan.handleref.filter(**filt).select_related(
                "ixlan"
            )
            ix_qset = qset.filter(id__in=[nx.ixlan.ix_id for nx in netixlan_qset])
            final_queryset = final_queryset & ix_qset

        return final_queryset

    @classmethod
    def not_related_to_net(cls, filt=None, value=None, field="network_id", qset=None):
        """
        Returns queryset of InternetExchange objects that
        are not related to the network specified by network_id

        Relationship through netixlan -> ixlan
        """

        if not qset:
            qset = cls.handleref.undeleted()

        filt = make_relation_filter(field, filt, value)
        q = NetworkIXLan.handleref.filter(**filt).select_related("ixlan")
        return qset.exclude(id__in=[nx.ixlan.ix_id for nx in q])

    @classmethod
    def related_to_ipblock(cls, ipblock, qset=None):
        """
        Returns queryset of InternetExchange objects that
        have ixlan prefixes matching the ipblock specified.

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
    def filter_capacity(cls, filt=None, value=None, qset=None):
        """
        Returns queryset of InternetExchange objects filtered by capacity
        in mbits.

        Arguments:

        - filt (`str`|`None`): match operation, None meaning exact match
          - 'gte': greater than equal
          - 'lte': less than equal
          - 'gt': greater than
          - 'lt': less than
        - value(`int`): capacity to filter in mbits
        - qset(`InternetExchange`): if specified will filter ontop of
          this existing query set
        """

        if not qset:
            qset = cls.handleref.undeleted()

        # prepar field filters

        if filt:
            filters = {f"capacity__{filt}": value}
        else:
            filters = {"capacity": value}

        # find exchanges that have the matching capacity
        # exchange capacity is simply the sum of its port speeds

        netixlans = NetworkIXLan.handleref.undeleted()
        capacity_set = (
            netixlans.values("ixlan_id")
            .annotate(capacity=models.Sum("speed"))
            .filter(**filters)
        )

        # collect ids
        # since ixlan id == exchange id we can simply use those

        qualifying = [c["ixlan_id"] for c in capacity_set]

        # finally limit the queryset by the ix (ixlan) ids that matched
        # the capacity filter

        qset = qset.filter(id__in=qualifying)
        return qset

    @classmethod
    def ixf_import_request_queue(cls, limit=0):
        qset = (
            InternetExchange.objects.filter(
                ixf_import_request__isnull=False, ixf_import_request_status="queued"
            )
            .exclude(
                models.Q(ixlan_set__ixf_ixp_member_list_url__isnull=True)
                | models.Q(ixlan_set__ixf_ixp_member_list_url="")
            )
            .order_by("ixf_import_request")
        )

        if limit:
            qset = qset[:limit]

        return qset

    @property
    def ixlan(self):
        """
        Returns the ixlan for this exchange.

        As per #21, each exchange will get one ixlan with a matching
        id, but the schema is to remain unchanged until a major
        version bump.
        """
        return self.ixlan_set.first()

    @property
    def networks(self):
        """
        Returns all active networks at this exchange.
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
        of this entity.
        """
        return self.name

    @property
    def ixlan_set_active(self):
        """
        Returns queryset of active ixlan objects at this exchange.
        """
        return self.ixlan_set(manager="handleref").filter(status="ok")

    @property
    def ixlan_set_active_or_pending(self):
        """
        Returns queryset of active or pending ixlan objects at
        this exchange.
        """
        return self.ixlan_set(manager="handleref").filter(status__in=["ok", "pending"])

    @property
    def ixfac_set_active(self):
        """
        Returns queryset of active ixfac objects at this exchange.
        """
        return (
            self.ixfac_set(manager="handleref")
            .select_related("facility")
            .filter(status="ok")
        )

    @property
    def sponsorship(self):
        """
        Returns sponsorship object for this exchange (through owning org).
        """
        return self.org.sponsorship

    @property
    def view_url(self):
        """
        Return the URL to this facility's web view.
        """
        return urljoin(
            settings.BASE_URL, django.urls.reverse("ix-view", args=(self.id,))
        )

    @property
    def derived_proto_unicast(self):
        """
        Returns a value for "proto_unicast" derived from the exchanges's
        ixpfx records.

        If the ix has a IPv4 ixpfx, proto_unicast should be True.
        """
        return self.ixlan.ixpfx_set_active.filter(protocol="IPv4").exists()

    @property
    def derived_proto_ipv6(self):
        """
        Returns a value for "proto_ipv6" derived from the exchanges's
        ixpfx records.

        If the ix has a IPv6 ixpfx, proto_ipv6 should be True.
        """
        return self.ixlan.ixpfx_set_active.filter(protocol="IPv6").exists()

    @property
    def derived_network_count(self):
        """
        Returns an ad hoc count of networks attached to an Exchange.
        Used in the deletable property to ensure an accurate count
        even if net_count signals are not being used.
        """
        return (
            NetworkIXLan.objects.select_related("network")
            .filter(ixlan__ix_id=self.id, status="ok")
            .aggregate(net_count=models.Count("network_id", distinct=True))["net_count"]
        )

    @property
    def deletable(self):
        """
        Returns whether or not the exchange is currently
        in a state where it can be marked as deleted.

        This will be False for exchanges of which ANY
        of the following is True:

        - has netixlans connected to it
        - ixfac relationship
        """

        if self.ixfac_set_active.exists():
            facility_names = ", ".join(
                [ixfac.facility.name for ixfac in self.ixfac_set_active.all()[:5]]
            )
            self._not_deletable_reason = _(
                "Exchange has active facility connection(s): {} ..."
            ).format(facility_names)
            return False
        elif self.derived_network_count > 0:
            self._not_deletable_reason = _("Exchange has active peer(s)")
            return False
        else:
            self._not_deletable_reason = None
            return True

    @property
    def ixf_import_request_recent_status(self):
        """
        Returns the recent ixf import request status as a tuple
        of value, display.
        """

        if not self.ixf_import_request:
            return "", ""

        value = self.ixf_import_request_status
        display = self.get_ixf_import_request_status_display

        if self.ixf_import_request_status == "queued":
            return value, display

        now = timezone.now()
        delta = (now - self.ixf_import_request).total_seconds()

        if delta < 3600:
            return value, display

        return "", ""

    @property
    def ixf_import_css(self):
        """
        Returns the appropriate bootstrap alert class
        depending on recent import request status.
        """
        status, _ = self.ixf_import_request_recent_status
        if status == "queued":
            return "alert alert-warning"
        if status == "finished":
            return "alert alert-success"
        if status == "error":
            return "alert alert-danger"
        return ""

    def vq_approve(self):
        """
        Called when internet exchange is approved in verification
        queue.
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
        exists.

        Keyword Argument(s):

        - create_ixlan (`bool`=True): if True and the ix is missing
          its ixlan, create it
        """

        self.validate_parent_status()

        r = super().save(**kwargs)

        ixlan = self.ixlan

        if not ixlan and create_ixlan:
            ixlan = IXLan(ix=self, status=self.status)

            # ixlan id will be set to match ix id in ixlan's clean()
            # call
            ixlan.clean()

            ixlan.save()

        elif ixlan and ixlan.status != self.status:
            # ixlan status should always be identical to ix status (#1077)
            if self.status == "deleted":
                ixlan.delete()
            else:
                ixlan.status = self.status
                ixlan.save()

        return r

    def validate_phonenumbers(self):
        try:
            self.tech_phone = validate_phonenumber(self.tech_phone, self.country.code)
        except ValidationError as exc:
            raise ValidationError({"tech_phone": exc})

        try:
            self.sales_phone = validate_phonenumber(self.sales_phone, self.country.code)
        except ValidationError as exc:
            raise ValidationError({"sales_phone": exc})

        try:
            self.policy_phone = validate_phonenumber(
                self.policy_phone, self.country.code
            )
        except ValidationError as exc:
            raise ValidationError({"policy_phone": exc})

    def clean(self):
        self.validate_phonenumbers()
        super().clean()

    def request_ixf_import(self, user=None):
        self.ixf_import_request = timezone.now()

        if self.ixf_import_request_status == "importing":
            raise ValidationError({"non_field_errors": ["Import is currently ongoing"]})

        self.ixf_import_request_status = "queued"
        self.ixf_import_request_user = user

        self.save_without_timestamp()


@grainy_model(namespace="ixfac", parent="ix")
@reversion.register
class InternetExchangeFacility(
    pdb_models.InternetExchangeFacilityBase, ParentStatusCheckMixin, StripFieldMixin
):
    """
    Describes facility to exchange relationship.
    """

    ix = models.ForeignKey(
        InternetExchange, on_delete=models.CASCADE, related_name="ixfac_set"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, default=0, related_name="ixfac_set"
    )

    parent_relations = ["ix", "facility"]

    @classmethod
    def related_to_name(cls, value=None, filt=None, field="facility__name", qset=None):
        """
        Filter queryset of ixfac objects related to facilities with name match
        in facility__name according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.undeleted()
        return qset.filter(**make_relation_filter(field, filt, value))

    @classmethod
    def related_to_country(
        cls, value=None, filt=None, field="facility__country", qset=None
    ):
        """
        Filter queryset of ixfac objects related to country via match
        in facility__country according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.filter(status="ok")
        return qset.filter(**make_relation_filter(field, filt, value))

    @classmethod
    def related_to_city(cls, value=None, filt=None, field="facility__city", qset=None):
        """
        Filter queryset of ixfac objects related to city via match
        in facility__city according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.undeleted()
        return qset.filter(**make_relation_filter(field, filt, value))

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the ixfac for logging purposes.
        """
        return f"ixfac{self.id} {self.ix.name} <-> {self.facility.name}"

    class Meta:
        unique_together = ("ix", "facility")
        db_table = "peeringdb_ix_facility"

    def save(self, *args, **kwargs):
        """
        Save the current instance
        """
        self.validate_parent_status()
        super().save(*args, **kwargs)


@grainy_model(namespace="ixlan", namespace_instance="{instance.ix.grainy_namespace}")
@reversion.register
class IXLan(pdb_models.IXLanBase, StripFieldMixin):
    """
    Describes a LAN at an exchange.
    """

    # as we are preparing to drop IXLans from the schema, as an interim
    # step (#21) we are giving each ix one ixlan with matching ids, so we need
    # to have an id field that doesnt automatically increment
    id = models.IntegerField(primary_key=True)

    ix = models.ForeignKey(
        InternetExchange, on_delete=models.CASCADE, default=0, related_name="ixlan_set"
    )

    # IX-F import fields

    ixf_ixp_import_enabled = models.BooleanField(default=False)
    ixf_ixp_import_error = models.TextField(
        _("IX-F error"),
        blank=True,
        null=True,
        help_text=_("Reason IX-F data could not be parsed"),
    )
    ixf_ixp_import_error_notified = models.DateTimeField(
        _("IX-F error notification date"),
        help_text=_("Last time we notified the exchange about the IX-F parsing issue"),
        null=True,
        blank=True,
    )
    ixf_ixp_import_protocol_conflict = models.IntegerField(
        _("IX-F sent IPs for unsupported protocol"),
        help_text=_(
            "IX has been sending IP addresses for protocol not supported by network"
        ),
        null=True,
        blank=True,
        default=0,
    )

    # FIXME: delete cascade needs to be fixed in django-peeringdb, can remove
    # this afterwards
    class HandleRef:
        tag = "ixlan"
        delete_cascade = ["ixpfx_set", "netixlan_set"]

    class Meta:
        db_table = "peeringdb_ixlan"

    @classmethod
    def api_cache_permissions_applicator(cls, row, ns, permission_holder):
        """
        Applies permissions to a row in an api-cache result
        set for ixlan.

        This will strip `ixf_ixp_member_list_url` fields for
        users / api keys that don't have read permissions for them according
        to `ixf_ixp_member_list_url_visible`

        Argument(s):

        - row (dict): ixlan row from api-cache result
        - ns (str): ixlan namespace as determined during api-cache
          result rendering
        - permission_holder (User or API Key)
        """

        visible = row.get("ixf_ixp_member_list_url_visible").lower()
        if not permission_holder and visible == "public":
            return
        namespace = f"{ns}.ixf_ixp_member_list_url.{visible}"

        if not check_permissions(permission_holder, namespace, "r", explicit=True):
            try:
                del row["ixf_ixp_member_list_url"]
            except KeyError:
                pass

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the ixlan for logging purposes.
        """
        return f"ixlan{self.id} {self.ix.name}"

    @property
    def ixpfx_set_active(self):
        """
        Returns queryset of active prefixes at this ixlan.
        """
        return self.ixpfx_set(manager="handleref").filter(status="ok")

    @property
    def ixpfx_set_active_or_pending(self):
        """
        Returns queryset of active or pending prefixes at this ixlan.
        """
        return self.ixpfx_set(manager="handleref").filter(status__in=["ok", "pending"])

    @property
    def netixlan_set_active(self):
        """
        Returns queryset of active netixlan objects at this ixlan.
        """
        return (
            self.netixlan_set(manager="handleref")
            .select_related("network")
            .filter(status="ok")
        )
        # q = NetworkIXLan.handleref.filter(ixlan_id=self.id).filter(status="ok")
        # return Network.handleref.filter(id__in=[i.network_id for i in
        # q]).filter(status="ok")

    @property
    def ready_for_ixf_import(self):
        """
        Returns True if IX-F data is ready to be imported.
        """
        return self.ixf_ixp_import_enabled and self.ixf_ixp_member_list_url

    @property
    def view_url(self):
        """
        Return the URL to related networks web view.
        """
        return urljoin(
            settings.BASE_URL, django.urls.reverse("ix-view", args=(self.ix_id,))
        )

    @staticmethod
    def autocomplete_search_fields():
        """
        Used by grappelli autocomplete to determine what
        fields to search in.
        """
        return ("ix__name__icontains",)

    def related_label(self):
        """
        Used by grappelli autocomplete for representation.
        """
        return f"{self.ix.name} IXLan ({self.id})"

    def test_ipv4_address(self, ipv4):
        """
        Test that the ipv4 a exists in one of the prefixes in this ixlan.
        """
        for pfx in self.ixpfx_set_active:
            if pfx.test_ip_address(ipv4):
                return True
        return False

    def test_ipv6_address(self, ipv6):
        """
        Test that the ipv6 address exists in one of the prefixes in this ixlan.
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

        if self.ixf_ixp_member_list_url is None and self.ixf_ixp_import_enabled:
            raise ValidationError(
                _(
                    "Cannot enable IX-F import without specifying the IX-F member list url"
                )
            )

        return super().clean()

    @reversion.create_revision()
    @transaction.atomic()
    def add_netixlan(self, netixlan_info, save=True, save_others=True):
        """
        This function allows for sane adding of netixlan object under
        this ixlan.

        It will take into account whether an ipaddress can be claimed from a
        soft-deleted netixlan or whether an object already exists
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
        if ipv4 and not ipv4_valid:
            raise ValidationError(
                {"ipaddr4": f"IPv4 {ipv4} does not match any prefix on this ixlan"}
            )
        if ipv6 and not ipv6_valid:
            raise ValidationError(
                {"ipaddr6": f"IPv6 {ipv6} does not match any prefix on this ixlan"}
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
            raise ValidationError(
                {"ipaddr4": f"Ip address {ipv4} already exists in another lan"}
            )

        if (
            ipv6
            and NetworkIXLan.objects.filter(status="ok", ipaddr6=ipv6)
            .exclude(ixlan=self)
            .count()
            > 0
        ):
            raise ValidationError(
                {"ipaddr6": f"Ip address {ipv6} already exists in another lan"}
            )

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

        # now we sync the data to our determined netixlan instance

        # IPv4
        if ipv4 != netixlan.ipaddr4:
            # we need to check if this ipaddress exists on a
            # soft-deleted netixlan elsewhere, and
            # reset if so.
            #
            # we only do this if ipaddr4 is not null

            if ipv4:
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
            #
            # we only do this if ipaddr6 is not None

            if ipv6:
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

        # Is the netixlan operational?
        if netixlan_info.operational != netixlan.operational:
            netixlan.operational = netixlan_info.operational
            changed.append("operational")

        # Speed
        if netixlan_info.speed != netixlan.speed and (
            netixlan_info.speed >= 0 or netixlan.speed is None
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

        if save and (changed or netixlan.status == "deleted"):
            netixlan.status = "ok"
            netixlan.full_clean()
            netixlan.save()

        return result(netixlan)


class IXLanIXFMemberImportAttempt(StripFieldMixin):
    """
    Holds information about the most recent ixf member import
    attempt for an ixlan.
    """

    ixlan = models.OneToOneField(
        IXLan,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="ixf_import_attempt",
    )
    updated = models.DateTimeField(auto_now=True)
    info = models.TextField(null=True, blank=True)


class IXLanIXFMemberImportLog(StripFieldMixin):
    """
    Import log of a IX-F member import that changed or added at least one
    netixlan under the specified ixlans.
    """

    ixlan = models.ForeignKey(
        IXLan, on_delete=models.CASCADE, related_name="ixf_import_log_set"
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("IX-F Import Log")
        verbose_name_plural = _("IX-F Import Logs")

    @reversion.create_revision()
    @transaction.atomic()
    def rollback(self):
        """
        Attempt to rollback the changes described in this log.
        """

        for entry in self.entries.all().order_by("-id"):
            if entry.rollback_status() == 0:
                if entry.version_before:
                    entry.version_before.revert()
                    related = self.entries.filter(
                        netixlan=entry.netixlan,
                    ).exclude(id=entry.id)
                    for _entry in related.order_by("-id"):
                        try:
                            _entry.version_before.revert()
                        except Exception:
                            break

                elif entry.netixlan.status == "ok":
                    entry.netixlan.ipaddr4 = None
                    entry.netixlan.ipaddr6 = None
                    entry.netixlan.delete()


class IXLanIXFMemberImportLogEntry(StripFieldMixin):
    """
    IX-F member import log entry that holds the affected netixlan and
    the netixlan's version after the change, which can be used to rollback
    the change.
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

    class Meta:
        verbose_name = _("IX-F Import Log Entry")
        verbose_name_plural = _("IX-F Import Log Entries")

    @property
    def changes(self):
        """
        Returns a dict of changes between the netixlan version
        saved by the IX-F import and the version before.

        Fields `created`, `updated` and `version` will be ignored.
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


class NetworkProtocolsDisabled(ValueError):
    """
    Raised when a network has both ipv6 and ipv4 support
    disabled during IX-F import.
    """


class IXFMemberData(pdb_models.NetworkIXLanBase, StripFieldMixin):
    """
    Describes a potential data update that arose during an IX-F import
    attempt for a specific member (asn, ip4, ip6) to netixlan
    (asn, ip4, ip6) where the importer could not complete the
    update automatically.
    """

    data = models.TextField(
        null=False,
        default="{}",
        help_text=_("JSON snapshot of the IX-F member data that " "created this entry"),
    )

    log = models.TextField(blank=True, help_text=_("Activity for this entry"))

    dismissed = models.BooleanField(
        default=False,
        help_text=_(
            "Network's dismissal of this proposed change, which will hide it until"
            " from the customer facing network view"
        ),
    )

    is_rs_peer = models.BooleanField(
        default=None, null=True, blank=True, help_text=_("RS Peer")
    )

    error = models.TextField(
        null=True,
        blank=True,
        help_text=_("Trying to apply data to peeringdb raised an issue"),
    )
    reason = models.CharField(max_length=255, default="")

    fetched = models.DateTimeField(
        _("Last Fetched"),
    )

    ixlan = models.ForeignKey(IXLan, related_name="ixf_set", on_delete=models.CASCADE)

    requirement_of = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="requirement_set",
        null=True,
        blank=True,
        help_text=_(
            "Requirement of another IXFMemberData entry "
            "and will be applied alongside it"
        ),
    )

    deskpro_ref = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text=_("Ticket reference on the DeskPRO side"),
    )

    deskpro_id = models.IntegerField(
        null=True, blank=True, help_text=_("Ticket id on the DeskPRO side")
    )

    extra_notifications_net_num = models.PositiveIntegerField(
        default=0,
        help_text=_(
            "Indicates how many extra notifications were sent to the network for this proposal. Extra notifications can be sent for stale netixlan entries over time."
        ),
    )
    extra_notifications_net_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Last time extra notifications were sent to the network for this proposal."
        ),
    )

    # field names of fields that can receive
    # modifications from IX-F

    data_fields = [
        "speed",
        "operational",
        "is_rs_peer",
    ]

    class Meta:
        db_table = "peeringdb_ixf_member_data"
        verbose_name = _("IX-F Member Data")
        verbose_name_plural = _("IX-F Member Data")

    class HandleRef:
        tag = "ixfmember"

    @classmethod
    def id_filters(cls, asn, ipaddr4, ipaddr6, check_protocols=True):
        """
        Returns a dict of filters to use with a
        IXFMemberData or NetworkIXLan query set
        to retrieve a unique entry.
        """

        net = Network.objects.get(asn=asn)

        ipv4_support = net.ipv4_support or not check_protocols
        ipv6_support = net.ipv6_support or not check_protocols

        filters = {"asn": asn}

        if ipv4_support:
            if ipaddr4:
                filters["ipaddr4"] = ipaddr4
            else:
                filters["ipaddr4__isnull"] = True

        if ipv6_support:
            if ipaddr6:
                filters["ipaddr6"] = ipaddr6
            else:
                filters["ipaddr6__isnull"] = True

        return filters

    @classmethod
    def instantiate(cls, asn, ipaddr4, ipaddr6, ixlan, **kwargs):
        """
        Returns an IXFMemberData object.

        It will take into consideration whether or not an instance
        for this object already exists (as identified by asn and ip
        addresses).

        It will also update the value of `fetched` to now.

        Keyword Argument(s):

        - speed(int=0) : network speed (mbit)
        - operational(bool=True): peer is operational
        - is_rs_peer(bool=False): peer is route server
        """

        fetched = datetime.datetime.now().replace(tzinfo=UTC())
        net = Network.objects.get(asn=asn)
        validate_network_protocols = kwargs.get("validate_network_protocols", True)
        for_deletion = kwargs.get("delete", False)

        try:
            id_filters = cls.id_filters(asn, ipaddr4, ipaddr6)
            instances = cls.objects.filter(**id_filters)

            if not instances.exists():
                raise cls.DoesNotExist()

            if instances.count() > 1:
                # this only happens when a network switches on/off
                # ipv4/ipv6 protocol support inbetween importer
                # runs.

                for instance in instances:
                    if ipaddr4 != instance.ipaddr4 or ipaddr6 != instance.ipaddr6:
                        instance.delete(hard=True)

                instance = cls.objects.get(**id_filters)
            else:
                instance = instances.first()

            for field in cls.data_fields:
                setattr(instance, f"previous_{field}", getattr(instance, field))

            instance._previous_data = instance.data
            instance._previous_error = instance.error

            instance.fetched = fetched
            instance._meta.get_field("updated").auto_now = False
            instance.save()
            instance._meta.get_field("updated").auto_now = True

        except cls.DoesNotExist:
            ip_args = {}

            if net.ipv4_support or not ipaddr4 or for_deletion:
                ip_args.update(ipaddr4=ipaddr4)

            if net.ipv6_support or not ipaddr6 or for_deletion:
                ip_args.update(ipaddr6=ipaddr6)

            if not ip_args and validate_network_protocols:
                raise NetworkProtocolsDisabled(
                    _(
                        "No suitable ipaddresses when validating against the enabled network protocols"
                    )
                )

            instance = cls(asn=asn, status="ok", **ip_args)

        instance.speed = kwargs.get("speed", 0)
        instance.operational = kwargs.get("operational", True)
        instance.is_rs_peer = kwargs.get("is_rs_peer")
        instance.ixlan = ixlan
        instance.fetched = fetched
        instance.for_deletion = for_deletion

        if ipaddr4:
            instance.init_ipaddr4 = ipaddress.ip_address(ipaddr4)
        else:
            instance.init_ipaddr4 = None

        if ipaddr6:
            instance.init_ipaddr6 = ipaddress.ip_address(ipaddr6)
        else:
            instance.init_ipaddr6 = None

        if "data" in kwargs:
            instance.set_data(kwargs.get("data"))

        return instance

    @classmethod
    def get_for_network(cls, net):
        """
        Returns queryset for IXFMemberData objects that match
        a network's asn.

        Argument(s):

        - net(Network)
        """
        return cls.objects.filter(asn=net.asn)

    @classmethod
    def dismissed_for_network(cls, net):
        """
        Returns queryset for IXFMemberData objects that match
        a network's asn and are currenlty flagged as dismissed.

        Argument(s):

        - net(Network)
        """
        qset = cls.get_for_network(net).select_related("ixlan", "ixlan__ix")
        qset = qset.filter(dismissed=True)
        return qset

    @classmethod
    def network_has_dismissed_actionable(cls, net):
        """
        Returns whether or not the specified network has
        any dismissed IXFMemberData suggestions that are
        actionable.

        Argument(s):

        - net(Network)
        """

        for ixf_member_data in cls.dismissed_for_network(net):
            if not ixf_member_data.ixlan.ready_for_ixf_import:
                continue
            if ixf_member_data.action != "noop":
                return True
        return False

    @classmethod
    def proposals_for_network(cls, net):
        """
        Returns a dict containing actionable proposals for
        a network.

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
            if not ixf_member_data.ixlan.ready_for_ixf_import:
                continue

            action = ixf_member_data.action
            ixf_member_data.error

            # not actionable for anyone

            if action == "noop":
                continue

            # not actionable for network

            if not ixf_member_data.actionable_for_network:
                continue

            # dismissed by network

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

        return sorted(proposals.values(), key=lambda x: x["ix"].name.lower())

    @property
    def previous_data(self):
        return getattr(self, "_previous_data", "{}")

    @property
    def previous_error(self):
        return getattr(self, "_previous_error", None)

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
        this entry.
        """

        if not hasattr(self, "_net"):
            self._net = Network.objects.get(asn=self.asn)
        return self._net

    @property
    def actionable_for_network(self):
        """
        Returns whether or not the proposed action by
        this IXFMemberData instance is actionable by
        the network.
        """
        error = self.error

        if error and "address outside of prefix" in error:
            return False

        if error and "does not match any prefix" in error:
            return False

        if error and "speed value" in error:
            return False

        return True

    @property
    def actionable_error(self):
        """
        Returns whether or not the error is actionable
        by exchange or network.

        If actionable will return self.error otherwise
        will return None.
        """

        if not self.error:
            return None

        try:
            error_data = json.loads(self.error)
        except Exception:
            return None

        IPADDR_EXIST = "already exists"
        DELETED_NETIXLAN_BAD_ASN = "This entity was created for the ASN"

        if IPADDR_EXIST in error_data.get("ipaddr4", [""])[0]:
            for requirement in self.requirements:
                if requirement.netixlan.ipaddr4 == self.ipaddr4:
                    return None
            if NetworkIXLan.objects.filter(
                ipaddr4=self.ipaddr4, status="deleted"
            ).exists():
                return None

        if IPADDR_EXIST in error_data.get("ipaddr6", [""])[0]:
            for requirement in self.requirements:
                if requirement.netixlan.ipaddr6 == self.ipaddr6:
                    return None

            if NetworkIXLan.objects.filter(
                ipaddr6=self.ipaddr6, status="deleted"
            ).exists():
                return None

        if DELETED_NETIXLAN_BAD_ASN in error_data.get("__all__", [""])[0]:
            if self.netixlan.status == "deleted":
                return None

        return self.error

    @property
    def net_contacts(self):
        """
        Returns a list of email addresses that
        are suitable contact points for conflict resolution
        at the network's end.
        """
        qset = self.net.poc_set_active.exclude(email="")
        qset = qset.exclude(email__isnull=True)

        role_priority = ["Technical", "NOC", "Policy"]

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
        at the exchange end.
        """
        return [self.ix.tech_email or self.ix.policy_email]

    @property
    def ix(self):
        """
        Returns the InternetExchange instance related to
        this entry.
        """

        if not hasattr(self, "_ix"):
            self._ix = self.ixlan.ix
        return self._ix

    @property
    def ixf_id(self):
        """
        Returns a tuple that identifies the IX-F member
        as a unqiue record by asn, ip4 and ip6 address.
        """

        return (self.asn, self.ipaddr4, self.ipaddr6)

    @property
    def ixf_id_pretty_str(self):
        ipaddr4 = self.ipaddr4 or _("IPv4 not set")
        ipaddr6 = self.ipaddr6 or _("IPv6 not set")

        return f"AS{self.asn} - {ipaddr4} - {ipaddr6}"

    @property
    def actionable_changes(self):
        self.requirements

        _changes = self.changes

        for requirement in self.requirements:
            _changes.update(self._changes(requirement.netixlan))

        if self.ipaddr4_on_requirement:
            _changes.update(ipaddr4=self.ipaddr4_on_requirement)
        if self.ipaddr6_on_requirement:
            _changes.update(ipaddr6=self.ipaddr6_on_requirement)

        return _changes

    @property
    def changes(self):
        """
        Returns a dict of changes (field, value)
        between this entry and the related netixlan.

        If an empty dict is returned that means no changes.

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
        return self._changes(netixlan)

    def _changes(self, netixlan):
        changes = {}

        if self.marked_for_removal or not netixlan:
            return changes

        if (
            self.modify_is_rs_peer
            and self.is_rs_peer is not None
            and netixlan.is_rs_peer != self.is_rs_peer
        ):
            changes.update(
                is_rs_peer={"from": netixlan.is_rs_peer, "to": self.is_rs_peer}
            )

        if self.modify_speed and self.speed > 0 and netixlan.speed != self.speed:
            changes.update(speed={"from": netixlan.speed, "to": self.speed})

        if netixlan.operational != self.operational:
            changes.update(
                operational={"from": netixlan.operational, "to": self.operational}
            )

        if netixlan.status != self.status:
            changes.update(status={"from": netixlan.status, "to": self.status})

        return changes

    @property
    def modify_speed(self):
        """
        Returns whether or not the `speed` property
        is enabled to receive modify updates or not (#793).
        """
        return False

    @property
    def modify_is_rs_peer(self):
        """
        Returns whether or not the `is_rs_peer` property
        is enabled to receive modify updates or not (#793).
        """
        return False

    @property
    def changed_fields(self):
        """
        Returns a comma separated string of field names
        for changes proposed by this IXFMemberData instance.
        """
        return ", ".join(list(self.changes.keys()))

    @property
    def remote_changes(self):
        """
        Returns a dict of changed fields between previously
        fetched IX-F data and current IX-F data.

        If an empty dict is returned that means no changes.

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
        IX-F source.
        """

        return self.data == "{}" or not self.data

    @property
    def marked_for_removal(self):
        """
        Returns whether or not this entry implies that
        the related netixlan should be removed.

        We do this by checking if the IX-F data was provided
        or not.
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
        instance.
        """
        return NetworkIXLan.objects.filter(
            ixlan=self.ixlan, network=self.net, status="ok"
        ).exists()

    @property
    def action(self):
        """
        Returns the implied action of applying this
        entry to peeringdb.

        Will return either "add", "modify", "delete" or "noop"
        """

        has_data = self.remote_data_missing is False

        action = "noop"

        if has_data:
            if not self.netixlan.id:
                action = "add"

            elif self.status == "ok" and self.netixlan.status == "deleted":
                action = "add"

            elif self.changes:
                action = "modify"
        else:
            if self.marked_for_removal:
                action = "delete"

        # the proposal is to add a netixlan, but we have
        # the requirement of a deletion of another netixlan
        # that has one of the ips set but not the other.
        #
        # action re-classified to modify (#770)
        if action == "add" and self.has_requirements:
            if (
                self.primary_requirement.asn == self.asn
                and self.primary_requirement.action == "delete"
            ):
                action = "modify"

        return action

    @property
    def has_requirements(self):
        """
        Return whether or not this IXFMemberData has
        other IXFMemberData objects as requirements.
        """

        return len(self.requirements) > 0

    @property
    def requirements(self):
        """
        Returns list of all IXFMemberData objects
        that are still active requirements for this
        IXFMemberData object.
        """
        if not self.id:
            return []
        return [
            requirement
            for requirement in self.requirement_set.all()
            # if requirement.action != "noop"
        ]

    @property
    def primary_requirement(self):
        """
        Return the initial requirement IXFMemberData
        for this IXFMemberData instance, None if there
        isn't any.
        """
        try:
            return self.requirements[0]
        except IndexError:
            return None

    @property
    def secondary_requirements(self):
        """
        Return a list of secondary requirement IXFMemberData
        objects for this IXFMemberData object. Currently this
        only happens on add proposals that require two netixlans
        to be deleted because both ipaddresses exist on separate
        netixlans (#770).
        """
        return self.requirements[1:]

    @property
    def ipaddr4_on_requirement(self):
        """
        Returns true if the ipv4 address claimed by this IXFMemberData
        object exists on one of its requirement IXFMemberData objects.
        """

        ipaddr4 = self.ipaddr4
        if not ipaddr4 and hasattr(self, "init_ipaddr4"):
            ipaddr4 = self.init_ipaddr4

        if not ipaddr4:
            return False
        for requirement in self.requirements:
            if requirement.ipaddr4 == ipaddr4:
                return True
        return False

    @property
    def ipaddr6_on_requirement(self):
        """
        Returns true if the ipv6 address claimed by this IXFMemberData
        object exists on one of its requirement IXFMemberData objects.
        """

        ipaddr6 = self.ipaddr6
        if not ipaddr6 and hasattr(self, "init_ipaddr6"):
            ipaddr6 = self.init_ipaddr6

        if not ipaddr6:
            return False
        for requirement in self.requirements:
            if requirement.ipaddr6 == ipaddr6:
                return True
        return False

    @property
    def netixlan(self):
        """
        Will either return a matching existing netixlan
        instance (asn,ip4,ip6) or a new netixlan if
        a matching netixlan does not currently exist.

        Any new netixlan will NOT be saved at this point.

        Note that the netixlan that matched may be currently
        soft-deleted (status=="deleted").
        """

        if not hasattr(self, "_netixlan"):
            if not hasattr(self, "for_deletion"):
                self.for_deletion = self.remote_data_missing

            try:
                if self.for_deletion:
                    filters = self.id_filters(
                        self.asn, self.ipaddr4, self.ipaddr6, check_protocols=False
                    )
                else:
                    filters = self.id_filters(self.asn, self.ipaddr4, self.ipaddr6)

                if "ipaddr6" not in filters and "ipaddr4" not in filters:
                    raise NetworkIXLan.DoesNotExist()

                self._netixlan = NetworkIXLan.objects.get(**filters)

            except NetworkIXLan.DoesNotExist:
                is_rs_peer = self.is_rs_peer
                if is_rs_peer is None:
                    is_rs_peer = False

                self._netixlan = NetworkIXLan(
                    ipaddr4=self.ipaddr4,
                    ipaddr6=self.ipaddr6,
                    speed=self.speed,
                    asn=self.asn,
                    operational=self.operational,
                    is_rs_peer=is_rs_peer,
                    ixlan=self.ixlan,
                    network=self.net,
                    status="ok",
                )

        return self._netixlan

    @property
    def netixlan_exists(self):
        """
        Returns whether or not an active netixlan exists
        for this IXFMemberData instance.
        """
        return self.netixlan.id and self.netixlan.status != "deleted"

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

    def set_requirement(self, ixf_member_data, save=True):
        """
        Sets another IXFMemberData object to be a requirement
        of the resolution of this IXFMemberData object.
        """
        if not ixf_member_data:
            return

        if ixf_member_data in self.requirements:
            return

        if ixf_member_data.netixlan == self.netixlan:
            return

        ixf_member_data.requirement_of = self

        if save:
            ixf_member_data.save()

        return ixf_member_data

    def apply_requirements(self, save=True):
        """
        Apply all requirements.
        """

        for requirement in self.requirements:
            requirement.apply(save=save)

    def apply(self, user=None, comment=None, save=True):
        """
        Applies the data.

        This will either create, update or delete a netixlan
        object.

        Will return a dict containing action and netixlan
        affected.

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

        if user and user.is_authenticated:
            reversion.set_user(user)

        if comment:
            reversion.set_comment(comment)

        self.apply_requirements(save=save)

        action = self.action
        netixlan = self.netixlan
        self.changes

        if action == "add":
            self.validate_speed()

            # Update data values
            netixlan.speed = self.speed
            netixlan.is_rs_peer = bool(self.is_rs_peer)
            netixlan.operational = bool(self.operational)

            if not self.net.ipv6_support:
                netixlan.ipaddr6 = None
            if not self.net.ipv4_support:
                netixlan.ipaddr4 = None

            result = self.ixlan.add_netixlan(netixlan, save=save, save_others=save)

            self._netixlan = netixlan = result["netixlan"]
        elif action == "modify":
            self.validate_speed()

            if self.modify_speed and self.speed:
                netixlan.speed = self.speed
            if self.modify_is_rs_peer and self.is_rs_peer is not None:
                netixlan.is_rs_peer = self.is_rs_peer

            netixlan.operational = self.operational
            if save:
                netixlan.full_clean()
                netixlan.save()
        elif action == "delete":
            if save:
                netixlan.delete()

        return {"action": action, "netixlan": netixlan, "ixf_member_data": self}

    def validate_speed(self):
        """
        Speed errors in IX-F data are raised during parse
        and speed will be on the attribute.

        In order to properly handle invalid speed values,
        check if speed is 0 and if there was a parsing
        error for it, and if so raise a validation error.

        TODO: find a better way to do this.
        """
        if self.speed == 0 and self.error:
            error_data = json.loads(self.error)
            if "speed" in self.error:
                raise ValidationError(error_data)

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
            self.error = json.dumps(exc, cls=ValidationErrorEncoder)

    def set_resolved(self, save=True):
        """
        Marks this IXFMemberData instance as resolved and
        sends out notifications to ac,ix and net if
        warranted.

        This will delete the IXFMemberData instance.
        """
        if self.id and save and not self.requirement_of_id:
            self.delete(hard=True)
            return True

    def set_conflict(self, error=None, save=True):
        """
        Persist this IXFMemberData instance and send out notifications
        for conflict (validation issues) for modifications proposed
        to the corresponding netixlan to ac, ix and net as warranted.
        """

        if not self.id:
            existing_conflict = IXFMemberData.objects.filter(
                asn=self.asn, error__isnull=False
            )

            if self.ipaddr4 and self.ipaddr6:
                existing_conflict = existing_conflict.filter(
                    models.Q(ipaddr4=self.ipaddr4) | models.Q(ipaddr6=self.ipaddr6)
                )
            elif self.ipaddr4:
                existing_conflict = existing_conflict.filter(ipaddr4=self.ipaddr4)
            elif self.ipaddr6:
                existing_conflict = existing_conflict.filter(ipaddr6=self.ipaddr6)

            if existing_conflict.exists():
                return None

        if (self.remote_changes or (error and not self.previous_error)) and save:
            if error:
                self.error = json.dumps(error, cls=ValidationErrorEncoder)
            else:
                self.error = None
            self.dismissed = False
            self.save()
            return True
        elif self.previous_data != self.data and save:
            # since remote_changes only tracks changes to the
            # relevant data fields speed, operational and is_rs_peer
            # we check if the remote data has changed in general
            # and force a save if it did

            self.save_without_update()

    def set_update(self, save=True, reason=""):
        """
        Persist this IXFMemberData instance and send out notifications
        for proposed modification to the corresponding netixlan
        instance to ac, ix and net as warranted.
        """
        self.reason = reason
        if ((self.changes and not self.id) or self.remote_changes) and save:
            self.grab_validation_errors()
            self.dismissed = False
            self.save()
            return True
        elif self.previous_data != self.data and save:
            # since remote_changes only tracks changes to the
            # relevant data fields speed, operational and is_rs_peer
            # we check if the remote data has changed in general
            # and force a save if it did

            self.save_without_update()

    def set_add(self, save=True, reason=""):
        """
        Persist this IXFMemberData instance and send out notifications
        for proposed creation of netixlan instance to ac, ix and net
        as warranted.
        """
        self.reason = reason

        if not self.id and save:
            self.grab_validation_errors()

            self.save()
            return True

        elif self.previous_data != self.data and save:
            # since remote_changes only tracks changes to the
            # relevant data fields speed, operational and is_rs_peer
            # we check if the remote data has changed in general
            # and force a save if it did

            self.save_without_update()

    def set_remove(self, save=True, reason=""):
        """
        Persist this IXFMemberData instance and send out notifications
        for proposed removal of netixlan instance to ac, net and ix
        as warranted.
        """
        self.reason = reason

        # we perist this IX-F member data that proposes removal
        # if any of these conditions are met

        # marked for removal, but not saved

        not_saved = not self.id and self.marked_for_removal

        # was in remote-data last time, gone now

        gone = (
            self.id
            and getattr(self, "previous_data", "{}") != "{}"
            and self.remote_data_missing
        )

        if (not_saved or gone) and save:
            self.set_data({})
            self.save()
            return True

    def set_data(self, data):
        """
        Stores a dict in self.data as a json string.
        """
        self.data = json.dumps(data)

    def render_notification(self, template_file, recipient, context=None):
        """
        Renders notification text for this ixfmemberdata
        instance.

        Argument(s):

        - template_file(str): email template file
        - recipient(str): ac, ix or net
        - context(dict): if set will update the template context
          from this
        """
        _context = {
            "instance": self,
            "recipient": recipient,
            "ixf_url": self.ixlan.ixf_ixp_member_list_url,
            "ixf_url_public": (self.ixlan.ixf_ixp_member_list_url_visible == "Public"),
        }
        if context:
            _context.update(context)

        template = loader.get_template(template_file)
        return template.render(_context)

    @property
    def ac_netixlan_url(self):
        if not self.netixlan.id:
            return ""
        path = django.urls.reverse(
            "admin:peeringdb_server_networkixlan_change",
            args=(self.netixlan.id,),
        )
        return urljoin(settings.BASE_URL, path)

    @property
    def ac_url(self):
        if not self.id:
            return ""
        path = django.urls.reverse(
            "admin:peeringdb_server_ixfmemberdata_change",
            args=(self.id,),
        )
        return urljoin(settings.BASE_URL, path)


# read only, or can make bigger, making smaller could break links
# validate could check


@grainy_model(
    namespace="prefix",
    namespace_instance="{instance.ixlan.grainy_namespace}.{namespace}.{instance.pk}",
)
@reversion.register
class IXLanPrefix(ProtectedMixin, pdb_models.IXLanPrefixBase, StripFieldMixin):
    """
    Descries a Prefix at an Exchange LAN.
    """

    ixlan = models.ForeignKey(
        IXLan, on_delete=models.CASCADE, default=0, related_name="ixpfx_set"
    )

    # override in_dfz to default it to True on the schema level (#761)

    in_dfz = models.BooleanField(default=True)

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the ixpfx for logging purposes.
        """
        return f"ixpfx{self.id} {self.prefix}"

    @classmethod
    def related_to_ix(cls, value=None, filt=None, field="ix_id", qset=None):
        """
        Filter queryset of ixpfx objects related to exchange via ix_id match
        according to filter.

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
        the supplied ipaddress.
        """

        if not qset:
            qset = cls.handleref.undeleted()

        ids = []

        ipaddr = ipaddress.ip_address(ipaddr)

        for ixpfx in qset:
            if ipaddr in ixpfx.prefix:
                ids.append(ixpfx.id)

        return qset.filter(id__in=ids)

    def __str__(self):
        return f"{self.prefix}"

    def test_ip_address(self, addr):
        """
        Checks if this prefix can contain the specified ip address.

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
            ip_range = ipaddress.ip_network(self.prefix)
            if addr in [ip_range[0], ip_range[-1]]:
                return False
            return addr in ip_range
        except ipaddress.AddressValueError:
            return False

        except ValueError:
            return False

    def clean(self):
        """
        Custom model validation.
        """

        status_error = _(
            "IXLanPrefix with status '{}' cannot be linked to a IXLan with status '{}'."
        ).format(self.status, self.ixlan.status)

        if self.ixlan.status == "pending" and self.status == "ok":
            raise ValidationError(status_error)
        elif self.ixlan.status == "deleted" and self.status in ["ok", "pending"]:
            raise ValidationError(status_error)

        # validate the specified prefix address
        validate_address_space(self.prefix)
        validate_prefix_overlap(self.prefix)
        return super().clean()

    @property
    def ix_result_name(self):
        return self.ixlan.ix.search_result_name

    @property
    def ix_org_id(self):
        return self.ixlan.ix.org_id

    @property
    def ix_id(self):
        return self.ixlan.ix.id

    @property
    def ix_sub_result_name(self):
        return self.prefix


@grainy_model(namespace="network", parent="org")
@reversion.register
class Network(
    pdb_models.NetworkBase,
    ParentStatusCheckMixin,
    SocialMediaMixin,
    StripFieldMixin,
):
    """
    Describes a peeringdb network.
    """

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="net_set"
    )
    allow_ixp_update = models.BooleanField(
        null=False,
        default=False,
        help_text=_(
            "Specifies whether an IXP is allowed to add a netixlan entry for this network via their ixp_member data"
        ),
    )

    @classmethod
    def automated_net_count(cls):
        """
        Class method that retrieves all Networks with allow_ixp_update=True.

        Args:
        None just returns a count of total automated_nets.

        Returns:
        A queryset of Network objects that match allow_ixp_update=True and status=ok .
        """

        return cls.objects.filter(allow_ixp_update=True, status="ok")

    netixlan_updated = models.DateTimeField(blank=True, null=True)
    netfac_updated = models.DateTimeField(blank=True, null=True)
    poc_updated = models.DateTimeField(blank=True, null=True)

    ix_count = models.PositiveIntegerField(
        _("number of exchanges at this network"),
        help_text=_("number of exchanges at this network"),
        null=False,
        default=0,
    )

    fac_count = models.PositiveIntegerField(
        _("number of facilities at this network"),
        help_text=_("number of facilities at this network"),
        null=False,
        default=0,
    )

    class Meta(pdb_models.NetworkBase.Meta):
        indexes = [
            models.Index(fields=["status", "allow_ixp_update"], name="net_status")
        ]

    parent_relations = ["org"]

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
    @transaction.atomic()
    def create_from_rdap(cls, rdap, asn, org):
        """
        Creates network from rdap result object.
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

        Relationship through netixlan.
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
        specified by ix_id (as in networks not present at the exchange).

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
        Returns a dict mapping asns to their irr_as_set value.
        """
        if not qset:
            qset = cls.objects.filter(status="ok").order_by("asn")
        return {net.asn: net.irr_as_set for net in qset}

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity.
        """

        return f"{self.name} ({self.asn})"

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
        through NetworkIXLan.
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
        to this network through NetworkIXLan.
        """
        qset = self.ixlan_set_active.filter(ixf_ixp_import_enabled=True)
        qset = qset.exclude(ixf_ixp_member_list_url__isnull=True)
        return qset

    @property
    def ixlan_set_ixf_enabled_with_suggestions(self):
        """
        Returns IXLan queryset for IX-F import enabled ixlans connected
        to this network through NetworkIXLan. Only contains ixlans that
        have active suggestions for the network.
        """
        qset = self.ixlan_set_ixf_enabled

        ixlan_ids = []

        for ixlan in qset:
            if ixlan.ixf_set.filter(asn=self.asn).exists():
                ixlan_ids.append(ixlan.id)

        return IXLan.objects.filter(id__in=ixlan_ids)

    @property
    def poc_set_active(self):
        return self.poc_set(manager="handleref").filter(status="ok")

    @property
    def ipv4_support(self):
        # network has not indicated either ip4 or ip6 support
        # so assume True (#771)

        if not self.info_unicast and not self.info_ipv6:
            return True

        return self.info_unicast

    @property
    def ipv6_support(self):
        # network has not indicated either ip4 or ip6 support
        # so assume True (#771)

        if not self.info_unicast and not self.info_ipv6:
            return True

        return self.info_ipv6

    @property
    def sponsorship(self):
        return self.org.sponsorship

    @property
    def view_url(self):
        """
        Return the URL to this networks web view.
        """
        return urljoin(
            settings.BASE_URL, django.urls.reverse("net-view", args=(self.id,))
        )

    @property
    def view_url_asn(self):
        """
        Return the URL to this networks web view.
        """
        return urljoin(
            settings.BASE_URL, django.urls.reverse("net-view-asn", args=(self.asn,))
        )

    @property
    def info_type(self):
        if self.info_types:
            return list(self.info_types)[0]
        return ""

    def clean(self):
        """
        Custom model validation.
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

        return super().clean()

    def save(self, *args, **kwargs):
        """
        Save the current instance
        """
        self.validate_parent_status()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Delete the Network instance.

        This method ensures that all related NetworkContact instances are deleted with
        the `deleting_network` flag set to True, which allows the contacts to be deleted
        regardless of their current state.

        """
        for contact in self.poc_set.all():
            contact.delete(deleting_network=True)
        super().delete(*args, **kwargs)


# class NetworkContact(HandleRefModel):
@grainy_model(
    namespace="poc_set",
    namespace_instance="{namespace}.{instance.visible}",
    parent="network",
)
@reversion.register
class NetworkContact(
    ProtectedMixin,
    pdb_models.ContactBase,
    ParentStatusCheckMixin,
    StripFieldMixin,
):
    """
    Describes a contact point (phone, email etc.) for a network.
    """

    # id = models.AutoField(primary_key=True)
    network = models.ForeignKey(
        Network, on_delete=models.CASCADE, default=0, related_name="poc_set"
    )

    TECH_ROLES = ["Technical", "NOC", "Policy"]
    parent_relations = ["network"]

    class Meta:
        db_table = "peeringdb_network_contact"

    @property
    def is_tech_contact(self):
        return self.role in self.TECH_ROLES

    @property
    def deletable(self):
        """
        Returns whether or not the poc is currently
        in a state where it can be marked as deleted.

        This will be False for pocs that are the last remaining
        technical contact point for a network that has
        active netixlans. (#923)
        """

        # non-technical pocs can always be deleted

        if not self.is_tech_contact:
            self._not_deletable_reason = None
            return True

        netixlan_count = self.network.netixlan_set_active.count()
        tech_poc_count = self.network.poc_set_active.filter(
            role__in=self.TECH_ROLES
        ).count()

        if netixlan_count and tech_poc_count == 1 and not self._deleting_network:
            # there are active netixlans and this poc is the
            # only technical poc left

            self._not_deletable_reason = _(
                "Last technical contact point for network with active peers"
            )
            return False
        else:
            self._not_deletable_reason = None
            return True

    def delete(self, *args, **kwargs):
        """
        Delete the NetworkContact instance.

        This method sets the `_deleting_network` attribute to indicate whether
        the deletion is part of a parent network deletion or not. If `deleting_network`
        is passed as True in the kwargs, it indicates that the parent network is
        being deleted, allowing the contact to be deleted regardless of its current state.

        """
        self._deleting_network = kwargs.pop("deleting_network", False)
        super().delete(*args, **kwargs)

    @property
    def view_url(self):
        """
        Return the URL to related networks web view.
        """
        return urljoin(
            settings.BASE_URL, django.urls.reverse("net-view", args=(self.network_id,))
        )

    def validate_requirements(self):
        if not self.phone and not self.email:
            raise ValidationError(
                {
                    "phone": _("Phone or email required"),
                    "email": _("Phone or email required"),
                }
            )

    def clean(self):
        try:
            self.phone = validate_phonenumber(self.phone)
        except ValidationError as exc:
            raise ValidationError({"phone": exc})

        self.visible = validate_poc_visible(self.visible)
        self.validate_requirements()

    def save(self, *args, **kwargs):
        """
        Save the current instance
        """
        self.validate_parent_status()
        super().save(*args, **kwargs)


@grainy_model(namespace="netfac", parent="network")
@reversion.register
class NetworkFacility(
    pdb_models.NetworkFacilityBase, ParentStatusCheckMixin, StripFieldMixin
):
    """
    Describes a network <-> facility relationship.
    """

    network = models.ForeignKey(
        Network, on_delete=models.CASCADE, default=0, related_name="netfac_set"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, default=0, related_name="netfac_set"
    )

    parent_relations = ["network", "facility"]

    class Meta:
        db_table = "peeringdb_network_facility"
        unique_together = ("network", "facility", "local_asn")
        indexes = [models.Index(fields=["status"], name="netfac_status")]

    @classmethod
    def related_to_name(cls, value=None, filt=None, field="facility__name", qset=None):
        """
        Filter queryset of netfac objects related to facilities with name match
        in facility__name according to filter.

        Relationship through facility.
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
        in facility__country according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.filter(status="ok")
        return qset.filter(**make_relation_filter(field, filt, value))

    @classmethod
    def related_to_city(cls, value=None, filt=None, field="facility__city", qset=None):
        """
        Filter queryset of netfac objects related to city via match
        in facility__city according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.undeleted()
        return qset.filter(**make_relation_filter(field, filt, value))

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the netfac for logging purposes.
        """
        return f"netfac{self.id} AS{self.network.asn} {self.network.name} <-> {self.facility.name}"

    def clean(self):
        # `local_asn` will eventually be dropped from the schema
        # for now make sure it is always a match to the related
        # network (#168)

        self.local_asn = self.network.asn

    def save(self, *args, **kwargs):
        """
        Save the current instance
        """
        self.validate_parent_status()
        super().save(*args, **kwargs)


def format_speed(value):
    if value >= 1000000:
        value = value / 10**6
        if not value % 1:
            return f"{value:.0f}T"
        return f"{value:.1f}T"
    elif value >= 1000:
        return f"{value / 10 ** 3:.0f}G"
    else:
        return f"{value:.0f}M"


@grainy_model(namespace="ixlan", parent="network")
@reversion.register
class NetworkIXLan(
    pdb_models.NetworkIXLanBase, ParentStatusCheckMixin, StripFieldMixin
):
    """
    Describes a network relationship to an IX through an IX Lan.
    """

    network = models.ForeignKey(
        Network, on_delete=models.CASCADE, default=0, related_name="netixlan_set"
    )
    ixlan = models.ForeignKey(
        IXLan, on_delete=models.CASCADE, default=0, related_name="netixlan_set"
    )
    net_side = models.ForeignKey(
        Facility,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="net_side_set",
    )
    ix_side = models.ForeignKey(
        Facility,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ix_side_set",
    )

    parent_relations = ["ixlan", "network"]

    class Meta:
        db_table = "peeringdb_network_ixlan"
        constraints = [
            models.UniqueConstraint(fields=["ipaddr4"], name="unique_ipaddr4"),
            models.UniqueConstraint(fields=["ipaddr6"], name="unique_ipaddr6"),
        ]
        indexes = [models.Index(fields=["status"], name="netixlan_status")]

    @property
    def name(self):
        return ""

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the netixlan for logging purposes.
        """
        return f"netixlan{self.id} AS{self.asn} {self.ipaddr4} {self.ipaddr6}"

    @property
    def ix_name(self):
        """
        Returns the exchange name for this netixlan.
        """
        return self.ixlan.ix.name

    @property
    def ix_id(self):
        """
        Returns the exchange id for this netixlan.
        """
        return self.ixlan.ix_id

    @property
    def ixf_id(self):
        """
        Returns a tuple that identifies the netixlan
        in the context of an IX-F member data entry as a unqiue record by asn, ip4 and ip6 address.
        """

        self.network
        return (self.asn, self.ipaddr4, self.ipaddr6)

    @property
    def ixf_id_pretty_str(self):
        asn, ipaddr4, ipaddr6 = self.ixf_id
        ipaddr4 = ipaddr4 or _("IPv4 not set")
        ipaddr6 = ipaddr6 or _("IPv6 not set")

        return f"AS{asn} - {ipaddr4} - {ipaddr6}"

    @property
    def data_change_parent(self):
        """
        Returns tuple of (str, int) describing the parent network

        This makes it a supported object for data change notification implemented through
        DataChangeNotificationQueue
        """

        return ("net", self.network_id)

    @property
    def data_change_pretty_str(self):
        return self.ixf_id_pretty_str

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
        according to filter.

        Relationship through ixlan -> ix
        """
        return cls.related_to_ix(value=value, filt=filt, field=field, qset=qset)

    def ipaddress_conflict(self, check_deleted=False):
        """
        Checks whether the ip addresses specified on this netixlan
        exist on another netixlan (with status="ok").

        Arguments

        - check_deleted (`bool`) - if True also look for conflicts in deleted

        Returns:
            - tuple(bool, bool): tuple of two booleans, first boolean is
                true if there was a conflict with the ip4 address, second
                boolean is true if there was a conflict with the ip6
                address
        """

        if not check_deleted:
            ipv4 = NetworkIXLan.objects.filter(
                ipaddr4=self.ipaddr4, status="ok"
            ).exclude(id=self.id)
            ipv6 = NetworkIXLan.objects.filter(
                ipaddr6=self.ipaddr6, status="ok"
            ).exclude(id=self.id)
        else:
            ipv4 = NetworkIXLan.objects.filter(ipaddr4=self.ipaddr4).exclude(id=self.id)
            ipv6 = NetworkIXLan.objects.filter(ipaddr6=self.ipaddr6).exclude(id=self.id)

        conflict_v4 = self.ipaddr4 and ipv4.exists()
        conflict_v6 = self.ipaddr6 and ipv6.exists()
        return (conflict_v4, conflict_v6)

    def validate_ipaddr4(self):
        if self.ipaddr4 and not self.ixlan.test_ipv4_address(self.ipaddr4):
            raise ValidationError(_("IPv4 address outside of prefix"))

    def validate_ipaddr6(self):
        if self.ipaddr6 and not self.ixlan.test_ipv6_address(self.ipaddr6):
            raise ValidationError(_("IPv6 address outside of prefix"))

    def validate_real_peer_vs_ghost_peer(self):
        """
        If there are ip-address conflicts with another NetworkIXLan object
        try to resolve those conflicts if the new peer exists in the related
        exchange's IX-F data (real peer) and the old peer does not (ghost peer)
        """

        # check for ip address conflicts

        conflict4, conflict6 = self.ipaddress_conflict()

        if not conflict4 and not conflict6:
            return

        # check if self (new peer) is a real peer that exists in the
        # exchange's IX-f DATA

        real4, real6 = self.ixlan.ix.peer_exists_in_ixf_data(
            self.network.asn, self.ipaddr4, self.ipaddr6
        )

        if not real4 and not real6:
            return

        # retrieve the conflicting NetworkIXLan instances

        other4 = None
        other6 = None

        if conflict4:
            other4 = NetworkIXLan.objects.get(status="ok", ipaddr4=self.ipaddr4)

        if conflict6:
            other6 = NetworkIXLan.objects.get(status="ok", ipaddr6=self.ipaddr6)

        # will be flagged for existance of other peer in IX-F data
        # False means other peer is a ghost peer

        ip4 = False
        ip6 = False

        try:
            if other4 == other6:
                # ip address conflicts are contained in the same NetworkIXLan, so other4 can be
                # processed by itself

                ip4, ip6 = self.ixlan.ix.peer_exists_in_ixf_data(
                    other4.network.asn, other4.ipaddr4, other4.ipaddr6
                )

            else:
                # conflicts for v4 and v6 are located on separate NetworkIXLan objects
                # process each separately.

                if other4 and other4 != other6:
                    ip4, _ = self.ixlan.ix.peer_exists_in_ixf_data(
                        other4.network.asn, other4.ipaddr4, None
                    )
                if other6 and other4 != other6:
                    _, ip6 = self.ixlan.ix.peer_exists_in_ixf_data(
                        other6.network.asn, None, other6.ipaddr6
                    )

        except Exception as exc:
            # Any error here is likely invalid IX-F data, we dont want to hard fail the object creation
            # Log the error and just return without applying the real vs ghost peer logic

            logger.error(exc)
            return

        # Free up conflicting ghost peer ip addresses

        if other4 == other6:
            # ip address conflicts are contained in the same NetworkIXLan, so other4 can be processed
            # by it self

            if real4 and not ip4:
                other4.ipaddr4 = None

            if real6 and not ip6:
                other4.ipaddr6 = None

            # if both ipaddresses are None now, delete the ghost peer
            # otherwise just save it

            if not other4.ipaddr4 and not other4.ipaddr6:
                other4.delete()
            else:
                other4.save()

        else:
            # conflicts for v4 and v6 are located on separate NetworkIXLan objects
            # process each separately.

            if other4 and real4 and not ip4:
                other4.ipaddr4 = None

                # if both ipaddresses are None now, delete the ghost peer
                # otherwise just save it

                if not other4.ipaddr4 and not other4.ipaddr6:
                    other4.delete()
                else:
                    other4.save()

            if other6 and real6 and not ip6:
                other6.ipaddr6 = None

                # if both ipaddresses are None now, delete the ghost peer
                # otherwise just save it

                if not other6.ipaddr4 and not other6.ipaddr6:
                    other6.delete()
                else:
                    other6.save()

    def validate_speed(self):
        if self.speed in [None, 0]:
            pass

        # bypass validation according to #741
        elif bypass_validation():
            return

        elif self.speed > settings.DATA_QUALITY_MAX_SPEED:
            raise ValidationError(
                _("Maximum speed: {}").format(
                    format_speed(settings.DATA_QUALITY_MAX_SPEED)
                )
            )
        elif self.speed < settings.DATA_QUALITY_MIN_SPEED:
            raise ValidationError(
                _("Minimum speed: {}").format(
                    format_speed(settings.DATA_QUALITY_MIN_SPEED)
                )
            )

    def validate_ip_conflicts(self, check_deleted=False):
        """
        Validates whether the ip addresses specified on this netixlan
        are conflicting with any other netixlans.

        Will raise a `ValidationError` on conflict

        Arguments

        - check_deleted (`bool`) - if True also look for conflicts in deleted
          netixlans
        """

        errors = {}

        conflict_v4, conflict_v6 = self.ipaddress_conflict(check_deleted=check_deleted)
        if conflict_v4:
            errors["ipaddr4"] = _("IP already exists")
        if conflict_v6:
            errors["ipaddr6"] = _("IP already exists")

        if errors:
            raise ValidationError(errors, code="unique")

    def clean(self):
        """
        Custom model validation.
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

        try:
            self.validate_speed()
        except ValidationError as exc:
            errors["speed"] = exc.message

        if errors:
            raise ValidationError(errors)

        # handle real peer versus ghost peer conflict resolution (#983)

        self.validate_real_peer_vs_ghost_peer()

        # make sure this ip address is not claimed anywhere else

        self.validate_ip_conflicts()

        # `asn` will eventually be dropped from the schema
        # for now make sure it is always a match to the related
        # network (#168)

        self.asn = self.network.asn
        super().clean()

    def ipaddr(self, version):
        """
        Return the netixlan's ipaddr for ip version.
        """
        if version == 4:
            return self.ipaddr4
        elif version == 6:
            return self.ipaddr6
        raise ValueError(f"Invalid ip version {version}")

    def descriptive_name_ipv(self, version):
        """
        Returns a descriptive label of the netixlan for logging purposes.
        Will only contain the ipaddress matching the specified version.
        """
        return f"netixlan{self.id} AS{self.asn} {self.ipaddr(version)}"

    @property
    def ix_result_name(self):
        return self.ixlan.ix.search_result_name

    @property
    def ix_org_id(self):
        return self.ixlan.ix.org_id

    @property
    def net_result_name(self):
        return self.network.search_result_name

    @property
    def net_org_id(self):
        return self.network.org_id

    @property
    def net_id(self):
        return self.network.id

    @property
    def ix_sub_result_name(self):
        if self.ipaddr4 and self.ipaddr6:
            return f"{self.ipaddr4} {self.ipaddr6}"
        elif self.ipaddr4:
            return f"{self.ipaddr4}"
        elif self.ipaddr6:
            return f"{self.ipaddr6}"

    @property
    def net_sub_result_name(self):
        ips = self.ix_sub_result_name
        return f"{self.ixlan.ix.search_result_name} {ips}"

    def save(self, *args, **kwargs):
        """
        Save the current instance
        """
        self.validate_parent_status()
        super().save(*args, **kwargs)


@grainy_model(namespace="carrier", parent="org")
@reversion.register
class Carrier(
    ProtectedMixin, pdb_models.CarrierBase, SocialMediaMixin, StripFieldMixin
):
    """
    Describes a carrier object.
    """

    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="carrier_set"
    )

    @staticmethod
    def autocomplete_search_fields():
        """
        Returns a tuple of field query strings to be used during quick search
        query.
        """
        return (
            "id__iexact",
            "name__icontains",
        )

    @property
    def sponsorship(self):
        """
        Returns sponsorship oject for this carrier (through the owning org).
        """
        return self.org.sponsorship

    @property
    def search_result_name(self):
        """
        This will be the name displayed for quick search matches
        of this entity.
        """
        return self.name

    @property
    def carrierfac_set_active(self):
        """
        Returns queryset of active CarrierFacility objects connected to this
        carrier.
        """
        return self.carrierfac_set.filter(status="ok")

    @property
    def view_url(self):
        """
        Return the URL to this carrier's web view.
        """
        return urljoin(
            settings.BASE_URL, django.urls.reverse("carrier-view", args=(self.id,))
        )


@grainy_model(namespace="carrierfac", parent="carrier")
@reversion.register
class CarrierFacility(pdb_models.CarrierFacilityBase, StripFieldMixin):
    """
    Describes a carrier <-> facility relationship.
    """

    carrier = models.ForeignKey(
        Carrier, on_delete=models.CASCADE, default=0, related_name="carrierfac_set"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, default=0, related_name="carrierfac_set"
    )

    class Meta(pdb_models.CarrierFacilityBase.Meta):
        db_table = "peeringdb_carrier_facility"
        unique_together = ("carrier", "facility")

    @classmethod
    def related_to_name(cls, value=None, filt=None, field="facility__name", qset=None):
        """
        Filter queryset of carrierfac objects related to facilities with name match
        in facility__name according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.undeleted()
        return qset.filter(**make_relation_filter(field, filt, value))

    @classmethod
    def related_to_country(
        cls, value=None, filt=None, field="facility__country", qset=None
    ):
        """
        Filter queryset of carrierfac objects related to country via match
        in facility__country according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.filter(status="ok")
        return qset.filter(**make_relation_filter(field, filt, value))

    @classmethod
    def related_to_city(cls, value=None, filt=None, field="facility__city", qset=None):
        """
        Filter queryset of carrierfac objects related to city via match
        in facility__city according to filter.

        Relationship through facility.
        """
        if not qset:
            qset = cls.handleref.undeleted()
        return qset.filter(**make_relation_filter(field, filt, value))

    @property
    def descriptive_name(self):
        """
        Returns a descriptive label of the netfac for logging purposes.
        """
        return f"carrierfac{self.id} {self.carrier.name} {self.facility.name}"


class User(AbstractBaseUser, PermissionsMixin, StripFieldMixin):
    """
    Proper length fields user.
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
    email = models.EmailField(
        _("email address"), max_length=254, null=True, unique=True
    )
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
    primary_org = models.IntegerField(
        blank=True,
        null=True,
        help_text=_("The user's primary organization"),
    )
    locale = models.CharField(
        _("language"),
        max_length=62,
        blank=False,
        null=False,
        default="en",
        choices=settings.LANGUAGES,
    )

    flagged_for_deletion = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Account is orphaned and has been flagged for deletion at this date"
        ),
    )

    notified_for_deletion = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "User has been notified about pending account deletion at this date"
        ),
    )

    never_flag_for_deletion = models.BooleanField(
        default=False,
        help_text=_(
            "This user will never be flagged for deletion through the orphaned user cleanup process."
        ),
    )

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
        requests for this user.
        """
        return self.affiliation_requests.filter(status="pending").order_by("-created")

    @property
    def affiliation_requests_available(self):
        """
        Returns whether the user currently has any affiliation request
        slots available by checking that the number of pending affiliation requests
        the user has is lower than MAX_USER_AFFILIATION_REQUESTS
        """
        return (
            self.pending_affiliation_requests.count()
            < settings.MAX_USER_AFFILIATION_REQUESTS
        )

    @property
    def organizations(self):
        """
        Returns all organizations this user is a member or admin of.
        """
        ids = []
        for group in self.groups.all():
            m = re.match(r"^org\.(\d+).*$", group.name)
            if m and int(m.group(1)) not in ids:
                ids.append(int(m.group(1)))

        return [org for org in Organization.objects.filter(id__in=ids, status="ok")]

    @property
    def self_entity_org(self):
        if self.primary_org:
            return self.primary_org
        orgs = self.organizations

        if not orgs:
            return None

        org_id = min(org.id for org in orgs)
        return Organization.objects.get(id=org_id).id

    @property
    def admin_organizations(self):
        """
        Returns all organizations this user is an admin of.
        """
        ids = []
        for group in self.groups.all():
            m = re.match(r"^org\.(\d+).admin$", group.name)
            if m and int(m.group(1)) not in ids:
                ids.append(int(m.group(1)))

        return [org for org in Organization.objects.filter(id__in=ids, status="ok")]

    @property
    def networks(self):
        """
        Returns all networks this user is a member of.
        """
        return list(
            chain.from_iterable(org.net_set_active.all() for org in self.organizations)
        )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def has_oauth(self):
        return SocialAccount.objects.filter(user=self).count() > 0

    @property
    def email_confirmed(self):
        """
        Returns True if the email specified by the user has
        been confirmed, False if not.
        """

        return self.emailaddress_set.filter(primary=True, verified=True).exists()

    @property
    def is_verified_user(self):
        """
        Returns whether the user is verified (e.g., has been validated
        by PDB staff).

        Currently this is accomplished by checking if the user
        has been added to the 'user' user group.
        """

        group = Group.objects.get(id=settings.USER_GROUP_ID)
        return group in self.groups.all()

    @property
    def has_2fa(self):
        """
        Returns true if the user has set up any TOTP or webauth security keys.
        """

        return self.totpdevice_set.exists() or self.webauthn_security_keys.exists()

    @property
    def get_2fa_security_keys(self):
        return self.webauthn_security_keys.filter(passkey_login=False).all()

    @property
    def get_passkey_security_keys(self):
        return self.webauthn_security_keys.filter(passkey_login=True).all()

    @staticmethod
    def autocomplete_search_fields():
        """
        Used by grappelli autocomplete to determine what
        fields to search in.
        """
        return ("username__icontains", "email__icontains", "last_name__icontains")

    def related_label(self):
        """
        Used by grappelli autocomplete for representation.
        """
        return f"{self.username} <{self.email}> ({self.id})"

    def flush_affiliation_requests(self):
        """
        Removes all user -> org affiliation requests for this user
        that have been denied or canceled.
        """

        UserOrgAffiliationRequest.objects.filter(
            user=self, status__in=["denied", "canceled"]
        ).delete()

    def recheck_affiliation_requests(self):
        """
        Will reevaluate pending affiliation requests to unclaimed
        ASN orgs.

        This allows a user with such a pending affiliation request to
        change ther email and recheck against rdap data for automatic
        ownership approval. (#375)
        """

        for req in self.pending_affiliation_requests.filter(asn__gt=0):
            # we dont want to re-evaluate for affiliation requests
            # with organizations that already have admin users managing them
            if req.org_id and req.org.admin_usergroup.user_set.exists():
                continue

            # cancel current request
            req.delete()

            # reopen request
            UserOrgAffiliationRequest.objects.create(
                user=self, org=req.org, asn=req.asn, status="pending"
            )

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
        full_name = f"{self.first_name} {self.last_name}"
        return full_name.strip()

    def get_short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def email_user(
        self, subject, message, from_email=settings.DEFAULT_FROM_EMAIL, email=None
    ):
        """
        Sends an email to this User.
        """

        if not email:
            email = self.email

        if not getattr(settings, "MAIL_DEBUG", False):
            mail = EmailMultiAlternatives(
                subject,
                message,
                from_email,
                [email],
                headers={"Auto-Submitted": "auto-generated", "Return-Path": "<>"},
            )
            mail.send(fail_silently=False)
        else:
            debug_mail(subject, message, from_email, [email])

    def email_user_all_addresses(
        self, subject, message, from_email=settings.DEFAULT_FROM_EMAIL, exclude=None
    ):
        """
        Sends email to all email addresses for the user
        """

        for email_address in self.emailaddress_set.filter(verified=True):
            if exclude and email_address.email in exclude:
                continue

            self.email_user(subject, message, from_email, email_address.email)

    def notify_email_removed(self, email):
        """
        Notifies the user that the specified email address has been removed
        from their account (#907)
        """

        msg = loader.get_template("email/notify-user-email-removed.txt").render(
            {"support_email": settings.DEFAULT_FROM_EMAIL}
        )

        self.email_user("Email address removed from account", msg, email=email)

    def notify_email_added(self, email):
        """
        Notifies the user that the specified email address has been added
        to their account (#907)
        """

        msg = loader.get_template("email/notify-user-email-added.txt").render(
            {"email": email, "support_email": settings.DEFAULT_FROM_EMAIL}
        )

        self.email_user_all_addresses(
            "Email address added to account", msg, exclude=[email]
        )

    def set_unverified(self):
        """
        Remove user from 'user' group.
        Add user to 'guest' group.
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
        Add user to 'user' group.
        Remove user from 'guest' group.
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

    def send_email_confirmation(self, request=None, signup=False, email=None):
        """
        Use allauth email-confirmation process to make user
        confirm that the email they provided is theirs.
        """
        if not email:
            email = self.email

        if not email:
            return

        email_obj, _ = EmailAddress.objects.get_or_create(user=self, email=email)
        email_obj.verified = False

        if EmailAddress.objects.filter(user=self, primary=True).count() == 0:
            email_obj.primary = True

        email_obj.save()

        try:
            EmailConfirmation.objects.get(email_address=email_obj).delete()
        except EmailConfirmation.DoesNotExist:
            pass

        email_obj.send_confirmation(request=request, signup=signup)

        return email_obj

    def password_reset_complete(self, token, password):
        if self.password_reset.match(token):
            self.set_password(password)
            self.save()
            self.password_reset.delete()

    def password_reset_initiate(self):
        """
        Initiate the password reset process for the user.
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
            if email and self.email and email.lower() == self.email.lower():
                return True
        return False

    @transaction.atomic()
    def close_account(self):
        """
        Removes all identifying information from the User instance
        and flags it as inactive.

        Warning: users that are status == "pending" are hard-deleted
        """

        if self.status == "pending":
            self.delete()
            return

        self.is_active = False
        self.email = None
        self.first_name = ""
        self.last_name = ""
        self.username = f"closed-account-{self.id}"
        self.save()

        self.groups.clear()
        self.emailaddress_set.all().delete()
        self.api_keys.all().delete()


class UserAPIKey(AbstractAPIKey, StripFieldMixin):
    """
    An API Key managed by a user. Can be readonly or can take on the
    permissions of the User.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )

    readonly = models.BooleanField(
        default=False,
        help_text=_(
            "Determines if API Key inherits the User Permissions or is readonly."
        ),
    )

    status = models.CharField(max_length=16, choices=API_KEY_STATUS, default="active")

    class Meta(AbstractAPIKey.Meta):
        verbose_name = "User API key"
        verbose_name_plural = "User API keys"
        db_table = "peeringdb_user_api_key"


def password_reset_token():
    token = str(uuid.uuid4())
    hashed = sha256_crypt.hash(token)
    return token, hashed


class IXFImportEmail(StripFieldMixin):
    """
    A copy of all emails sent by the IX-F importer.
    """

    subject = models.CharField(max_length=255, blank=False)
    message = models.TextField(blank=False)
    recipients = models.CharField(max_length=255, blank=False)
    created = models.DateTimeField(auto_now_add=True)
    sent = models.DateTimeField(blank=True, null=True)
    net = models.ForeignKey(
        Network,
        on_delete=models.CASCADE,
        related_name="network_email_set",
        blank=True,
        null=True,
    )
    ix = models.ForeignKey(
        InternetExchange,
        on_delete=models.CASCADE,
        related_name="ix_email_set",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = _("IX-F Import Email")
        verbose_name_plural = _("IX-F Import Emails")


class UserPasswordReset(StripFieldMixin):
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


class CommandLineTool(StripFieldMixin):
    """
    Describes command line tool execution by a staff user inside the
    control panel (admin).
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
        return f"{self.tool}: {self.description}"

    def set_waiting(self):
        self.status = "waiting"

    def set_done(self):
        self.status = "done"

    def set_running(self):
        self.status = "running"


class EnvironmentSetting(StripFieldMixin):
    """
    Environment settings overrides controlled through
    django admin (/cp).
    """

    class Meta:
        db_table = "peeringdb_settings"
        verbose_name = _("Environment Setting")
        verbose_name_plural = _("Environment Settings")

    setting = models.CharField(
        max_length=255,
        choices=(
            # (
            #     "IXF_IMPORTER_DAYS_UNTIL_TICKET",
            #     _("IX-F Importer: Days until DeskPRO ticket is created"),
            # ),
            (
                "API_THROTTLE_RATE_ANON",
                _("API: Anonymous API throttle rate"),
            ),
            (
                "API_THROTTLE_RATE_USER",
                _("API: Authenticated API throttle rate"),
            ),
            # melissa rate throttle
            (
                "API_THROTTLE_MELISSA_RATE_ADMIN",
                _("API: Melissa request throttle rate for admin users"),
            ),
            (
                "API_THROTTLE_MELISSA_ENABLED_ADMIN",
                _("API: Melissa request throttle enabled for admin users"),
            ),
            (
                "API_THROTTLE_MELISSA_RATE_USER",
                _("API: Melissa request throttle rate for users"),
            ),
            (
                "API_THROTTLE_MELISSA_ENABLED_USER",
                _("API: Melissa request throttle enabled for users"),
            ),
            (
                "API_THROTTLE_MELISSA_RATE_ORG",
                _("API: Melissa request throttle rate for organizations"),
            ),
            (
                "API_THROTTLE_MELISSA_ENABLED_ORG",
                _("API: Melissa request throttle enabled for organizations"),
            ),
            (
                "API_THROTTLE_MELISSA_RATE_IP",
                _("API: Melissa request throttle rate for anonymous requests (ips)"),
            ),
            (
                "API_THROTTLE_MELISSA_ENABLED_IP",
                _("API: Melissa request throttle enabled for anonymous requests (ips)"),
            ),
            # api repeated request throttle: ip-block config
            (
                "API_THROTTLE_REPEATED_REQUEST_THRESHOLD_CIDR",
                _(
                    "API: Repeated request throttle size threshold for ip blocks (bytes)"
                ),
            ),
            (
                "API_THROTTLE_REPEATED_REQUEST_RATE_CIDR",
                _("API: Repeated request throttle rate for ip blocks"),
            ),
            (
                "API_THROTTLE_REPEATED_REQUEST_ENABLED_CIDR",
                _("API: Repeated request throttle enabled for ip blocks"),
            ),
            # api repeated request throttle: ip address config
            (
                "API_THROTTLE_REPEATED_REQUEST_THRESHOLD_IP",
                _(
                    "API: Repeated request throttle size threshold for ip addresses (bytes)"
                ),
            ),
            (
                "API_THROTTLE_REPEATED_REQUEST_RATE_IP",
                _("API: Repeated request throttle rate for ip addresses"),
            ),
            (
                "API_THROTTLE_REPEATED_REQUEST_ENABLED_IP",
                _("API: Repeated request throttle enabled for ip addresses"),
            ),
            # api repeated request throttle: user config
            (
                "API_THROTTLE_REPEATED_REQUEST_THRESHOLD_USER",
                _(
                    "API: Repeated request throttle size threshold for authenticated users (bytes)"
                ),
            ),
            (
                "API_THROTTLE_REPEATED_REQUEST_RATE_USER",
                _("API: Repeated request throttle rate for authenticated users"),
            ),
            (
                "API_THROTTLE_REPEATED_REQUEST_ENABLED_USER",
                _("API: Repeated request throttle enabled for authenticated users"),
            ),
            # api repeated request throttle: org config
            (
                "API_THROTTLE_REPEATED_REQUEST_THRESHOLD_ORG",
                _(
                    "API: Repeated request throttle size threshold for organization api-keys (bytes)"
                ),
            ),
            (
                "API_THROTTLE_REPEATED_REQUEST_RATE_ORG",
                _("API: Repeated request throttle rate for organization api-keys"),
            ),
            (
                "API_THROTTLE_REPEATED_REQUEST_ENABLED_ORG",
                _("API: Repeated request throttle enabled for organization api-keys"),
            ),
            # api throttling response messages
            (
                "API_THROTTLE_RATE_ANON_MSG",
                _("API: Anonymous API throttle rate message"),
            ),
            (
                "API_THROTTLE_RATE_USER_MSG",
                _("API: Authenticated API throttle rate message"),
            ),
            (
                "API_THROTTLE_RATE_WRITE",
                _("API: Request Write API Limiting"),
            ),
            # show database last sync
            (
                "DATABASE_LAST_SYNC",
                _("Show last database sync"),
            ),
            # tutorial mode sync message
            (
                "TUTORIAL_MODE_MESSAGE",
                _("Tutorial mode banner message"),
            ),
        ),
        unique=True,
    )

    value_str = models.CharField(max_length=255, blank=True, null=True)
    value_int = models.IntegerField(blank=True, null=True)
    value_bool = models.BooleanField(blank=True, default=False)
    value_float = models.FloatField(blank=True, null=True)

    updated = models.DateTimeField(
        _("Last Updated"),
        auto_now=True,
        null=True,
        blank=True,
    )

    created = models.DateTimeField(
        _("Configured on"),
        auto_now_add=True,
        blank=True,
        null=True,
    )

    user = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name="admincom_setting_set",
        help_text=_("Last updated by this user"),
    )

    setting_to_field = {
        # "IXF_IMPORTER_DAYS_UNTIL_TICKET": "value_int",
        "API_THROTTLE_RATE_ANON": "value_str",
        "API_THROTTLE_RATE_USER": "value_str",
        "API_THROTTLE_REPEATED_REQUEST_THRESHOLD_CIDR": "value_int",
        "API_THROTTLE_REPEATED_REQUEST_RATE_CIDR": "value_str",
        "API_THROTTLE_REPEATED_REQUEST_ENABLED_CIDR": "value_bool",
        "API_THROTTLE_REPEATED_REQUEST_THRESHOLD_IP": "value_int",
        "API_THROTTLE_REPEATED_REQUEST_RATE_IP": "value_str",
        "API_THROTTLE_REPEATED_REQUEST_ENABLED_IP": "value_bool",
        "API_THROTTLE_REPEATED_REQUEST_THRESHOLD_USER": "value_int",
        "API_THROTTLE_REPEATED_REQUEST_RATE_USER": "value_str",
        "API_THROTTLE_REPEATED_REQUEST_ENABLED_USER": "value_bool",
        "API_THROTTLE_REPEATED_REQUEST_THRESHOLD_ORG": "value_int",
        "API_THROTTLE_REPEATED_REQUEST_RATE_ORG": "value_str",
        "API_THROTTLE_REPEATED_REQUEST_ENABLED_ORG": "value_bool",
        "API_THROTTLE_MELISSA_RATE_USER": "value_str",
        "API_THROTTLE_MELISSA_ENABLED_USER": "value_bool",
        "API_THROTTLE_MELISSA_RATE_ADMIN": "value_str",
        "API_THROTTLE_MELISSA_ENABLED_ADMIN": "value_bool",
        "API_THROTTLE_MELISSA_RATE_ORG": "value_str",
        "API_THROTTLE_MELISSA_ENABLED_ORG": "value_bool",
        "API_THROTTLE_MELISSA_RATE_IP": "value_str",
        "API_THROTTLE_MELISSA_ENABLED_IP": "value_bool",
        "API_THROTTLE_RATE_ANON_MSG": "value_str",
        "API_THROTTLE_RATE_USER_MSG": "value_str",
        "API_THROTTLE_RATE_WRITE": "value_str",
        "DATABASE_LAST_SYNC": "value_str",
        "TUTORIAL_MODE_MESSAGE": "value_str",
    }

    setting_validators = {
        "API_THROTTLE_RATE_ANON": [validate_api_rate],
        "API_THROTTLE_RATE_USER": [validate_api_rate],
        "API_THROTTLE_REPEATED_REQUEST_RATE_CIDR": [validate_api_rate],
        "API_THROTTLE_REPEATED_REQUEST_ENABLED_CIDR": [validate_bool],
        "API_THROTTLE_REPEATED_REQUEST_RATE_IP": [validate_api_rate],
        "API_THROTTLE_REPEATED_REQUEST_ENABLED_IP": [validate_bool],
        "API_THROTTLE_REPEATED_REQUEST_RATE_USER": [validate_api_rate],
        "API_THROTTLE_REPEATED_REQUEST_ENABLED_USER": [validate_bool],
        "API_THROTTLE_REPEATED_REQUEST_RATE_ORG": [validate_api_rate],
        "API_THROTTLE_REPEATED_REQUEST_ENABLED_ORG": [validate_bool],
        "API_THROTTLE_MELISSA_RATE_ADMIN": [validate_api_rate],
        "API_THROTTLE_MELISSA_RATE_USER": [validate_api_rate],
        "API_THROTTLE_MELISSA_RATE_ORG": [validate_api_rate],
        "API_THROTTLE_MELISSA_RATE_IP": [validate_api_rate],
        "API_THROTTLE_MELISSA_ENABLED_ADMIN": [validate_bool],
        "API_THROTTLE_MELISSA_ENABLED_USER": [validate_bool],
        "API_THROTTLE_MELISSA_ENABLED_ORG": [validate_bool],
        "API_THROTTLE_MELISSA_ENABLED_IP": [validate_bool],
        "API_THROTTLE_RATE_WRITE": [validate_api_rate],
    }

    @classmethod
    def get_setting_value(cls, setting):
        """
        Get the current value of the setting specified by
        its setting name.

        If no instance has been saved for the specified setting
        the default value will be returned.
        """
        try:
            instance = cls.objects.get(setting=setting)
            return instance.value
        except cls.DoesNotExist:
            return getattr(settings, setting)

    @classmethod
    def validate_value(cls, setting, value):
        if value is None:
            return value

        for validator in cls.setting_validators.get(setting, []):
            value = validator(value)
        return value

    @property
    def value(self):
        """
        Get the value for this setting.
        """
        return getattr(self, self.setting_to_field[self.setting])

    def __str__(self):
        return f"EnvironmentSetting `{self.setting}` ({self.id})"

    def clean(self):
        self.validate_value(self.setting, self.value)

    def set_value(self, value):
        """
        Update the value for this setting.
        """

        setattr(
            self,
            self.setting_to_field[self.setting],
            self.validate_value(self.setting, value),
        )

        self.full_clean()
        self.save()


class OAuthApplication(oauth2.AbstractApplication, StripFieldMixin):
    """
    OAuth application - extends the default oauth_provider2 application
    and adds optional org ownership to it through an `org` relationship
    """

    org = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        help_text=_("application is owned by this organization"),
        related_name="oauth_applications",
        on_delete=models.CASCADE,
    )

    objects = oauth2.ApplicationManager()

    class Meta(oauth2.AbstractApplication.Meta):
        db_table = "peeringdb_oauth_application"
        verbose_name = _("OAuth Application")
        verbose_name_plural = _("OAuth Applications")

    def natural_key(self):
        return (self.client_id,)

    def clean(self):
        # user should not be set on org owned apps
        if self.org_id and self.user_id:
            self.user = None


class OAuthGrantInfo(StripFieldMixin):
    """
    OAuth grant info

    Used to store additional information about a grant

    - amr: Authentication method reference set on the session that
        created the grant
    """

    grant = models.OneToOneField(
        oauth2.Grant,
        on_delete=models.CASCADE,
        related_name="grant_info",
    )

    amr = models.CharField(
        max_length=255,
        help_text=_("Authentication method reference"),
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "peeringdb_oauth_grant_info"
        verbose_name = _("OAuth Grant Info")
        verbose_name_plural = _("OAuth Grant Info")


class OAuthAccessTokenInfo(StripFieldMixin):
    """
    OAuth access token info

    Used to store additional information about an access token

    - amr: Authentication method reference set on the session that
        created the grant that resulted in this access token
    """

    access_token = models.OneToOneField(
        oauth2.AccessToken,
        on_delete=models.CASCADE,
        related_name="access_token_info",
    )

    amr = models.CharField(
        max_length=255,
        help_text=_("Authentication method reference"),
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "peeringdb_oauth_access_token_info"
        verbose_name = _("OAuth Access Token Info")
        verbose_name_plural = _("OAuth Access Token Info")


WATCHABLE_OBJECTS = [
    ("net", _("Network")),
]

DATACHANGE_OBJECTS = [
    ("netixlan", "netixlan"),
]

DATACHANGE_ACTIONS = [
    ("add", _("Added")),
    ("modify", _("Updated")),
    ("delete", _("Deleted")),
]


class DataChangeWatchedObject(StripFieldMixin):
    """
    Describes a user's intention to be notified about
    changes to a specific objects.

    Currently only `net` objects are watchable
    """

    user = models.ForeignKey(
        User, related_name="watched_objects", on_delete=models.CASCADE
    )

    # object being watched

    ref_tag = models.CharField(choices=WATCHABLE_OBJECTS, max_length=255)
    object_id = models.PositiveIntegerField()

    created = models.DateTimeField(
        auto_now_add=True, help_text=_("User started watching this object at this time")
    )

    # last time user had a notification sent for changes to this object

    last_notified = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Last time user was notified about changes to this object"),
    )

    class Meta:
        db_table = "peeringdb_data_change_watch"
        verbose_name = _("Data Change Watched Object")
        verbose_name_plural = _("Data Change Watched Object")

        indexes = [
            models.Index(fields=["ref_tag", "object_id"], name="data_change_watch_obj")
        ]

        unique_together = (("user", "ref_tag", "object_id"),)

    @classmethod
    def watching(cls, user, obj):
        if isinstance(user, AnonymousUser):
            return False

        return cls.objects.filter(
            user=user, ref_tag=obj.HandleRef.tag, object_id=obj.id
        ).exists()

    @classmethod
    def cleanup(cls):
        """
        1) checks for deleted objects and removes all watched object instances for them

        2) only users that write permissions to the watched object are eligible for notifications
        """

        qset = cls.objects.all().select_related("user")
        deleted = 0

        for obj in qset:
            user = obj.user
            stale = False
            try:
                watched = obj.watched_object

                if watched.status == "deleted":
                    stale = True
                elif not check_permissions(user, watched, "crud"):
                    stale = True
            except REFTAG_MAP[obj.ref_tag].DoesNotExist:
                stale = True

            if stale:
                obj.delete()
                deleted += 1

        return deleted

    @classmethod
    def collect(cls):
        """
        Collects all instances that require notifications to be sent.

        This will take into account created/last_notified data of the DataChangeWatchedObject
        instance to determine new notifications.

        Returns

        - dict, dict where the first dictionary is a mapping of user id to `User` and the
          second dictionary is a mapping of user id to a dicitionary structure holding collected
          notifications for the user as decribed below.

          ```
          {
                (watched_ref_tag, watched_object_id): {
                    "watched": DataChangeWatchedObject,
                    "entries": {
                        (ref_tag, id): list<DataChangeNotificationQueue>
                    }
                }
          }
          ```
        """

        qset = cls.objects.all().select_related("user")

        collected = {}
        users = {}

        for watched in qset:
            collected.setdefault(watched.user_id, {})
            key = (watched.ref_tag, watched.object_id)

            users[watched.user_id] = watched.user

            if watched.last_notified:
                date_limit = watched.last_notified
            else:
                date_limit = watched.created

            entries = DataChangeNotificationQueue.consolidate(
                watched.ref_tag, watched.object_id, date_limit
            )

            if entries:
                collected[watched.user_id][key] = {
                    "watched": watched,
                    "entries": entries,
                }

        for user_id, notifications in list(collected.items()):
            if not notifications:
                del users[user_id]
                del collected[user_id]

        return users, collected

    @property
    def watched_object(self):
        """
        Returns instance of the watched object
        """
        if not hasattr(self, "_watched_object"):
            self._watched_object = REFTAG_MAP[self.ref_tag].objects.get(
                id=self.object_id
            )

        return self._watched_object

    @property
    def changes_since(self):
        return self.last_notified or self.created

    def __str__(self):
        return f"{self.ref_tag}.{self.object_id} ({self.pk})"


class DataChangeNotificationQueue(StripFieldMixin):
    # object being watched
    # this serves as a point of consolidation, notifications will be sent
    # out as a summary for this object
    # e.g., a network

    watched_ref_tag = models.CharField(choices=WATCHABLE_OBJECTS, max_length=255)
    watched_object_id = models.PositiveIntegerField()

    # notification target
    # the object that has had changes that warrant notification
    # e.g., a netixlan

    ref_tag = models.CharField(max_length=255)
    object_id = models.PositiveIntegerField()

    reason = models.CharField(
        max_length=255, help_text=_("Reason for notification"), null=True, blank=True
    )

    # keeping track of object versions

    version_before = models.ForeignKey(
        reversion.models.Version,
        related_name="data_change_notification_before",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    version_after = models.ForeignKey(
        reversion.models.Version,
        related_name="data_change_notification_after",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    # descriptor of action done to the object (e.g.,

    action = models.CharField(max_length=255, choices=DATACHANGE_ACTIONS)

    source = models.CharField(max_length=32, help_text=_("Source of automated update"))

    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "peeringdb_data_change_notify"
        verbose_name = _("Data Change Notification Queue")
        verbose_name_plural = _("Data Change Notification Queue")

        indexes = [
            models.Index(
                fields=["watched_ref_tag", "watched_object_id"],
                name="data_change_notify_watch",
            ),
            models.Index(
                fields=["ref_tag", "object_id"], name="data_change_notify_target"
            ),
        ]

    @classmethod
    def push(cls, source, action, obj, version_before, version_after, **kwargs):
        if not hasattr(obj, "data_change_parent"):
            raise AttributeError(f"{obj} does not have a `data_change_parent` property")

        watched_ref_tag, watched_object_id = obj.data_change_parent

        # check if any user has set up a watched object
        # for the data change parent. If no user has set it up
        # dont push a notification as no one is watching anyway.

        parent_is_watched = DataChangeWatchedObject.objects.filter(
            ref_tag=watched_ref_tag, object_id=watched_object_id
        ).exists()

        if not parent_is_watched:
            return

        # create notification entry

        entry = cls(
            action=action,
            watched_ref_tag=watched_ref_tag,
            watched_object_id=watched_object_id,
            ref_tag=obj.HandleRef.tag,
            object_id=obj.id,
            version_before=version_before,
            version_after=version_after,
            reason=kwargs.get("reason"),
            source=source,
        )

        entry.full_clean()
        entry.save()

        return entry

    @classmethod
    def consolidate(cls, watched_ref_tag, watched_object_id, date_limit):
        """
        Returns a dict of all DataChangeQueueNotification entries for the specified
        ref tag and object id.

        `date_limit` is the cut off point for considering eligible notifications (notifications
        older than this date will be ignored)
        """

        qset = cls.objects.filter(
            watched_ref_tag=watched_ref_tag,
            watched_object_id=watched_object_id,
            created__gte=date_limit,
        ).order_by("created")

        actions = {}

        if not qset.exists():
            return actions

        for entry in qset:
            key = (entry.ref_tag, entry.object_id)
            actions.setdefault(key, [])
            actions[key].append(entry)

        return actions

    @property
    def data(self):
        """
        Retrieve relevant data from the version snap shot of the notification
        object
        """

        if not hasattr(self, "_data"):
            self._data = self.version_after.field_dict
        return self._data

    @property
    def title(self):
        """
        Used to label a change to an object in the notification message
        """

        title_fn = getattr(self, f"title_{self.ref_tag}")
        return title_fn

    @property
    def title_netixlan(self):
        """
        Used to label a change to a netixlan in the notification message
        """

        asn = self.data["asn"]
        ip4 = self.data["ipaddr4"] or ""
        ip6 = self.data["ipaddr6"] or ""
        return f"AS{asn} {ip4} {ip6}"

    @property
    def details(self):
        """
        Generates a string describing change details according to
        notification object type, action type and notification
        source

        Will return self.reason if nothing else can be gathered.
        """

        if self.source == "ixf":
            ix = InternetExchange.objects.get(id=self.data["ixlan_id"])
            details = [
                f"This change was the result of an IX-F import for { ix.name }",
                self.reason or "",
            ]

            if self.action == "add":
                details = [
                    f"Speed: {format_speed(self.data['speed'])}",
                    f"RS Peer: {self.data['is_rs_peer']}",
                    f"Operational: {self.data['operational']}",
                ] + details

            details += [
                f"Exchange: {ix.view_url}",
            ]

            return "\n".join(details)

        return self.reason

    @property
    def watched_object(self):
        """
        Returns instance of the watched object
        """

        if not hasattr(self, "_watched_object"):
            self._watched_object = REFTAG_MAP[self.watched_ref_tag].objects.get(
                id=self.watched_object_id
            )

        return self._watched_object

    @property
    def target_object(self):
        """
        Returns instance of the target object
        """

        if not hasattr(self, "_target_object"):
            self._target_object = REFTAG_MAP[self.ref_tag].objects.get(
                id=self.object_id
            )

        return self._target_object

    @property
    def target_id(self):
        return (self.ref_tag, self.object_id)


class EmailAddressData(StripFieldMixin):
    email = models.OneToOneField(
        EmailAddress, on_delete=models.CASCADE, related_name="data"
    )
    confirmed_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "peeringdb_email_address_data"


class DataChangeEmail(StripFieldMixin):
    user = models.ForeignKey(
        User, related_name="data_change_emails", on_delete=models.CASCADE
    )
    watched_object = models.ForeignKey(
        DataChangeWatchedObject,
        related_name="data_change_emails",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    email = models.EmailField()
    content = models.TextField()
    subject = models.CharField(max_length=255)

    created = models.DateTimeField(auto_now_add=True)
    sent = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "peeringdb_data_change_email"
        verbose_name = _("Data Change Email")
        verbose_name_plural = _("Data Change Emails")

    def send(self):
        if self.sent is not None:
            raise ValueError("Cannot send email again")

        if settings.DATA_CHANGE_SEND_EMAILS:
            self.user.email_user(self.subject, self.content)
            self.sent = timezone.now()
            self.save()


REFTAG_MAP = {
    cls.handleref.tag: cls
    for cls in [
        Organization,
        Network,
        Carrier,
        CarrierFacility,
        Facility,
        InternetExchange,
        InternetExchangeFacility,
        NetworkFacility,
        NetworkIXLan,
        NetworkContact,
        IXLan,
        IXLanPrefix,
        Campus,
    ]
}


QUEUE_ENABLED = []
QUEUE_NOTIFY = []

if not getattr(settings, "DISABLE_VERIFICATION_QUEUE", False):
    # enable verification queue for these models
    QUEUE_ENABLED = (User, InternetExchange, Facility, Carrier, Organization)

    if not getattr(settings, "DISABLE_VERIFICATION_QUEUE_EMAILS", False):
        # send admin notification emails for these models
        QUEUE_NOTIFY = (InternetExchange, Facility, Carrier, Organization)
