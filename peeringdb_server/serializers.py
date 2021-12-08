"""
REST API Serializer definitions.
REST API POST / PUT data validators.

New serializers should extend ModelSerializer class, which is a custom extension
of django-rest-framework's ModelSerializer.

Custom ModelSerializer implements logic for the expansion of relationships driven by the `depth` url parameter. The depth parameter indicates how many objects to recurse into.

Special api filtering implementation should be done through the `prepare_query`
method.
"""

import ipaddress
import re

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldError, ValidationError
from django.core.validators import URLValidator
from django.db.models import Prefetch
from django.db.models.expressions import RawSQL
from django.db.models.fields.related import (
    ForwardManyToOneDescriptor,
    ReverseManyToOneDescriptor,
)
from django.db.models.query import QuerySet
from django.utils.translation import ugettext_lazy as _
from django_grainy.rest import PermissionDenied

# from drf_toolbox import serializers
from django_handleref.rest.serializers import HandleRefSerializer
from django_inet.rest import IPAddressField, IPNetworkField
from django_peeringdb.const import AVAILABLE_VOLTAGE
from django_peeringdb.models.abstract import AddressModel
from rest_framework import serializers, validators
from rest_framework.exceptions import ValidationError as RestValidationError

from peeringdb_server.deskpro import (
    ticket_queue_asnauto_skipvq,
    ticket_queue_rdap_error,
)
from peeringdb_server.inet import (
    RdapException,
    RdapInvalidRange,
    RdapLookup,
    get_prefix_protocol,
    rdap_pretty_error_message,
)
from peeringdb_server.models import (
    QUEUE_ENABLED,
    Facility,
    GeoCoordinateCache,
    InternetExchange,
    InternetExchangeFacility,
    IXLan,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    VerificationQueueItem,
)
from peeringdb_server.permissions import (
    check_permissions_from_request,
    get_org_key_from_request,
    get_user_from_request,
    validate_rdap_user_or_key,
)
from peeringdb_server.validators import (
    validate_address_space,
    validate_info_prefixes4,
    validate_info_prefixes6,
    validate_irr_as_set,
    validate_phonenumber,
    validate_poc_visible,
    validate_prefix_overlap,
    validate_zipcode,
)

# exclude certain query filters that would otherwise
# be exposed to the api for filtering operations

FILTER_EXCLUDE = [
    # unused
    "org__latitude",
    "org__longitude",
    "ixlan_set__descr",
    "ixlan__descr",
    # private
    "ixlan_set__ixf_ixp_member_list_url",
    "ixlan__ixf_ixp_member_list_url",
    "network__notes_private",
    # internal
    "ixf_import_log_set__id",
    "ixf_import_log_set__created",
    "ixf_import_log_set__updated",
    "ixf_import_log_entries__id",
    "ixf_import_log_entries__action",
    "ixf_import_log_entries__reason",
    "sponsorshiporg_set__id",
    "sponsorshiporg_set__url",
    "partnerships__id",
    "partnerships__url",
    "merged_to__id",
    "merged_to__created",
    "merged_from__id",
    "merged_from__created",
    "affiliation_requests__status",
    "affiliation_requests__created",
    "affiliation_requests__org_name",
    "affiliation_requests__id",
]


# def _(x):
#    return x


class GeocodeSerializerMixin:
    """
    Override create() and update() method of serializer
    to normalize the location against the Google Maps Geocode API
    and resave the model instance with normalized address fields.

    Can only be used if the model includes the GeocodeBaseMixin.
    """

    GEO_ERROR_MESSAGE = _(
        "We could not find the address you entered. "
        "Please review your address data and contact "
        "{} for further assistance "
        "if needed."
    ).format(settings.DEFAULT_FROM_EMAIL)

    def _geosync_information_present(self, instance, validated_data):
        """
        Determine if there is enough address information
        to necessitate a geosync attempt.
        """

        for f in AddressSerializer.Meta.fields:

            # We do not need to sync if only the country is defined
            if f == "country":
                continue

            if validated_data.get(f) != "":
                return True

        return False

    def _need_geosync(self, instance, validated_data):
        """
        Determine if any geofields that have changed need normalization.
        Returns False if the only change is that fields have been deleted.
        """

        # If there isn't any data besides country, don't sync
        geosync_info_present = self._geosync_information_present(
            instance, validated_data
        )

        if not geosync_info_present:
            return False

        # We do not need to resync if floor, suite and geo coords are changed
        ignored_fields = ["floor", "suite", "latitude", "longitude"]
        geocode_fields = [
            f for f in AddressSerializer.Meta.fields if f not in ignored_fields
        ]

        for field in geocode_fields:
            if validated_data.get(field) == "":
                continue

            if getattr(instance, field) != validated_data.get(field):
                return True

        return False

    def _add_meta_information(self, metadata):
        """
        Adds a dictionary of metadata to the "meta" field of the API
        request, so that it ends up in the API response.
        """
        if "request" in self.context:
            request = self.context["request"]
            if not hasattr(request, "meta_response"):
                request.meta_response = {}
            request.meta_response.update(metadata)
            return True

        return False

    def handle_geo_error(self, exc, instance):
        """
        Issue #939: In the event that there is an error in geovalidating
        the address (including address not found), a warning is returned in
        the "meta" field of the response and null the latitude and
        longitude on the instance.
        """
        self._add_meta_information(
            {
                "geovalidation_warning": self.GEO_ERROR_MESSAGE,
            }
        )
        print(exc.message)
        instance.latitude = None
        instance.longitude = None
        instance.save()

    def needs_address_suggestion(self, suggested_address, instance):
        """
        Issue #940: If the geovalidated address meaningfully differs
        from the address the user provided, we return True to signal
        a address suggestion should be provided to the user.
        """

        if not suggested_address:
            return False

        for key in ["address1", "city", "state", "zipcode"]:
            suggested_val = suggested_address.get(key, None)
            instance_val = getattr(instance, key, None)
            if instance_val != suggested_val:
                return True

        return False

    def update(self, instance, validated_data):
        """
        When updating a geo-enabled object,
        update the model first
        and then normalize the geofields.
        """

        # Need to check if we need geosync before updating the instance
        need_geosync = self._need_geosync(instance, validated_data)

        instance = super().update(instance, validated_data)

        # we dont want to geocode on tests
        if settings.RELEASE_ENV == "run_tests":
            return instance

        if need_geosync:
            try:
                suggested_address = instance.process_geo_location()

                if self.needs_address_suggestion(suggested_address, instance):
                    self._add_meta_information(
                        {
                            "suggested_address": suggested_address,
                        }
                    )

            # Reraise the model validation error
            # as a serializer validation error
            except ValidationError as exc:
                self.handle_geo_error(exc, instance)

        return instance

    def create(self, validated_data):
        # When creating a geo-enabled object,
        # we first want to save the model
        # and then normalize the geofields
        instance = super().create(validated_data)

        # we dont want to geocode on tests
        if settings.RELEASE_ENV == "run_tests":
            return instance

        if self._geosync_information_present(instance, validated_data):
            try:
                suggested_address = instance.process_geo_location()

                if self.needs_address_suggestion(suggested_address, instance):
                    self._add_meta_information(
                        {
                            "suggested_address": suggested_address,
                        }
                    )

            # Reraise the model validation error
            # as a serializer validation error
            except ValidationError as exc:
                self.handle_geo_error(exc, instance)
        return instance


def queryable_field_xl(fld):
    """
    Translate <fld>_id into <fld> and also translate fac and net queries into "facility"
    and "network" queries.

    FIXME: should be renamed on model schema.
    """

    if re.match("^.+[^_]_id$", fld):

        # if field name is {rel}_id strip the `_id` suffix

        fld = fld[:-3]

    if fld == "fac":

        # if field name is `fac` rename to `facility`
        # since the model relationship field is called `facility`

        return "facility"

    elif fld == "net":

        # if field name is `net` rename to `network`
        # since the model relationship field is called `network`

        return "network"

    elif re.match("net_(.+)", fld):

        # if field name starts with `net_` rename to `network_`
        # since the model relationship field is called `network`

        return re.sub("^net_", "network_", fld)

    elif re.match("fac_(.+)", fld):

        # if field name starts with `fac_` rename to `facility_`
        # since the model relationship field is called `facility`

        return re.sub("^fac_", "facility_", fld)

    return fld


def single_url_param(params, key, fn=None):
    v = params.get(key)

    if not v:
        return None

    if isinstance(v, list):
        v = v[0]

    try:
        if fn:
            v = fn(v)
    except ValueError:
        raise ValidationError({key: _("Invalid value")})
    except Exception as exc:
        raise ValidationError({key: exc})

    return v


def validate_relation_filter_field(a, b):
    b = queryable_field_xl(b)
    a = queryable_field_xl(a)
    if a == b or a == "%s_id" % b or a.find("%s__" % b) == 0:
        return True
    return False


def get_relation_filters(flds, serializer, **kwargs):
    rv = {}
    for k, v in list(kwargs.items()):
        m = re.match("^(.+)__(lt|lte|gt|gte|contains|startswith|in)$", k)
        if isinstance(v, list) and v:
            v = v[0]
        if m and len(k.split("__")) <= 2:
            r = m.group(1)
            f = m.group(2)
            rx = r.split("__")
            if f == "contains":
                f = "icontains"
            elif f == "startswith":
                f = "istartswith"
            if len(rx) == 2:
                rx[0] = queryable_field_xl(rx[0])
                rx[1] = queryable_field_xl(rx[1])
                r_field = rx[0]
                r = "__".join(rx)
            else:
                r_field = r
                r = queryable_field_xl(r)
            if r_field in flds:
                if f == "in":
                    v = v.split(",")
                rv[r] = {"filt": f, "value": v}
        elif k in flds:
            rv[queryable_field_xl(k)] = {"filt": None, "value": v}
        else:
            rx = k.split("__")

            if len(rx) in [2, 3] and rx[0] in flds:
                rx[0] = queryable_field_xl(rx[0])
                rx[1] = queryable_field_xl(rx[1])
                m = re.match("^(.+)__(lt|lte|gt|gte|contains|startswith|in)$", k)
                f = None
                if m:
                    f = m.group(2)
                if f == "in":
                    v = v.split(",")
                rv["__".join(rx[:2])] = {"filt": f, "value": v}

    return rv


class UniqueFieldValidator:
    """
    For issue #70:

    Django-side unique field validation.

    Ideally this is done in mysql, however the other
    duplicates need to be cleared first, so validate on the django side initially.
    """

    message = _("Need to be unique")

    def __init__(self, fields, message=None, check_deleted=False):
        self.fields = fields
        self.message = message or self.message
        self.check_deleted = check_deleted

    def set_context(self, serializer):
        self.instance = getattr(serializer, "instance", None)
        self.model = serializer.Meta.model

    def __call__(self, attrs):
        id = getattr(self.instance, "id", 0)
        collisions = {}
        for field in self.fields:
            value = attrs.get(field)

            if value == "" or value is None:
                continue

            filters = {field: value}
            if not self.check_deleted:
                filters.update(status="ok")
            if self.model.objects.filter(**filters).exclude(id=id).exists():
                collisions[field] = self.message
        if collisions:
            raise RestValidationError(collisions, code="unique")


class RequiredForMethodValidator:
    """
    A validator that makes a field required for certain
    methods.
    """

    message = _("This field is required")

    def __init__(self, field, methods=["POST", "PUT"], message=None):
        self.field = field
        self.methods = methods
        self.messages = message or self.message

    def __call__(self, attrs):
        if self.request.method in self.methods and not attrs.get(self.field):
            raise RestValidationError(
                {self.field: self.message.format(methods=self.methods)}
            )

    def set_context(self, serializer):
        self.instance = getattr(serializer, "instance", None)
        self.request = serializer._context.get("request")


class SoftRequiredValidator:
    """
    A validator that allows us to require that at least
    one of the specified fields is set.
    """

    message = _("This field is required")

    def __init__(self, fields, message=None):
        self.fields = fields
        self.message = message or self.message

    def set_context(self, serializer):
        self.instance = getattr(serializer, "instance", None)

    def __call__(self, attrs):
        missing = {
            field_name: self.message
            for field_name in self.fields
            if not attrs.get(field_name)
        }
        valid = len(self.fields) != len(list(missing.keys()))
        if not valid:
            raise RestValidationError(missing)


class AsnRdapValidator:
    """
    A validator that queries rdap entries for the provided value (Asn)
    and will fail if no matching asn is found.
    """

    message = _("RDAP Lookup Error")

    def __init__(self, field="asn", message=None, methods=None):
        if message:
            self.message = message
        if not methods:
            methods = ["POST"]
        self.field = field
        self.methods = methods

    def __call__(self, attrs):
        if self.request.method not in self.methods:
            return
        asn = attrs.get(self.field)
        try:
            rdap = RdapLookup().get_asn(asn)
            rdap.emails
            self.request.rdap_result = rdap
        except RdapInvalidRange as exc:
            # Issue 995: Block registering private ASN ranges
            # raise an error if ANS is in private or reserved range
            raise RestValidationError({self.field: rdap_pretty_error_message(exc)})
        except RdapException as exc:
            self.request.rdap_error = (asn, exc)
            raise RestValidationError({self.field: rdap_pretty_error_message(exc)})

    def set_context(self, serializer):
        self.instance = getattr(serializer, "instance", None)
        self.request = serializer._context.get("request")


class FieldMethodValidator:
    """
    A validator that will only allow a field to be set for certain
    methods.
    """

    message = _("This field is only allowed for these requests: {methods}")

    def __init__(self, field, methods, message=None):
        self.field = field
        self.methods = methods

    def __call__(self, attrs):
        if self.field not in attrs:
            return
        if self.request.method not in self.methods:
            raise RestValidationError(
                {self.field: self.message.format(methods=self.methods)}
            )

    def set_context(self, serializer):
        self.instance = getattr(serializer, "instance", None)
        self.request = serializer._context.get("request")


class ExtendedURLField(serializers.URLField):
    def __init__(self, **kwargs):
        schemes = kwargs.pop("schemes", None)
        super().__init__(**kwargs)
        validator = URLValidator(
            message=self.error_messages["invalid"], schemes=schemes
        )
        self.validators = []
        self.validators.append(validator)


class SaneIntegerField(serializers.IntegerField):
    """
    Integer field that renders null values to 0.
    """

    def get_attribute(self, instance):
        r = super().get_attribute(instance)
        if r is None:
            return 0
        return r


class ParentStatusException(IOError):
    """
    Throw this when an object cannot be created because its parent is
    either status pending or deleted.
    """

    def __init__(self, parent, typ):
        if parent.status == "pending":
            super().__init__(
                _(
                    "Object of type '%(type)s' cannot be created because its parent entity '%(parent_tag)s/%(parent_id)s' has not yet been approved"
                )
                % {"type": typ, "parent_tag": parent.ref_tag, "parent_id": parent.id}
            )
        elif parent.status == "deleted":
            super().__init__(
                _(
                    "Object of type '%(type)s' cannot be created because its parent entity '%(parent_tag)s/%(parent_id)s' has been marked as deleted"
                )
                % {"type": typ, "parent_tag": parent.ref_tag, "parent_id": parent.id}
            )


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = (AddressModel,)
        fields = [
            "address1",
            "address2",
            "city",
            "country",
            "state",
            "zipcode",
            "floor",
            "suite",
            "latitude",
            "longitude",
        ]


class ModelSerializer(serializers.ModelSerializer):
    """
    ModelSerializer that provides DB API with custom params.

    Main problem with doing field ops here is data is already fetched, so while
    it's fine for single columns, it doesn't help on speed for fk relationships.
    However data is not yet serialized so there may be some gain.

    Using custom method fields to introspect doesn't work at all, because
    they're not called until they're serialized, and then are called once per row,

    for example
    test_depth = serializers.SerializerMethodField('check_for_fk')
    def check_for_fk(self, obj):
        print "check ", type(obj)

    class Meta:
        fields = [
            'test_depth',
            ...

    Best bet so far looks like overloading the single object GET in the model
    view set, and adding on the relationships, but need to GET to GET the fields
    defined yet not included in the query, may have to rewrite the base class,
    which would mean talking to the dev and committing back or we'll have this problem
    every update.

    After testing, the time is all in serialization and transfer, so culling
    related here should be fine.

    arg[0] is a queryset, but seems to have already been evaluated

    Addition Query arguments:
    `fields` comma separated list of only fields to display

        could cull the default list down quite a bit by default and make people ask explicitly for them
        self.Meta.default_fields, but I'm not sure it matters, more testing
    """

    is_model = True
    nested_exclude = []

    id = serializers.IntegerField(read_only=True)

    def __init__(self, *args, **kwargs):
        # args[0] is either a queryset or a model
        # kwargs: {u'context': {u'view': <peeringdb.rest.NetworkViewSet object
        # at 0x7fa5604e8410>, u'request': <rest_framework.request.Request
        # object at 0x7fa5604e86d0>, u'format': None}}

        try:
            data = args[0]
        except IndexError:
            data = None

        if "request" in kwargs.get("context", {}):
            request = kwargs.get("context").get("request")
        else:
            request = None

        is_list = isinstance(data, QuerySet)
        self.nested_depth = self.depth_from_request(request, is_list)

        # Instantiate the superclass normally
        super().__init__(*args, **kwargs)

        if not request:
            return

        fields = self.context["request"].query_params.get("fields")

        if fields:
            fields = fields.split(",")
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields.keys())
            for field_name in existing - allowed:
                self.fields.pop(field_name)

    @classmethod
    def queryable_field_xl(self, fld):
        return queryable_field_xl(fld)

    @classmethod
    def is_unique_query(cls, request):
        """
        Check if the request parameters are expected to return a unique entity.
        """

        return "id" in request.GET

    @classmethod
    def queryable_relations(self):
        """
        Returns a list of all second level queryable relation fields.
        """
        rv = []

        for fld in self.Meta.model._meta.get_fields():

            if fld.name in FILTER_EXCLUDE:
                continue

            if (
                hasattr(fld, "get_internal_type")
                and fld.get_internal_type() == "ForeignKey"
            ):
                model = fld.related_model
                for _fld in model._meta.get_fields():
                    field_name = f"{fld.name}__{_fld.name}"

                    if field_name in FILTER_EXCLUDE:
                        continue

                    if (
                        hasattr(_fld, "get_internal_type")
                        and _fld.get_internal_type() != "ForeignKey"
                    ):
                        rv.append((field_name, _fld))
        return rv

    @classmethod
    def prefetch_query(cls, qset, request):
        if hasattr(request, "_ctf"):
            qset = qset.filter(**request._ctf)
        return qset

    @classmethod
    def depth_from_request(cls, request, is_list):
        """
        Derive aproporiate depth parameter from request. Max and default depth will vary depending on whether
        result set is a list or single object.

        This will return the depth specified in the request or the next best
        possible depth.
        """
        try:
            if not request:
                raise ValueError("No Request")
            return min(
                int(request.query_params.get("depth", cls.default_depth(is_list))),
                cls.max_depth(is_list),
            )
        except ValueError:
            return cls.default_depth(is_list)

    @classmethod
    def max_depth(cls, is_list):
        """
        Return max depth according to whether resultset is list or single GET.
        """
        if is_list:
            return 3
        return 4

    @classmethod
    def default_depth(cls, is_list):
        """
        Return default depth according to whether resultset is list or single GET.
        """
        if is_list:
            return 0
        return 2

    @classmethod
    def prefetch_related(
        cls,
        qset,
        request,
        prefetch=None,
        related=None,
        nested="",
        depth=None,
        is_list=False,
        single=None,
        selective=None,
    ):
        """
        Prefetch related sets according to depth specified in the request.

        Prefetched set data will be located off the instances in an attribute
        called "<tag>_set_active_prefetched" where tag is the handleref tag
        of the objects the set will be holding.
        """

        if depth is None:
            depth = cls.depth_from_request(request, is_list)

        if prefetch is None:
            prefetch = []
            related = []
        if depth <= 0:
            return qset

        if hasattr(cls.Meta, "fields"):
            for fld in cls.Meta.related_fields:

                # cycle through all related fields declared on the serializer

                o_fld = fld

                # selective is specified, check that field is matched
                # otherwise ignore
                if selective and fld not in selective:
                    continue

                # if the field is not to be rendered, skip it
                if fld not in cls.Meta.fields:
                    continue

                # if we're in list serializer get the actual serializer class
                child = getattr(cls._declared_fields.get(fld), "child", None)
                getter = None

                # there are still a few instances where model and serializer
                # fields differ, net_id -> network_id in some cases for example
                #
                # in order to get the actual model field source we can check
                # the primary key relation ship field on the serializer which
                # has the same name with '_id' prefixed to it
                pk_rel_fld = cls._declared_fields.get("%s_id" % fld)

                # if serializer class specifies a through field name, rename
                # field to that
                if child and child.Meta.through:
                    fld = child.Meta.through

                # if primary key relationship field was found and source differs
                # we want to use that source instead
                elif pk_rel_fld and pk_rel_fld.source != fld:
                    fld = pk_rel_fld.source

                # set is getting its values via a proxy attribute specified
                # in the serializer's Meta class as getter
                getter = getattr(cls.Meta, "getter", None)

                # retrieve the model field for the relationship
                model_field = getattr(cls.Meta.model, fld, None)

                if type(model_field) == ReverseManyToOneDescriptor:

                    # nested sets

                    # build field and attribute names to prefetch to, this function will be
                    # called in a nested fashion so it is important we keep an aproporiate
                    # attribute "path" in tact
                    if not nested:
                        src_fld = fld
                        attr_fld = "%s_active_prefetched" % fld
                    else:
                        if getter:
                            src_fld = f"{nested}__{getter}__{fld}"
                        else:
                            src_fld = f"{nested}__{fld}"
                        attr_fld = "%s_active_prefetched" % fld

                    route_fld = "%s_active_prefetched" % src_fld

                    # print "(SET)", src_fld, attr_fld, getattr(cls.Meta.model,
                    # fld).related.related_model

                    # build the Prefetch object

                    prefetch.append(
                        Prefetch(
                            src_fld,
                            queryset=cls.prefetch_query(
                                getattr(
                                    cls.Meta.model, fld
                                ).rel.related_model.objects.filter(status="ok"),
                                request,
                            ),
                            to_attr=attr_fld,
                        )
                    )

                    # expanded objects within sets may contain sets themselves,
                    # so make sure to prefetch those as well
                    cls._declared_fields.get(o_fld).child.prefetch_related(
                        qset,
                        request,
                        related=related,
                        prefetch=prefetch,
                        nested=route_fld,
                        depth=depth - 1,
                        is_list=is_list,
                    )

                elif type(model_field) == ForwardManyToOneDescriptor and not is_list:

                    # single relations

                    if not nested:
                        src_fld = fld
                        related.append(fld)
                    else:
                        if getter:
                            src_fld = f"{nested}__{getter}__{fld}"
                        else:
                            src_fld = f"{nested}__{fld}"

                    route_fld = src_fld

                    # print "(SINGLE)", fld, src_fld, route_fld, model_field

                    # expanded single realtion objects may contain sets, so
                    # make sure to prefetch those as well

                    REFTAG_MAP.get(o_fld).prefetch_related(
                        qset,
                        request,
                        single=fld,
                        related=related,
                        prefetch=prefetch,
                        nested=route_fld,
                        depth=depth - 1,
                        is_list=is_list,
                    )

            if not nested:
                # print "prefetching", [p.prefetch_through for p in prefetch]
                # qset = qset.select_related(*related).prefetch_related(*prefetch)
                qset = qset.prefetch_related(*prefetch)
        return qset

    @property
    def is_root(self):
        if not self.parent:
            return True
        if type(self.parent) == serializers.ListSerializer and not self.parent.parent:
            return True
        return False

    @property
    def in_list(self):
        return type(self.parent) == serializers.ListSerializer

    @property
    def depth(self):
        par = self
        depth = -1
        nd = getattr(par, "nested_depth", 0)
        while par:
            b = hasattr(par, "is_model")
            depth += 1
            if hasattr(par, "nested_depth"):
                nd = par.nested_depth
            par = par.parent

        return (depth, nd + 1, b)

    @property
    def current_depth(self):
        d, nd, a = self.depth
        return nd - d, d, nd, a

    def to_representation(self, data):
        d, x, y, a = self.current_depth

        # a specified whether or not the serialization root is
        # a signle object or a queryset (e.g GET vs GET /<id>)
        # we need to adjust depth limits accordingly due to drf
        # internal parent - child structuring
        if a:
            k = 2
            j = 1
        else:
            k = 1
            j = 0

        r = self.is_root
        pop_related = False
        return_full = True

        if r:
            # main element
            if d < k:
                pop_related = True

        else:
            # sub element
            if self.in_list:
                # sub element in set
                if d < j:
                    return_full = False
                if d < k:
                    pop_related = True

            else:
                # sub element in property
                if d < j:
                    return_full = False
                if d < k:
                    pop_related = True

            for fld in self.nested_exclude:
                if fld in self.fields:
                    self.fields.pop(fld)

        # if the serialization base is not a single object but a GET all
        # request instead we want to drop certain fields from serialization
        # due to horrible performance - these fields are specified in
        # Meta.list_exclude
        if not a:
            for fld in getattr(self.__class__.Meta, "list_exclude", []):
                if fld in self.fields:
                    self.fields.pop(fld)

        # pop relted fields because of depth limit met
        if pop_related:
            for fld in getattr(self.__class__.Meta, "related_fields", []):
                if fld in self.fields:
                    self.fields.pop(fld)

        # return full object if depth limit allows, otherwise return id
        if return_full:
            if isinstance(data, list):
                return super().to_representation(data)
            else:
                result = super().to_representation(data)
                result["_grainy"] = data.grainy_namespace
                return result
        else:
            return data.id

    def sub_serializer(self, serializer, data, exclude=None):
        if not exclude:
            exclude = []
        s = serializer(read_only=True)
        s.parent = self
        s.nested_exclude = exclude
        return s.to_representation(data)

    def validate_create(self, validated_data):
        return

    def update(self, instance, validated_data):
        grainy_kwargs = {"id": instance.id}
        grainy_kwargs.update(**validated_data)

        namespace = self.Meta.model.Grainy.namespace_instance("*", **grainy_kwargs)
        request = self.context.get("request")

        if request and not check_permissions_from_request(request, namespace, "u"):
            raise PermissionDenied(
                f"User does not have write permissions to '{namespace}'"
            )

        return super().update(instance, validated_data)

    def create(self, validated_data):
        """
        Entities created via the API should go into the verification
        queue with status pending if they are in the QUEUE_ENABLED
        list.
        """
        if self.Meta.model in QUEUE_ENABLED:
            validated_data["status"] = "pending"
        else:
            validated_data["status"] = "ok"
        if "suggest" in validated_data:
            del validated_data["suggest"]

        self.validate_create(validated_data)
        grainy_kwargs = {"id": "*"}

        grainy_kwargs.update(**validated_data)

        request = self.context.get("request")

        if hasattr(self, "grainy_namespace_create"):
            namespace = self.grainy_namespace_create(**grainy_kwargs)
        else:
            namespace = self.Meta.model.Grainy.namespace_instance("*", **grainy_kwargs)

        if request and not check_permissions_from_request(request, namespace, "c"):
            raise PermissionDenied(
                f"User does not have write permissions to '{namespace}'"
            )

        return super().create(validated_data)

    def _unique_filter(self, fld, data):
        for _fld, slz_fld in list(self._declared_fields.items()):
            if fld == slz_fld.source:
                if type(slz_fld) == serializers.PrimaryKeyRelatedField:
                    return slz_fld.queryset.get(id=data[_fld])

    def run_validation(self, data=serializers.empty):

        """
        Custom validation handling.

        Will run the vanilla django-rest-framework validation but
        wrap it with logic to handle unique constraint errors to
        restore soft-deleted objects that are blocking a save on basis
        of a unique constraint violation.
        """

        try:
            return super().run_validation(data=data)
        except RestValidationError as exc:

            filters = {}
            for k, v in list(exc.detail.items()):
                v = v[0]

                # if code is not set on the error detail it's
                # useless to us

                if not hasattr(v, "code"):
                    continue

                # During `ix` creation `prefix` is passed to create
                # an `ixpfx` object alongside the ix, it's not part of ix
                # so ignore it (#718)

                if k == "prefix" and self.Meta.model == InternetExchange:
                    continue

                # when handling unique constraint database errors
                # we want to check if the offending object is
                # currently soft-deleted and can gracefully be
                # restored.

                if v.code == "unique" and k == "non_field_errors":

                    # unique-set errors - database blocked save
                    # because of a unique multi key constraint

                    # find out which fields caused the issues
                    # this is done by checking all serializer fields
                    # against the error message.
                    #
                    # If a field is contained in the error message
                    # it can be safely  assumed to be part of the
                    # unique set that caused the collision

                    columns = "|".join(self.Meta.fields)
                    m = re.findall(fr"\b({columns})\b", v)

                    # build django queryset filters we can use
                    # to retrieve the blocking object

                    for fld in m:
                        _value = data.get(fld, self._unique_filter(fld, data))
                        if _value is not None:
                            filters[fld] = _value

                elif v.code == "unique":

                    # unique single field error

                    # build django queryset filter we can use to
                    # retrieve the blocking object

                    filters[k] = data.get(k, self._unique_filter(k, data))

            request = self._context.get("request")

            # handle graceful restore of soft-deleted object
            # that is causing the unique constraint error
            #
            # if `filters` is set it means that we were able
            # to identify a soft-deleted object that we want
            # to restore
            #
            # At this point  `POST` (create) requests and
            # `PUT` (update) requests are supported
            #
            # POST will undelete the blocking entity and re-claim it
            # PUT will null the offending fields on the blocking entity

            if (
                filters
                and request
                and request.user
                and request.method in ["POST", "PUT"]
            ):

                if "fac_id" in filters:
                    filters["facility_id"] = filters["fac_id"]
                    del filters["fac_id"]
                if "net_id" in filters:
                    filters["network_id"] = filters["net_id"]
                    del filters["net_id"]

                try:
                    filters.update(status="deleted")
                    if (
                        self.Meta.model == NetworkIXLan
                        and "ipaddr4" in filters
                        and "ipaddr6" in filters
                    ):
                        # if unqiue constraint blocked on both ipaddr4 and ipaddr6 on netixlans
                        # we need to account for the fact that they might be on separate netixlans.
                        instance = self._handle_netixlan_reclaim(
                            filters["ipaddr4"], filters["ipaddr6"]
                        )
                    else:
                        instance = self.Meta.model.objects.get(**filters)
                except self.Meta.model.DoesNotExist:
                    raise exc
                except FieldError as exc:
                    raise exc

                if request.method == "POST":

                    if (
                        (
                            instance._meta.model == Network
                            and "name" in filters
                            and "asn" not in filters
                        )
                        or (instance._meta.model == Facility and "name" in filters)
                        or (
                            instance._meta.model == InternetExchange
                            and "name" in filters
                        )
                    ):
                        # issue #901 - if an entity is submitted where the name is currently
                        # held by a soft-deleted entity rename the soft-deleted
                        # network to free up the name and proceed with creation validation normally

                        instance.name = f"{instance.name} #{instance.id}"
                        instance.notes_private = (
                            "Name of deleted entity claimed by new entity"
                        )
                        instance.save()
                        return super().run_validation(data=data)

                    self.instance = instance

                    if type(instance) in QUEUE_ENABLED:
                        self._reapprove = True
                        self._undelete = False
                    else:
                        self._reapprove = False
                        self._undelete = True

                elif request.method == "PUT":
                    for field in filters.keys():
                        if field == "status":
                            continue
                        setattr(instance, field, None)

                    try:
                        # if field can't be nulled this will
                        # fail and raise the original error
                        instance.save()
                    except Exception:
                        raise exc

                rv = super().run_validation(data=data)
                return rv
            else:
                raise

    def _handle_netixlan_reclaim(self, ipaddr4, ipaddr6):

        """
        Handles logic of reclaiming ipaddresses from soft-deleted
        netixlans in case where ipv4 and ipv6 are on separate netixlan objects

        Will raise a django DoesNotExist error if either ipaddress does not
        exist on a deleted netixlan
        """

        netixlan_a = NetworkIXLan.objects.get(ipaddr4=ipaddr4, status="deleted")
        netixlan_b = NetworkIXLan.objects.get(ipaddr6=ipaddr6, status="deleted")
        instance = netixlan_a

        if netixlan_a != netixlan_b:
            netixlan_b.ipaddr6 = None
            netixlan_b.save()
        return instance

    def save(self, **kwargs):
        """
        Entities created via API that have status pending should
        attempt to store which user created the item in the
        verification queue instance.
        """
        instance = super().save(**kwargs)

        if instance.status == "deleted" and getattr(self, "_reapprove", False):
            instance.status = "pending"
            instance.save()

        elif instance.status == "deleted" and getattr(self, "_undelete", False):
            instance.status = "ok"
            instance.save()

        request = self._context["request"]

        if instance.status == "pending" and request:
            vq = VerificationQueueItem.objects.filter(
                content_type=ContentType.objects.get_for_model(type(instance)),
                object_id=instance.id,
            ).first()
            if vq:
                # This will save the user field if user credentials
                # or if a user api key are used
                user = get_user_from_request(request)
                org_key = get_org_key_from_request(request)
                if user:
                    vq.user = user
                    vq.save()

                # This will save the org api key if provided
                elif org_key:
                    vq.org_key = org_key
                    vq.save()

    def finalize_create(self, request):
        """This will be called on the end of POST request to this serializer."""

    def finalize_update(self, request):
        """This will be called on the end of PUT request to this serializer."""

    def finalize_delete(self, request):
        """This will be called on the end of DELETE request to this serializer."""


class RequestAwareListSerializer(serializers.ListSerializer):
    """
    A List serializer that has access to the originating
    request.

    Used as the list serializer class for all nested lists
    so time filters can be applied to the resultset if the _ctf param
    is set in the request.
    """

    @property
    def request(self):
        """
        Retrieve the request from the root serializer.
        """

        par = self
        while par:
            if "request" in par._context:
                return par._context["request"]
            par = par.parent
        return None

    def to_representation(self, data):
        return [self.child.to_representation(self.child.extract(item)) for item in data]


def nested(serializer, exclude=[], getter=None, through=None, **kwargs):
    """
    Use this function to create nested serializer fields. Making
    depth work otherwise while fetching related lists via handlref remains a mystery.
    """

    field_set = [fld for fld in serializer.Meta.fields if fld not in exclude]

    class NestedSerializer(serializer):
        class Meta(serializer.Meta):
            list_serializer_class = RequestAwareListSerializer
            fields = field_set
            orig_name = serializer.__name__

        def extract(self, item):
            if getter:
                return getattr(item, getter)
            return item

    NestedSerializer.__name__ = serializer.__name__
    NestedSerializer.Meta.through = through
    NestedSerializer.Meta.getter = getter

    return NestedSerializer(many=True, read_only=True, **kwargs)


class SpatialSearchMixin:

    """
    Mixin that enables spatial search for a model
    with address fields.

    At minimum, a model needs a country and city field, but
    address1, address2, zipcode and state are also considered
    if they exist.
    """

    @classmethod
    def prepare_spatial_search(cls, qset, filters, distance=50):

        # no distance or negative distance provided, bail

        if distance <= 0:
            return qset

        if "longitude" not in filters or "latitude" not in filters:

            # geo-coordinates have not been provided in the filter
            # so we can attempt to grab them for the provided
            # address filters

            # we require at least city and country to be defined
            # in the filters to create meaningful coordinates
            # and proceed with the distance query

            required_fields = ["country", "city"]
            errors = {}
            for field in required_fields:
                if not filters.get(field):
                    errors[field] = _("Required for distance filtering")

            # One or more of the required address fields was missing
            # raise validation errors
            if errors:
                raise serializers.ValidationError(errors)

            try:
                # convert address filters into lng and lat
                coords = GeoCoordinateCache.request_coordinates(**filters)
            except OSError:
                # google failure to convert address to coordinates
                # due ot technical error
                # return empty query set
                return qset.none()
            if coords:
                # coords were obtained, updated filters
                filters.update(**coords)
            else:
                # no coords found, return empty queryset
                return qset.none()

        # spatial distance calculation

        tbl = qset.model._meta.db_table

        gcd_formula = f"6371 * acos(least(greatest(cos(radians(%s)) * cos(radians({tbl}.`latitude`)) * cos(radians({tbl}.`longitude`) - radians(%s)) + sin(radians(%s)) * sin(radians({tbl}.`latitude`)), -1), 1))"
        distance_raw_sql = RawSQL(
            gcd_formula, (coords["latitude"], coords["longitude"], coords["latitude"])
        )
        qset = qset.annotate(distance=distance_raw_sql).order_by("distance")
        qset = qset.filter(distance__lte=distance)

        # we mark the query as spatial - note that this is not a django property
        # but an arbitrary property we are setting so we can determine whether
        # thq query is doing spatial filtering or not at a later point.
        qset.spatial = True

        return qset


# serializers get their own ref_tag in case we want to define different types
# that aren't one to one with models and serializer turns model into a tuple
# so always lookup the ref tag from the serializer (in fact, do we even need it
# on the model?


class FacilitySerializer(SpatialSearchMixin, GeocodeSerializerMixin, ModelSerializer):
    """
    Serializer for peeringdb_server.models.Facility

    Possible relationship queries:
      - net_id, handled by prepare_query
      - ix_id, handled by prepare_query
      - org_id, handled by serializer
      - org_name, hndled by prepare_query
    """

    org_id = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), source="org"
    )
    org_name = serializers.CharField(source="org.name", read_only=True)

    org = serializers.SerializerMethodField()

    suggest = serializers.BooleanField(required=False, write_only=True)

    website = serializers.URLField()
    address1 = serializers.CharField()
    city = serializers.CharField()
    zipcode = serializers.CharField(required=False, allow_blank=True, default="")

    tech_phone = serializers.CharField(required=False, allow_blank=True, default="")
    sales_phone = serializers.CharField(required=False, allow_blank=True, default="")

    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)

    available_voltage_services = serializers.MultipleChoiceField(
        choices=AVAILABLE_VOLTAGE, required=False, allow_null=True
    )

    region_continent = serializers.CharField(read_only=True)

    def validate_create(self, data):
        # we don't want users to be able to create facilities if the parent
        # organization status is pending or deleted
        if data.get("org") and data.get("org").status != "ok":
            raise ParentStatusException(data.get("org"), self.Meta.model.handleref.tag)
        return super().validate_create(data)

    class Meta:
        model = Facility

        fields = (
            [
                "id",
                "org_id",
                "org_name",
                "org",
                "name",
                "aka",
                "name_long",
                "website",
                "clli",
                "rencode",
                "npanxx",
                "notes",
                "net_count",
                "ix_count",
                "suggest",
                "sales_email",
                "sales_phone",
                "tech_email",
                "tech_phone",
                "available_voltage_services",
                "diverse_serving_substations",
                "property",
                "region_continent",
            ]
            + HandleRefSerializer.Meta.fields
            + AddressSerializer.Meta.fields
        )

        read_only_fields = ["rencode", "region_continent"]

        related_fields = ["org"]

        list_exclude = ["org"]

    @classmethod
    def prepare_query(cls, qset, **kwargs):

        qset = qset.select_related("org")
        filters = get_relation_filters(
            ["net_id", "net", "ix_id", "ix", "org_name", "ix_count", "net_count"],
            cls,
            **kwargs,
        )

        for field, e in list(filters.items()):
            for valid in ["net", "ix"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    qset = fn(qset=qset, field=field, **e)
                    break
            if field == "org_name":
                flt = {"org__name__%s" % (e["filt"] or "icontains"): e["value"]}
                qset = qset.filter(**flt)

            if field == "network_count":
                if e["filt"]:
                    flt = {"net_count__%s" % e["filt"]: e["value"]}
                else:
                    flt = {"net_count": e["value"]}
                qset = qset.filter(**flt)

        if "asn_overlap" in kwargs:
            asns = kwargs.get("asn_overlap", [""])[0].split(",")
            qset = cls.Meta.model.overlapping_asns(asns, qset=qset)
            filters.update({"asn_overlap": kwargs.get("asn_overlap")})

        if "org_present" in kwargs:
            org_list = kwargs.get("org_present")[0].split(",")
            fac_ids = []

            # relation through netfac
            fac_ids.extend(
                [
                    netfac.facility_id
                    for netfac in NetworkFacility.objects.filter(
                        network__org_id__in=org_list
                    )
                ]
            )

            # relation through ixfac
            fac_ids.extend(
                [
                    ixfac.facility_id
                    for ixfac in InternetExchangeFacility.objects.filter(
                        ix__org_id__in=org_list
                    )
                ]
            )

            qset = qset.filter(id__in=set(fac_ids))

            filters.update({"org_present": kwargs.get("org_present")[0]})

        if "org_not_present" in kwargs:

            org_list = kwargs.get("org_not_present")[0].split(",")
            fac_ids = []

            # relation through netfac
            fac_ids.extend(
                [
                    netfac.facility_id
                    for netfac in NetworkFacility.objects.filter(
                        network__org_id__in=org_list
                    )
                ]
            )

            # relation through ixfac
            fac_ids.extend(
                [
                    ixfac.facility_id
                    for ixfac in InternetExchangeFacility.objects.filter(
                        ix__org_id__in=org_list
                    )
                ]
            )

            qset = qset.exclude(id__in=set(fac_ids))

            filters.update({"org_not_present": kwargs.get("org_not_present")[0]})

        if "all_net" in kwargs:
            network_id_list = [
                int(net_id) for net_id in kwargs.get("all_net")[0].split(",")
            ]
            qset = cls.Meta.model.related_to_multiple_networks(
                value_list=network_id_list, qset=qset
            )
            filters.update({"all_net": kwargs.get("all_net")})

        if "not_net" in kwargs:
            networks = kwargs.get("not_net")[0].split(",")
            qset = cls.Meta.model.not_related_to_net(
                filt="in", value=networks, qset=qset
            )
            filters.update({"not_net": kwargs.get("not_net")})

        if "distance" in kwargs:
            qset = cls.prepare_spatial_search(
                qset, kwargs, single_url_param(kwargs, "distance", float)
            )

        return qset, filters

    def to_internal_value(self, data):
        # if `suggest` keyword is provided, hard-set the org to
        # whichever org is specified in `SUGGEST_ENTITY_ORG`
        #
        # this happens here so it is done before the validators run
        if "suggest" in data and (not self.instance or not self.instance.id):
            data["org_id"] = settings.SUGGEST_ENTITY_ORG

        return super().to_internal_value(data)

    def to_representation(self, instance):

        representation = super().to_representation(instance)

        if not isinstance(representation, dict):
            return representation

        # django-rest-framework multiplechoicefield maintains
        # a set of values and thus looses sorting.
        #
        # we always want to return values sorted by choice
        # definition order
        if instance.available_voltage_services:
            avs = []
            for choice, label in AVAILABLE_VOLTAGE:
                if choice in instance.available_voltage_services:
                    avs.append(choice)

            representation["available_voltage_services"] = avs

        return representation

    def get_org(self, inst):
        return self.sub_serializer(OrganizationSerializer, inst.org)

    def validate(self, data):
        try:
            data["tech_phone"] = validate_phonenumber(
                data["tech_phone"], data["country"]
            )
        except ValidationError as exc:
            raise serializers.ValidationError({"tech_phone": exc.message})

        try:
            data["sales_phone"] = validate_phonenumber(
                data["sales_phone"], data["country"]
            )
        except ValidationError as exc:
            raise serializers.ValidationError({"sales_phone": exc.message})

        try:
            data["zipcode"] = validate_zipcode(data["zipcode"], data["country"])
        except ValidationError as exc:
            raise serializers.ValidationError({"zipcode": exc.message})

        return data


class InternetExchangeFacilitySerializer(ModelSerializer):
    """
    Serializer for peeringdb_server.models.InternetExchangeFacility

    Possible relationship queries:
      - fac_id, handled by serializer
      - ix_id, handled by serializer
    """

    ix_id = serializers.PrimaryKeyRelatedField(
        queryset=InternetExchange.objects.all(), source="ix"
    )
    fac_id = serializers.PrimaryKeyRelatedField(
        queryset=Facility.objects.all(), source="facility"
    )

    ix = serializers.SerializerMethodField()
    fac = serializers.SerializerMethodField()

    name = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()

    def validate_create(self, data):
        # we don't want users to be able to create ixfacs if the parent
        # ix or fac status is pending or deleted
        if data.get("ix") and data.get("ix").status != "ok":
            raise ParentStatusException(data.get("ix"), self.Meta.model.handleref.tag)
        if data.get("fac") and data.get("fac").status != "ok":
            raise ParentStatusException(data.get("fac"), self.Meta.model.handleref.tag)
        return super().validate_create(data)

    class Meta:
        model = InternetExchangeFacility
        fields = [
            "id",
            "name",
            "city",
            "country",
            "ix_id",
            "ix",
            "fac_id",
            "fac",
        ] + HandleRefSerializer.Meta.fields

        list_exclude = ["ix", "fac"]

        related_fields = ["ix", "fac"]

        validators = [
            validators.UniqueTogetherValidator(
                InternetExchangeFacility.objects.all(), ["ix_id", "fac_id"]
            )
        ]

        _ref_tag = model.handleref.tag

    @classmethod
    def prepare_query(cls, qset, **kwargs):
        qset = qset.select_related("ix", "ix__org", "facility")

        filters = get_relation_filters(["name", "country", "city"], cls, **kwargs)
        for field, e in list(filters.items()):
            for valid in ["name", "country", "city"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    field = f"facility__{valid}"
                    qset = fn(qset=qset, field=field, **e)
                    break

        return qset, filters

    def get_ix(self, inst):
        return self.sub_serializer(InternetExchangeSerializer, inst.ix)

    def get_fac(self, inst):
        return self.sub_serializer(FacilitySerializer, inst.facility)

    def get_name(self, inst):
        return inst.facility.name

    def get_country(self, inst):
        return inst.facility.country

    def get_city(self, inst):
        return inst.facility.city


class NetworkContactSerializer(ModelSerializer):
    """
    Serializer for peeringdb_server.models.NetworkContact

    Possible relationship queries:
      - net_id, handled by serializer
    """

    net_id = serializers.PrimaryKeyRelatedField(
        queryset=Network.objects.all(), source="network"
    )
    net = serializers.SerializerMethodField()

    class Meta:
        model = NetworkContact
        depth = 0
        fields = [
            "id",
            "net_id",
            "net",
            "role",
            "visible",
            "name",
            "phone",
            "email",
            "url",
        ] + HandleRefSerializer.Meta.fields

        related_fields = ["net"]

        list_exclude = ["net"]

        _ref_tag = model.handleref.tag

    @classmethod
    def prepare_query(cls, qset, **kwargs):
        qset = qset.select_related("network", "network__org")
        return qset, {}

    def validate_create(self, data):
        # we don't want users to be able to create contacts if the parent
        # network status is pending or deleted
        if data.get("network") and data.get("network").status != "ok":
            raise ParentStatusException(
                data.get("network"), self.Meta.model.handleref.tag
            )
        return super().validate_create(data)

    def grainy_namespace_create(self, **kwargs):
        return kwargs["network"].grainy_namespace

    def get_net(self, inst):
        return self.sub_serializer(NetworkSerializer, inst.network)

    def validate_phone(self, value):
        return validate_phonenumber(value)

    def validate_visible(self, value):
        return validate_poc_visible(value)

    def to_representation(self, data):
        # When a network contact is marked as deleted we
        # want to return blank values for any sensitive
        # fields (#569)

        representation = super().to_representation(data)

        if (
            isinstance(representation, dict)
            and representation.get("status") == "deleted"
        ):
            for field in ["name", "phone", "email", "url"]:
                representation[field] = ""

        return representation


class NetworkIXLanSerializer(ModelSerializer):
    """
    Serializer for peeringdb_server.models.NetworkIXLan

    Possible relationship queries:
      - net_id, handled by serializer
      - ixlan_id, handled by serializer
      - ix_id, handled by prepare_query
    """

    net_id = serializers.PrimaryKeyRelatedField(
        queryset=Network.objects.all(), source="network"
    )
    ixlan_id = serializers.PrimaryKeyRelatedField(
        queryset=IXLan.objects.all(), source="ixlan"
    )

    net = serializers.SerializerMethodField()
    ixlan = serializers.SerializerMethodField()

    name = serializers.SerializerMethodField()
    ix_id = serializers.SerializerMethodField()

    ipaddr4 = IPAddressField(version=4, allow_blank=True)
    ipaddr6 = IPAddressField(version=6, allow_blank=True)

    def validate_create(self, data):
        # we don't want users to be able to create netixlans if the parent
        # network or ixlan is pending or deleted
        if data.get("network") and data.get("network").status != "ok":
            raise ParentStatusException(
                data.get("network"), self.Meta.model.handleref.tag
            )
        if data.get("ixlan") and data.get("ixlan").status != "ok":
            raise ParentStatusException(
                data.get("ixlan"), self.Meta.model.handleref.tag
            )
        return super().validate_create(data)

    class Meta:

        validators = [
            SoftRequiredValidator(
                fields=("ipaddr4", "ipaddr6"), message="Input required for IPv4 or IPv6"
            ),
            UniqueFieldValidator(
                fields=("ipaddr4", "ipaddr6"),
                message="IP already exists",
                check_deleted=True,
            ),
        ]

        model = NetworkIXLan
        depth = 0
        fields = [
            "id",
            "net_id",
            "net",
            "ix_id",
            "name",
            "ixlan_id",
            "ixlan",
            "notes",
            "speed",
            "asn",
            "ipaddr4",
            "ipaddr6",
            "is_rs_peer",
            "operational",
        ] + HandleRefSerializer.Meta.fields

        related_fields = ["net", "ixlan"]

        list_exclude = ["net", "ixlan"]

        _ref_tag = model.handleref.tag

    @classmethod
    def prepare_query(cls, qset, **kwargs):
        """
        Allows filtering by indirect relationships.

        Currently supports: ix_id
        """

        qset = qset.select_related("network", "network__org")

        filters = get_relation_filters(["ix_id", "ix", "name"], cls, **kwargs)
        for field, e in list(filters.items()):
            for valid in ["ix", "name"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    if field == "name":
                        field = "ix__name"
                    qset = fn(qset=qset, field=field, **e)
                    break

        qset = qset.select_related("network", "ixlan", "ixlan__ix")

        return qset, filters

    def get_net(self, inst):
        return self.sub_serializer(NetworkSerializer, inst.network)

    def get_ixlan(self, inst):
        return self.sub_serializer(IXLanSerializer, inst.ixlan)

    def get_name(self, inst):
        ixlan_name = inst.ixlan.name
        if ixlan_name:
            return f"{inst.ix_name}: {ixlan_name}"
        return inst.ix_name

    def get_ix_id(self, inst):
        return inst.ix_id

    def run_validation(self, data=serializers.empty):
        # `asn` will eventually be dropped from the schema
        # for now make sure it is always a match to the related
        # network

        if data.get("net_id"):
            try:
                net = Network.objects.get(id=data.get("net_id"))
                data["asn"] = net.asn
            except Exception:
                pass
        return super().run_validation(data=data)

    def _validate_network_contact(self, data):
        """
        Per github ticket #826, a Netixlan is only allowed to be added
        if there is a network contact that the AC can contact to resolve issues.
        """
        network = data["network"]

        poc = (
            network.poc_set_active.filter(
                role__in=["Technical", "NOC", "Policy"], visible__in=["Users", "Public"]
            )
            .exclude(email="")
            .count()
        )

        if poc == 0:
            raise serializers.ValidationError(
                _(
                    "Network must have a Technical, NOC, or Policy point of contact "
                    "with valid email before adding exchange point."
                )
            )

    def validate(self, data):

        self._validate_network_contact(data)

        netixlan = NetworkIXLan(**data)
        try:
            netixlan.validate_ipaddr4()
        except ValidationError as exc:
            raise serializers.ValidationError({"ipaddr4": exc.message})

        try:
            netixlan.validate_ipaddr6()
        except ValidationError as exc:
            raise serializers.ValidationError({"ipaddr6": exc.message})

        try:
            netixlan.validate_speed()
        except ValidationError as exc:
            raise serializers.ValidationError({"speed": exc.message})

        # when validating an existing netixlan that has a mismatching
        # asn value raise a validation error stating that it needs
        # to be moved
        #
        # this is to catch and force correction of instances where they
        # could not be migrated automatically during rollout of #168
        # because the targeted asn did not exist in peeringdb

        if self.instance and self.instance.asn != self.instance.network.asn:
            raise serializers.ValidationError(
                {
                    "asn": _(
                        "This entity was created for the ASN {} - please remove it from this network and recreate it under the correct network"
                    ).format(self.instance.asn)
                }
            )

        return data


class NetworkFacilitySerializer(ModelSerializer):
    """
    Serializer for peeringdb_server.models.NetworkFacility

    Possible relationship queries:
      - fac_id, handled by serializer
      - net_id, handled by seralizers
    """

    #  facilities = serializers.PrimaryKeyRelatedField(queryset='fac_set', many=True)

    fac_id = serializers.PrimaryKeyRelatedField(
        queryset=Facility.objects.all(), source="facility"
    )
    net_id = serializers.PrimaryKeyRelatedField(
        queryset=Network.objects.all(), source="network"
    )

    fac = serializers.SerializerMethodField()
    net = serializers.SerializerMethodField()

    name = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()

    class Meta:

        model = NetworkFacility
        depth = 0
        fields = [
            "id",
            "name",
            "city",
            "country",
            "net_id",
            "net",
            "fac_id",
            "fac",
            "local_asn",
        ] + HandleRefSerializer.Meta.fields
        _ref_tag = model.handleref.tag

        related_fields = ["net", "fac"]

        list_exclude = ["net", "fac"]

        validators = [
            validators.UniqueTogetherValidator(
                NetworkFacility.objects.all(), ["net_id", "fac_id", "local_asn"]
            )
        ]

    @classmethod
    def prepare_query(cls, qset, **kwargs):

        qset = qset.select_related("network", "network__org")

        filters = get_relation_filters(["name", "country", "city"], cls, **kwargs)
        for field, e in list(filters.items()):
            for valid in ["name", "country", "city"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    field = f"facility__{valid}"
                    qset = fn(qset=qset, field=field, **e)
                    break

        return qset.select_related("network", "facility"), filters

    def validate_create(self, data):
        # we don't want users to be able to create netfac links if the parent
        # network or facility status is pending or deleted
        if data.get("network") and data.get("network").status != "ok":
            raise ParentStatusException(
                data.get("network"), self.Meta.model.handleref.tag
            )
        if data.get("facility") and data.get("facility").status != "ok":
            raise ParentStatusException(
                data.get("facility"), self.Meta.model.handleref.tag
            )
        return super().validate_create(data)

    def get_net(self, inst):
        return self.sub_serializer(NetworkSerializer, inst.network)

    def get_fac(self, inst):
        return self.sub_serializer(FacilitySerializer, inst.facility)

    def get_name(self, inst):
        return inst.facility.name

    def get_country(self, inst):
        return inst.facility.country

    def get_city(self, inst):
        return inst.facility.city

    def run_validation(self, data=serializers.empty):
        # `local_asn` will eventually be dropped from the schema
        # for now make sure it is always a match to the related
        # network

        if data.get("net_id"):
            try:
                net = Network.objects.get(id=data.get("net_id"))
                data["local_asn"] = net.asn
            except Exception:
                pass
        return super().run_validation(data=data)

    def validate(self, data):

        # when validating an existing netfac that has a mismatching
        # local_asn value raise a validation error stating that it needs
        # to be moved
        #
        # this is to catch and force correction of instances where they
        # could not be migrated automatically during rollout of #168
        # because the targeted local_asn did not exist in peeringdb

        if self.instance and self.instance.local_asn != self.instance.network.asn:
            raise serializers.ValidationError(
                {
                    "local_asn": _(
                        "This entity was created for the ASN {} - please remove it from this network and recreate it under the correct network"
                    ).format(self.instance.local_asn)
                }
            )

        return data


class NetworkSerializer(ModelSerializer):
    # TODO override these so they dn't repeat network ID, or add a kwarg to
    # disable fields
    """
    Serializer for peeringdb_server.models.Network

    Possible realtionship queries:
      - org_id, handled by serializer
      - ix_id, handled by prepare_query
      - ixlan_id, handled by prepare_query
      - netfac_id, handled by prepare_query
      - fac_id, handled by prepare_query
    """
    netfac_set = nested(
        NetworkFacilitySerializer,
        exclude=["net_id", "net"],
        source="netfac_set_active_prefetched",
    )

    poc_set = nested(
        NetworkContactSerializer,
        exclude=["net_id", "net"],
        source="poc_set_active_prefetched",
    )

    netixlan_set = nested(
        NetworkIXLanSerializer,
        exclude=["net_id", "net"],
        source="netixlan_set_active_prefetched",
    )

    org_id = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), source="org"
    )
    org = serializers.SerializerMethodField()

    route_server = serializers.CharField(
        required=False,
        allow_blank=True,
        validators=[URLValidator(schemes=["http", "https", "telnet", "ssh"])],
    )

    looking_glass = serializers.CharField(
        required=False,
        allow_blank=True,
        validators=[URLValidator(schemes=["http", "https", "telnet", "ssh"])],
    )

    info_prefixes4 = SaneIntegerField(
        allow_null=False, required=False, validators=[validate_info_prefixes4]
    )
    info_prefixes6 = SaneIntegerField(
        allow_null=False, required=False, validators=[validate_info_prefixes6]
    )

    suggest = serializers.BooleanField(required=False, write_only=True)
    validators = [
        AsnRdapValidator(),
    ]

    # irr_as_set = serializers.CharField(validators=[validate_irr_as_set])

    class Meta:
        model = Network
        depth = 1
        fields = [
            "id",
            "org_id",
            "org",
            "name",
            "aka",
            "name_long",
            "website",
            "asn",
            "looking_glass",
            "route_server",
            "irr_as_set",
            "info_type",
            "info_prefixes4",
            "info_prefixes6",
            "info_traffic",
            "info_ratio",
            "info_scope",
            "info_unicast",
            "info_multicast",
            "info_ipv6",
            "info_never_via_route_servers",
            "ix_count",
            "fac_count",
            "notes",
            "netixlan_updated",
            "netfac_updated",
            "poc_updated",
            "policy_url",
            "policy_general",
            "policy_locations",
            "policy_ratio",
            "policy_contracts",
            "netfac_set",
            "netixlan_set",
            "poc_set",
            "allow_ixp_update",
            "suggest",
        ] + HandleRefSerializer.Meta.fields
        default_fields = ["id", "name", "asn"]
        related_fields = [
            "org",
            "netfac_set",
            "netixlan_set",
            "poc_set",
        ]
        read_only_fields = [
            "netixlan_updated",
            "netfac_updated",
            "poc_updated",
        ]
        list_exclude = ["org"]

        _ref_tag = model.handleref.tag

    @classmethod
    def prepare_query(cls, qset, **kwargs):
        """
        Allows filtering by indirect relationships.

        Currently supports: ixlan_id, ix_id, netixlan_id, netfac_id, fac_id
        """

        qset = qset.select_related("org")

        filters = get_relation_filters(
            [
                "ixlan_id",
                "ixlan",
                "ix_id",
                "ix",
                "netixlan_id",
                "netixlan",
                "netfac_id",
                "netfac",
                "fac",
                "fac_id",
                "fac_count",
                "ix_count",
            ],
            cls,
            **kwargs,
        )

        for field, e in list(filters.items()):
            for valid in ["ix", "ixlan", "netixlan", "netfac", "fac"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    qset = fn(qset=qset, field=field, **e)
                    break

            if field == "facility_count":
                if e["filt"]:
                    flt = {"fac_count__%s" % e["filt"]: e["value"]}
                else:
                    flt = {"fac_count": e["value"]}
                qset = qset.filter(**flt)

        # networks that are NOT present at exchange
        if "not_ix" in kwargs:
            not_ix = kwargs.get("not_ix")[0]
            qset = cls.Meta.model.not_related_to_ix(value=not_ix, qset=qset)
            filters.update({"not_ix": not_ix})

        # networks that are NOT present at facility
        if "not_fac" in kwargs:
            not_fac = kwargs.get("not_fac")[0]
            qset = cls.Meta.model.not_related_to_fac(value=not_fac, qset=qset)
            filters.update({"not_fac": not_fac})

        return qset, filters

    @classmethod
    def is_unique_query(cls, request):
        if "asn" in request.GET:
            return True
        return ModelSerializer.is_unique_query(request)

    def to_internal_value(self, data):
        # if `suggest` keyword is provided, hard-set the org to
        # whichever org is specified in `SUGGEST_ENTITY_ORG`
        #
        # this happens here so it is done before the validators run
        if "suggest" in data and (not self.instance or not self.instance.id):
            data["org_id"] = settings.SUGGEST_ENTITY_ORG

        # if an asn exists already but is currently deleted, fail
        # with a specific error message indicating it (#288)

        if Network.objects.filter(asn=data.get("asn"), status="deleted").exists():
            errmsg = _("Network has been deleted. Please contact {}").format(
                settings.DEFAULT_FROM_EMAIL
            )
            raise RestValidationError({"asn": errmsg})

        return super().to_internal_value(data)

    def validate_create(self, data):
        # we don't want users to be able to create networks if the parent
        # organization status is pending or deleted
        if data.get("org") and data.get("org").status != "ok":
            raise ParentStatusException(data.get("org"), self.Meta.model.handleref.tag)
        return super().validate_create(data)

    def get_org(self, inst):
        return self.sub_serializer(OrganizationSerializer, inst.org)

    def create(self, validated_data):
        request = self._context.get("request")
        request.user

        asn = validated_data.get("asn")
        website = validated_data.get("website")

        # Check if website field is not empty
        if not website:
            raise RestValidationError({"website": _("This field may not be blank.")})

        if "suggest" in validated_data:
            del validated_data["suggest"]

        if validated_data["org"].id == settings.SUGGEST_ENTITY_ORG:
            rdap = None
        else:
            # rdap result may already be avalaible from
            # validation - no need to requery in such
            # cases
            rdap = getattr(request, "rdap_result", None)

            # otherwise setup rdap lookup
            if not rdap:
                try:
                    rdap = RdapLookup().get_asn(asn)
                except RdapInvalidRange as exc:
                    raise RestValidationError(
                        {self.field: rdap_pretty_error_message(exc)}
                    )
                except RdapException as exc:
                    raise RestValidationError(
                        {self.field: rdap_pretty_error_message(exc)}
                    )

        # add network to existing org
        if rdap and validate_rdap_user_or_key(request, rdap):

            # user email exists in RiR data, skip verification queue
            validated_data["status"] = "ok"
            net = super().create(validated_data)
            ticket_queue_asnauto_skipvq(request, validated_data["org"], net, rdap)
            return net

        elif self.Meta.model in QUEUE_ENABLED:
            # user email does NOT exist in RiR data, put into verification
            # queue
            validated_data["status"] = "pending"
        else:
            # verification queue is disabled regardless
            validated_data["status"] = "ok"

        return super().create(validated_data)

    def update(self, instance, validated_data):
        if validated_data.get("asn") != instance.asn:
            raise serializers.ValidationError(
                {
                    "asn": _("ASN cannot be changed."),
                }
            )
        return super().update(instance, validated_data)

    def finalize_create(self, request):
        rdap_error = getattr(request, "rdap_error", None)

        if rdap_error:
            ticket_queue_rdap_error(request, *rdap_error)

    def validate_irr_as_set(self, value):
        if value:
            return validate_irr_as_set(value)
        else:
            return value


# Create an Network serializer with no fields
class ASSetSerializer(NetworkSerializer):
    class Meta:
        model = Network
        fields = []


class IXLanPrefixSerializer(ModelSerializer):
    """
    Serializer for peeringdb_server.models.IXLanPrefix

    Possible relationship queries:
      - ixlan_id, handled by serializer
      - ix_id, handled by prepare_query
    """

    ixlan_id = serializers.PrimaryKeyRelatedField(
        queryset=IXLan.objects.all(), source="ixlan"
    )

    ixlan = serializers.SerializerMethodField()

    prefix = IPNetworkField(
        validators=[
            validators.UniqueValidator(queryset=IXLanPrefix.objects.all()),
            validate_address_space,
            validate_prefix_overlap,
        ]
    )
    in_dfz = serializers.SerializerMethodField(read_only=False)

    class Meta:
        model = IXLanPrefix
        fields = [
            "id",
            "ixlan",
            "ixlan_id",
            "protocol",
            "prefix",
            "in_dfz",
        ] + HandleRefSerializer.Meta.fields

        related_fields = ["ixlan"]

        list_exclude = ["ixlan"]

    @staticmethod
    def get_in_dfz(obj):
        return True

    @classmethod
    def prepare_query(cls, qset, **kwargs):

        qset = qset.select_related("ixlan", "ixlan__ix", "ixlan__ix__org")

        filters = get_relation_filters(["ix_id", "ix", "whereis"], cls, **kwargs)
        for field, e in list(filters.items()):
            for valid in ["ix"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    qset = fn(qset=qset, field=field, **e)
                    break

            if field == "whereis":
                qset = cls.Meta.model.whereis_ip(e["value"], qset=qset)

        return qset.select_related("ixlan", "ixlan__ix"), filters

    def validate_create(self, data):
        # we don't want users to be able to create prefixes if the parent
        # ixlan status is pending or deleted
        if data.get("ixlan") and data.get("ixlan").status != "ok":
            raise ParentStatusException(
                data.get("ixlan"), self.Meta.model.handleref.tag
            )
        return super().validate_create(data)

    def get_ixlan(self, inst):
        return self.sub_serializer(IXLanSerializer, inst.ixlan)

    def validate(self, data):

        # validate prefix against selected protocol
        #
        # Note: While the IPNetworkField already has this validator set on it
        # there is no good way to set the field's version from the protocol
        # specified in the rest data at this point, so we instead opt to validate
        # it again here.
        try:
            if data["protocol"].lower() == "ipv4":
                ipaddress.IPv4Network(data["prefix"])
            elif data["protocol"].lower() == "ipv6":
                ipaddress.IPv6Network(data["prefix"])
        except ipaddress.AddressValueError:
            raise serializers.ValidationError(
                "Prefix address invalid, needs to be valid according to the selected protocol"
            )
        except ipaddress.NetmaskValueError:
            raise serializers.ValidationError(
                "Prefix netmask invalid, needs to be valid according to the selected protocol"
            )

        # The implementation of #761 has deprecated the in_dfz
        # property as a writeable setting, if someone tries
        # to actively set it to `False` let them know it is no
        # longer supported

        if self.initial_data.get("in_dfz", True) is False:
            raise serializers.ValidationError(
                _(
                    "The `in_dfz` property has been deprecated "
                    "and setting it to `False` is no "
                    "longer supported"
                )
            )

        if self.instance:
            prefix = data["prefix"]
            if prefix != self.instance.prefix and not self.instance.deletable:
                raise serializers.ValidationError(
                    {"prefix": self.instance.not_deletable_reason}
                )
        return data


class IXLanSerializer(ModelSerializer):
    """
    Serializer for peeringdb_server.models.IXLan

    Possible relationship queries:
      - ix_id, handled by serializer
    """

    dot1q_support = serializers.SerializerMethodField()

    ix_id = serializers.PrimaryKeyRelatedField(
        queryset=InternetExchange.objects.all(), source="ix"
    )

    ix = serializers.SerializerMethodField()

    net_set = nested(
        NetworkSerializer,
        source="netixlan_set_active_prefetched",
        through="netixlan_set",
        getter="network",
    )
    ixpfx_set = nested(
        IXLanPrefixSerializer,
        exclude=["ixlan_id", "ixlan"],
        source="ixpfx_set_active_prefetched",
    )

    def validate_create(self, data):
        # we don't want users to be able to create ixlans if the parent
        # ix status is pending or deleted
        if data.get("ix") and data.get("ix").status != "ok":
            raise ParentStatusException(data.get("ix"), self.Meta.model.handleref.tag)
        return super().validate_create(data)

    class Meta:
        model = IXLan
        fields = [
            "id",
            "ix_id",
            "ix",
            "name",
            "descr",
            "mtu",
            "dot1q_support",
            "rs_asn",
            "arp_sponge",
            "net_set",
            "ixpfx_set",
            "ixf_ixp_member_list_url",
            "ixf_ixp_member_list_url_visible",
            "ixf_ixp_import_enabled",
        ] + HandleRefSerializer.Meta.fields
        related_fields = ["ix", "net_set", "ixpfx_set"]

        list_exclude = ["ix"]

        extra_kwargs = {
            "ixf_ixp_import_enabled": {"write_only": True},
        }

        _ref_tag = model.handleref.tag

    @classmethod
    def prepare_query(cls, qset, **kwargs):
        return qset.select_related("ix", "ix__org"), {}

    def get_ix(self, inst):
        return self.sub_serializer(InternetExchangeSerializer, inst.ix)

    def get_dot1q_support(self, inst):
        # as per #903 this should always return false as the field
        # is now deprecated
        return False

    def validate(self, data):
        # Per issue 846
        if data["ixf_ixp_member_list_url"] == "" and data["ixf_ixp_import_enabled"]:
            raise ValidationError(
                _(
                    "Cannot enable IX-F import without specifying the IX-F member list url"
                )
            )
        return data


class InternetExchangeSerializer(ModelSerializer):
    """
    Serializer for peeringdb_server.models.InternetExchange

    Possible relationship queries:
      - org_id, handled by serializer
      - fac_id, handled by prepare_query
      - net_id, handled by prepare_query
      - ixfac_id, handled by prepare_query
      - ixlan_id, handled by prepare_query
    """

    org_id = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), source="org"
    )

    org = serializers.SerializerMethodField()

    ixlan_set = nested(
        IXLanSerializer, exclude=["ix_id", "ix"], source="ixlan_set_active_prefetched"
    )
    fac_set = nested(
        FacilitySerializer,
        source="ixfac_set_active_prefetched",
        through="ixfac_set",
        getter="facility",
    )

    # suggest = serializers.BooleanField(required=False, write_only=True)

    ixf_net_count = serializers.IntegerField(read_only=True)
    ixf_last_import = serializers.DateTimeField(read_only=True)

    website = serializers.URLField()
    tech_email = serializers.EmailField(required=True)

    tech_phone = serializers.CharField(required=False, allow_blank=True, default="")
    policy_phone = serializers.CharField(required=False, allow_blank=True, default="")

    sales_phone = serializers.CharField(required=False, allow_blank=True, default="")
    sales_email = serializers.CharField(required=False, allow_blank=True, default="")

    # For the creation of the initial prefix during exchange
    # creation. It will be a required field during `POST` requests
    # but will be ignored during `PUT` so we cannot just do
    # required=True here
    prefix = IPNetworkField(
        validators=[
            validators.UniqueValidator(
                queryset=IXLanPrefix.objects.filter(status__in=["ok", "pending"])
            ),
            validate_address_space,
            validate_prefix_overlap,
        ],
        required=False,
        write_only=True,
    )

    proto_unicast = serializers.SerializerMethodField()
    proto_ipv6 = serializers.SerializerMethodField()

    validators = [
        RequiredForMethodValidator("prefix", ["POST"]),
        SoftRequiredValidator(
            ["policy_email", "tech_email"],
            message=_("Specify at least one email address"),
        ),
    ]

    class Meta:
        model = InternetExchange
        fields = [
            "id",
            "org_id",
            "org",
            "name",
            "aka",
            "name_long",
            "city",
            "country",
            "region_continent",
            "media",
            "notes",
            "proto_unicast",
            "proto_multicast",
            "proto_ipv6",
            "website",
            "url_stats",
            "tech_email",
            "tech_phone",
            "policy_email",
            "policy_phone",
            "sales_phone",
            "sales_email",
            "fac_set",
            "ixlan_set",
            # "suggest",
            "prefix",
            "net_count",
            "fac_count",
            "ixf_net_count",
            "ixf_last_import",
            "ixf_import_request",
            "ixf_import_request_status",
            "service_level",
            "terms",
        ] + HandleRefSerializer.Meta.fields
        _ref_tag = model.handleref.tag
        related_fields = ["org", "fac_set", "ixlan_set"]
        list_exclude = ["org"]

        read_only_fields = ["proto_multicast"]

    @classmethod
    def prepare_query(cls, qset, **kwargs):

        qset = qset.select_related("org")

        filters = get_relation_filters(
            [
                "ixlan_id",
                "ixlan",
                "ixfac_id",
                "ixfac",
                "fac_id",
                "fac",
                "net_id",
                "net",
                "net_count",
                "fac_count",
                "capacity",
            ],
            cls,
            **kwargs,
        )

        for field, e in list(filters.items()):

            for valid in ["ixlan", "ixfac", "fac", "net"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    qset = fn(qset=qset, field=field, **e)
                    break

            if field == "network_count":
                if e["filt"]:
                    flt = {"net_count__%s" % e["filt"]: e["value"]}
                else:
                    flt = {"net_count": e["value"]}
                qset = qset.filter(**flt)

            if field == "facility_count":
                if e["filt"]:
                    flt = {"fac_count__%s" % e["filt"]: e["value"]}
                else:
                    flt = {"fac_count": e["value"]}
                qset = qset.filter(**flt)

            if field == "capacity":
                qset = cls.Meta.model.filter_capacity(qset=qset, **e)

        if "ipblock" in kwargs:
            qset = cls.Meta.model.related_to_ipblock(
                kwargs.get("ipblock", [""])[0], qset=qset
            )
            filters.update({"ipblock": kwargs.get("ipblock")})

        if "asn_overlap" in kwargs:

            asns = kwargs.get("asn_overlap", [""])[0].split(",")
            qset = cls.Meta.model.overlapping_asns(asns, qset=qset)
            filters.update({"asn_overlap": kwargs.get("asn_overlap")})

        if "all_net" in kwargs:
            network_id_list = [
                int(net_id) for net_id in kwargs.get("all_net")[0].split(",")
            ]
            qset = cls.Meta.model.related_to_multiple_networks(
                value_list=network_id_list, qset=qset
            )
            filters.update({"all_net": kwargs.get("all_net")})

        if "not_net" in kwargs:
            networks = kwargs.get("not_net")[0].split(",")
            qset = cls.Meta.model.not_related_to_net(
                filt="in", value=networks, qset=qset
            )
            filters.update({"not_net": kwargs.get("not_net")})

        if "org_present" in kwargs:
            org_list = kwargs.get("org_present")[0].split(",")
            ix_ids = []

            # relation through netixlan
            ix_ids.extend(
                [
                    netixlan.ixlan_id
                    for netixlan in NetworkIXLan.objects.filter(
                        network__org_id__in=org_list
                    )
                ]
            )

            # relation through ixfac
            ix_ids.extend(
                [
                    ixfac.ix_id
                    for ixfac in InternetExchangeFacility.objects.filter(
                        facility__org_id__in=org_list
                    )
                ]
            )

            qset = qset.filter(id__in=set(ix_ids))

            filters.update({"org_present": kwargs.get("org_present")[0]})

        if "org_not_present" in kwargs:

            org_list = kwargs.get("org_not_present")[0].split(",")
            ix_ids = []

            # relation through netixlan
            ix_ids.extend(
                [
                    netixlan.ixlan_id
                    for netixlan in NetworkIXLan.objects.filter(
                        network__org_id__in=org_list
                    )
                ]
            )

            # relation through ixfac
            ix_ids.extend(
                [
                    ixfac.ix_id
                    for ixfac in InternetExchangeFacility.objects.filter(
                        facility__org_id__in=org_list
                    )
                ]
            )

            qset = qset.exclude(id__in=set(ix_ids))

            filters.update({"org_not_present": kwargs.get("org_not_present")[0]})

        return qset, filters

    def validate_create(self, data):
        # we don't want users to be able to create internet exchanges if the parent
        # organization status is pending or deleted
        if data.get("org") and data.get("org").status != "ok":
            raise ParentStatusException(data.get("org"), self.Meta.model.handleref.tag)

        # we don't want users to be able to create an internet exchange with an
        # org that is the "suggested entity org"
        if data.get("org") and (data.get("org").id == settings.SUGGEST_ENTITY_ORG):
            raise serializers.ValidationError(
                {
                    "org": _(
                        "User cannot create an internet exchange with"
                        "its org set as the SUGGEST_ENTITY organization"
                    )
                }
            )
        return super().validate_create(data)

    def to_representation(self, data):
        # When an ix is created we want to add the ixlan_id and ixpfx_id
        # that were created to the representation (see #609)

        representation = super().to_representation(data)
        request = self.context.get("request")
        if request and request.method == "POST" and self.instance:
            ixlan = self.instance.ixlan
            ixpfx = ixlan.ixpfx_set.first()
            representation.update(ixlan_id=ixlan.id, ixpfx_id=ixpfx.id)
        return representation

    def create(self, validated_data):
        # when creating an exchange via the API it is required
        # that an initial prefix is provided and an ixlan and ixlanprefix
        # object is created and connected to the ix

        # the prefix that was provided, we pop it off the validated
        # data because we don't need it during the ix creation
        prefix = validated_data.pop("prefix")

        website = validated_data.get("website")

        # Check if website field is not empty
        if not website:
            raise RestValidationError({"website": _("This field may not be blank.")})

        # create ix
        r = super().create(validated_data)

        ixlan = r.ixlan

        # create ixlan
        # if False:# not ixlan:
        #    ixlan = IXLan(ix=r, status="pending")
        #    ixlan.clean()
        #    ixlan.save()

        # see if prefix already exists in a deleted state
        ixpfx = IXLanPrefix.objects.filter(prefix=prefix, status="deleted").first()
        if ixpfx:
            # if it does, we want to re-assign it to this ix and
            # undelete it
            ixpfx.ixlan = ixlan
            ixpfx.status = "pending"
            ixpfx.save()
        else:
            # if it does not exist we will create a new ixpfx object
            ixpfx = IXLanPrefix.objects.create(
                ixlan=ixlan,
                prefix=prefix,
                status="pending",
                protocol=get_prefix_protocol(prefix),
            )

        return r

    def get_org(self, inst):
        return self.sub_serializer(OrganizationSerializer, inst.org)

    def get_proto_ipv6(self, inst):
        return inst.derived_proto_ipv6

    def get_proto_unicast(self, inst):
        return inst.derived_proto_unicast

    def validate(self, data):
        try:
            data["tech_phone"] = validate_phonenumber(
                data["tech_phone"], data["country"]
            )
        except ValidationError as exc:
            raise serializers.ValidationError({"tech_phone": exc.message})

        try:
            data["policy_phone"] = validate_phonenumber(
                data["policy_phone"], data["country"]
            )
        except ValidationError as exc:
            raise serializers.ValidationError({"policy_phone": exc.message})

        return data


class OrganizationSerializer(
    SpatialSearchMixin, GeocodeSerializerMixin, ModelSerializer
):
    """
    Serializer for peeringdb_server.models.Organization
    """

    net_set = nested(
        NetworkSerializer, exclude=["org_id", "org"], source="net_set_active_prefetched"
    )

    fac_set = nested(
        FacilitySerializer,
        exclude=["org_id", "org"],
        source="fac_set_active_prefetched",
    )

    ix_set = nested(
        InternetExchangeSerializer,
        exclude=["org_id", "org"],
        source="ix_set_active_prefetched",
    )

    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)

    class Meta:  # (AddressSerializer.Meta):
        model = Organization
        depth = 1
        fields = (
            [
                "id",
                "name",
                "aka",
                "name_long",
                "website",
                "notes",
                "net_set",
                "fac_set",
                "ix_set",
            ]
            + AddressSerializer.Meta.fields
            + HandleRefSerializer.Meta.fields
        )
        related_fields = [
            "fac_set",
            "net_set",
            "ix_set",
        ]

        _ref_tag = model.handleref.tag

    @classmethod
    def prepare_query(cls, qset, **kwargs):
        """
        Add special filter options

        Currently supports:

        - asn: filter by network asn
        """
        filters = {}

        if "asn" in kwargs:
            asn = kwargs.get("asn", [""])[0]
            qset = qset.filter(net_set__asn=asn, net_set__status="ok")
            filters.update({"asn": kwargs.get("asn")})

        if "distance" in kwargs:
            qset = cls.prepare_spatial_search(
                qset, kwargs, single_url_param(kwargs, "distance", float)
            )

        return qset, filters


REFTAG_MAP = {
    cls.Meta.model.handleref.tag: cls
    for cls in [
        OrganizationSerializer,
        NetworkSerializer,
        FacilitySerializer,
        InternetExchangeSerializer,
        InternetExchangeFacilitySerializer,
        NetworkFacilitySerializer,
        NetworkIXLanSerializer,
        NetworkContactSerializer,
        IXLanSerializer,
        IXLanPrefixSerializer,
    ]
}
