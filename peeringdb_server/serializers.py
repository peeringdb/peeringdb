import ipaddress
import re
import reversion

from django_inet.rest import IPAddressField, IPPrefixField
from django.core.validators import URLValidator
from django.db.models.query import QuerySet
from django.db.models import Prefetch, Q, Sum, IntegerField, Case, When
from django.db import models, transaction, IntegrityError
from django.db.models.fields.related import (
    ReverseManyToOneDescriptor,
    ForwardManyToOneDescriptor,
)
from django.core.exceptions import FieldError, ValidationError
from rest_framework import serializers, validators
from rest_framework.exceptions import ValidationError as RestValidationError

# from drf_toolbox import serializers
from django_handleref.rest.serializers import HandleRefSerializer
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django_peeringdb.models.abstract import AddressModel

from django_namespace_perms.rest import PermissionedModelSerializer
from django_namespace_perms.util import has_perms

from peeringdb_server.inet import RdapLookup, RdapNotFoundError, get_prefix_protocol
from peeringdb_server.deskpro import (
    ticket_queue_asnauto_skipvq,
    ticket_queue_rdap_error,
)
from peeringdb_server.models import (
    QUEUE_ENABLED,
    VerificationQueueItem,
    InternetExchange,
    InternetExchangeFacility,
    IXLan,
    IXLanPrefix,
    Facility,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
)
from peeringdb_server.validators import (
    validate_address_space,
    validate_info_prefixes4,
    validate_info_prefixes6,
    validate_prefix_overlap,
    validate_phonenumber,
    validate_irr_as_set,
)

from django.utils.translation import ugettext_lazy as _

from rdap.exceptions import RdapException

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


def queryable_field_xl(fld):
    """
    Translate <fld>_id into <fld> and also take
    care of translating fac and net queries into "facility"
    and "network" queries

    FIXME: should be renamed on models, but this will open
    a pandora's box im not ready to open yet
    """

    if re.match(".+_id", fld):
        fld = fld[:-3]
    if fld == "fac":
        return "facility"
    elif fld == "net":
        return "network"
    elif re.match("net_(.+)", fld):
        return re.sub("^net_", "network_", fld)
    elif re.match("fac(.+)", fld):
        return re.sub("^fac_", "facility_", fld)
    return fld


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


class UniqueFieldValidator(object):
    """
    For issue #70

    Django-side unique field validation

    This should ideally be done in mysql, however we need to clear out the other
    duplicates first, so we validate on the django side for now
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
            raise RestValidationError(collisions)


class RequiredForMethodValidator(object):
    """
    A validator that makes a field required for certain
    methods
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


class SoftRequiredValidator(object):
    """
    A validator that allows us to require that at least
    one of the specified fields is set
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


class AsnRdapValidator(object):
    """
    A validator that queries rdap entries for the provided value (Asn)
    and will fail if no matching asn is found
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
            emails = rdap.emails
            self.request.rdap_result = rdap
        except RdapException as exc:
            self.request.rdap_error = (self.request.user, asn, exc)
            raise RestValidationError({self.field: "{}: {}".format(self.message, exc)})

    def set_context(self, serializer):
        self.instance = getattr(serializer, "instance", None)
        self.request = serializer._context.get("request")


class FieldMethodValidator(object):
    """
    A validator that will only allow a field to be set for certain
    methods
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
        super(ExtendedURLField, self).__init__(**kwargs)
        validator = URLValidator(message=self.error_messages["invalid"], schemes=schemes)
        self.validators = []
        self.validators.append(validator)


class SaneIntegerField(serializers.IntegerField):
    """
    Integer field that renders null values to 0
    """

    def get_attribute(self, instance):
        r = super(SaneIntegerField, self).get_attribute(instance)
        if r is None:
            return 0
        return r


class ParentStatusException(IOError):
    """
    Throw this when an object cannot be created because it's parent is
    either status pending or deleted
    """

    def __init__(self, parent, typ):
        if parent.status == "pending":
            super(IOError, self).__init__(
                _(
                    "Object of type '%(type)s' cannot be created because it's parent entity '%(parent_tag)s/%(parent_id)s' has not yet been approved"
                )
                % {"type": typ, "parent_tag": parent.ref_tag, "parent_id": parent.id}
            )
        elif parent.status == "deleted":
            super(IOError, self).__init__(
                _(
                    "Object of type '%(type)s' cannot be created because it's parent entity '%(parent_tag)s/%(parent_id)s' has been marked as deleted"
                )
                % {"type": typ, "parent_tag": parent.ref_tag, "parent_id": parent.id}
            )


class AddressSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = (AddressModel,)
        fields = ["address1", "address2", "city", "country", "state", "zipcode"]


class ModelSerializer(PermissionedModelSerializer):
    """
    ModelSerializer that provides pdb API with custom params

    Main problem with doing field ops here is data is already fetched, so while
    it's fine for single columns, it doesn't help on speed for fk relationships
    However data is not yet serialized so there may be some gain

    using custom method fields to introspect doesn't work at all, because
    they're not called until they're serialized, and then are called once per row,

    for example
    test_depth = serializers.SerializerMethodField('check_for_fk')
    def check_for_fk(self, obj):
        print "check ", type(obj)

    class Meta:
        fields = [
            'test_depth',
            ...

    Best bet so far looks like overloading the single object get in the model
    view set, and adding on the relationships, but need to get to get the fields
    defined yet not included in the query, may have to rewrite the base class,
    which would mean talking to the dev and committing back or we'll have this problem
    every update

    After testing, the time is all in serialization and transfer, so culling
    related here should be fine

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
        super(ModelSerializer, self).__init__(*args, **kwargs)

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
        Check if the request parameters are expected to return a unique entity
        """

        return "id" in request.GET

    @classmethod
    def queryable_relations(self):
        """
        Returns a list of all second level queryable relation fields
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
                    field_name = "{}__{}".format(fld.name, _fld.name)

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
        Derive aproporiate depth parameter from request, depending on whether
        result set is a list or single object max and default depth will vary

        This will return the depth specified in the request or the next best
        possible depth
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
        Return max depth according to whether resultset is list or single get
        """
        if is_list:
            return 3
        return 4

    @classmethod
    def default_depth(cls, is_list):
        """
        Return default depth according to whether resultset is list or single get
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
    ):
        """
        Prefetch related sets according to depth specified in the request

        Prefetched set data will be located off the instances in an attribute
        called "<tag>_set_active_prefetched" where tag is the handleref tag
        of the objects the set will be holding
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
                            src_fld = "%s__%s__%s" % (nested, getter, fld)
                        else:
                            src_fld = "%s__%s" % (nested, fld)
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
                            src_fld = "%s__%s__%s" % (nested, getter, fld)
                        else:
                            src_fld = "%s__%s" % (nested, fld)

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
            l = self.in_list
            if l:
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
            return super(ModelSerializer, self).to_representation(data)
        else:
            return data.id

    def sub_serializer(self, serializer, data, exclude=None):
        if not exclude:
            exclude = []
        s = serializer(read_only=True)
        s.parent = self
        s.nested_exclude = exclude
        return s.to_representation(data)

    def create(self, validated_data):
        """
        entities created via the api should go into the verification
        queue with status pending if they are in the QUEUE_ENABLED
        list
        """
        if self.Meta.model in QUEUE_ENABLED:
            validated_data["status"] = "pending"
        else:
            validated_data["status"] = "ok"
        if "suggest" in validated_data:
            del validated_data["suggest"]
        return super(ModelSerializer, self).create(validated_data)

    def _unique_filter(self, fld, data):
        for _fld, slz_fld in list(self._declared_fields.items()):
            if fld == slz_fld.source:
                if type(slz_fld) == serializers.PrimaryKeyRelatedField:
                    return slz_fld.queryset.get(id=data[_fld])

    def run_validation(self, data=serializers.empty):
        try:
            return super(ModelSerializer, self).run_validation(data=data)
        except RestValidationError as exc:
            filters = {}
            for k, v in list(exc.detail.items()):
                v = v[0]

                # During `ix` creation `prefix` is passed to create
                # an `ixpfx` object alongside the ix, it's not part of ix
                # so ignore it (#718)
                if k == "prefix" and self.Meta.model == InternetExchange:
                    continue

                if k == "non_field_errors" and v.find("unique set") > -1:
                    m = re.match("The fields (.+) must make a unique set.", v)
                    if m:
                        for fld in [i.strip() for i in m.group(1).split(",")]:
                            filters[fld] = data.get(fld, self._unique_filter(fld, data))
                elif v.find("must be unique") > -1:
                    filters[k] = data.get(k, self._unique_filter(k, data))

            request = self._context.get("request")
            if filters and request and request.user and request.method == "POST":

                if "fac_id" in filters:
                    filters["facility_id"] = filters["fac_id"]
                    del filters["fac_id"]
                if "net_id" in filters:
                    filters["network_id"] = filters["net_id"]
                    del filters["net_id"]

                try:
                    self.instance = self.Meta.model.objects.get(**filters)
                except self.Meta.model.DoesNotExist:
                    raise exc
                except FieldError as exc:
                    raise exc
                if (
                    has_perms(request.user, self.instance, "update")
                    and self.instance.status == "deleted"
                ):
                    rv = super(ModelSerializer, self).run_validation(data=data)
                    self._undelete = True
                    return rv
                raise
            else:
                raise

    def save(self, **kwargs):
        """
        entities created via api that have status pending should
        attempt to store which user created the item in the
        verification queue instance
        """
        instance = super(ModelSerializer, self).save(**kwargs)

        if instance.status == "deleted" and getattr(self, "_undelete", False):
            instance.status = "ok"
            instance.save()

        if instance.status == "pending":
            if self._context["request"]:
                vq = VerificationQueueItem.objects.filter(
                    content_type=ContentType.objects.get_for_model(type(instance)),
                    object_id=instance.id,
                ).first()
                if vq:
                    vq.user = self._context["request"].user
                    vq.save()

    def finalize_create(self, request):
        """ this will be called on the end of POST request to this serializer """
        pass

    def finalize_update(self, request):
        """ this will be called on the end of PUT request to this serializer """
        pass

    def finalize_delete(self, request):
        """ this will be called on the end of DELETE request to this serializer """
        pass


class RequestAwareListSerializer(serializers.ListSerializer):
    """
    A List serializer that has access to the originating
    request

    We use this as the list serializer class for all nested lists
    so we can apply time filters to the resultset if the _ctf param
    is set in the request
    """

    @property
    def request(self):
        """
        Retrieve the request from the root serializer
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
    Use this function to created nested serializer fields since making
    depth work otherwise while fetching related lists via handlref remains
    to be a mystery
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


# serializers get their own ref_tag in case we want to define different types
# that aren't one to one with models and serializer turns model into a tuple
# so always lookup the ref tag from the serializer (in fact, do we even need it
# on the model?


class FacilitySerializer(ModelSerializer):
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

    net_count = serializers.SerializerMethodField()

    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)

    suggest = serializers.BooleanField(required=False, write_only=True)

    website = serializers.URLField()
    address1 = serializers.CharField()
    city = serializers.CharField()
    zipcode = serializers.CharField()

    tech_phone = serializers.CharField(required=False, allow_blank=True, default="")
    sales_phone = serializers.CharField(required=False, allow_blank=True, default="")

    validators = [FieldMethodValidator("suggest", ["POST"])]

    def has_create_perms(self, user, data):
        # we dont want users to be able to create facilities if the parent
        # organization status is pending or deleted
        if data.get("org") and data.get("org").status != "ok":
            raise ParentStatusException(data.get("org"), self.Meta.model.handleref.tag)
        return super(FacilitySerializer, self).has_create_perms(user, data)

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(data.get("org").id, "create")

    class Meta:
        model = Facility

        fields = (
            [
                "id",
                "org_id",
                "org_name",
                "org",
                "name",
                "website",
                "clli",
                "rencode",
                "npanxx",
                "notes",
                "net_count",
                "latitude",
                "longitude",
                "suggest",
                "sales_email",
                "sales_phone",
                "tech_email",
                "tech_phone",
            ]
            + HandleRefSerializer.Meta.fields
            + AddressSerializer.Meta.fields
        )

        related_fields = ["org"]

        list_exclude = ["org"]

    @classmethod
    def prepare_query(cls, qset, **kwargs):

        qset = qset.select_related("org")
        filters = get_relation_filters(
            ["net_id", "net", "ix_id", "ix", "org_name", "net_count"], cls, **kwargs
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
            elif field == "network_count":
                if e["filt"]:
                    flt = {"net_count_a__%s" % e["filt"]: e["value"]}
                else:
                    flt = {"net_count_a": e["value"]}

                qset = qset.annotate(
                    net_count_a=Sum(
                        Case(
                            When(netfac_set__status="ok", then=1),
                            default=0,
                            output_field=IntegerField(),
                        )
                    )
                ).filter(**flt)

        if "asn_overlap" in kwargs:
            asns = kwargs.get("asn_overlap", [""])[0].split(",")
            qset = cls.Meta.model.overlapping_asns(asns, qset=qset)
            filters.update({"asn_overlap": kwargs.get("asn_overlap")})

        return qset, filters

    def to_internal_value(self, data):
        # if `suggest` keyword is provided, hard-set the org to
        # whichever org is specified in `SUGGEST_ENTITY_ORG`
        #
        # this happens here so it is done before the validators run
        if "suggest" in data:
            data["org_id"] = settings.SUGGEST_ENTITY_ORG
        return super(FacilitySerializer, self).to_internal_value(data)

    def get_org(self, inst):
        return self.sub_serializer(OrganizationSerializer, inst.org)

    def get_net_count(self, inst):
        return inst.net_count

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

    def has_create_perms(self, user, data):
        # we dont want users to be able to create ixfacs if the parent
        # ix or fac status is pending or deleted
        if data.get("ix") and data.get("ix").status != "ok":
            raise ParentStatusException(data.get("ix"), self.Meta.model.handleref.tag)
        if data.get("fac") and data.get("fac").status != "ok":
            raise ParentStatusException(data.get("fac"), self.Meta.model.handleref.tag)
        return super(InternetExchangeFacilitySerializer, self).has_create_perms(
            user, data
        )

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(
            data["ix"].org_id, data["ix"].id, "create"
        )

    class Meta:
        model = InternetExchangeFacility
        fields = [
            "id",
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
        return qset.select_related("ix"), {}

    def get_ix(self, inst):
        return self.sub_serializer(InternetExchangeSerializer, inst.ix)

    def get_fac(self, inst):
        return self.sub_serializer(FacilitySerializer, inst.facility)


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

    def has_create_perms(self, user, data):
        # we dont want users to be able to create contacts if the parent
        # network status is pending or deleted
        if data.get("network") and data.get("network").status != "ok":
            raise ParentStatusException(
                data.get("network"), self.Meta.model.handleref.tag
            )
        return super(NetworkContactSerializer, self).has_create_perms(user, data)

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(
            data["network"].org.id, data["network"].id, "create"
        )

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
        qset = qset.select_related("network")
        return qset, {}

    def get_net(self, inst):
        return self.sub_serializer(NetworkSerializer, inst.network)

    def validate_phone(self, value):
        return validate_phonenumber(value)



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

    def has_create_perms(self, user, data):
        # we dont want users to be able to create netixlans if the parent
        # network or ixlan is pending or deleted
        if data.get("network") and data.get("network").status != "ok":
            raise ParentStatusException(
                data.get("network"), self.Meta.model.handleref.tag
            )
        if data.get("ixlan") and data.get("ixlan").status != "ok":
            raise ParentStatusException(
                data.get("ixlan"), self.Meta.model.handleref.tag
            )
        return super(NetworkIXLanSerializer, self).has_create_perms(user, data)

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(
            data["network"].org.id, data["network"].id, "create"
        )

    class Meta:

        validators = [
            SoftRequiredValidator(
                fields=("ipaddr4", "ipaddr6"), message="Input required for IPv4 or IPv6"
            ),
            UniqueFieldValidator(
                fields=("ipaddr4", "ipaddr6"), message="IP already exists"
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
        Allows filtering by indirect relationships

        Currently supports: ix_id
        """

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
            return "%s: %s" % (inst.ix_name, ixlan_name)
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
            except:
                pass
        return super(NetworkIXLanSerializer, self).run_validation(data=data)

    def validate(self, data):
        netixlan = NetworkIXLan(**data)

        try:
            netixlan.validate_ipaddr4()
        except ValidationError as exc:
            raise serializers.ValidationError({"ipaddr4": exc.message})

        try:
            netixlan.validate_ipaddr6()
        except ValidationError as exc:
            raise serializers.ValidationError({"ipaddr6": exc.message})

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
        filters = get_relation_filters(["name", "country", "city"], cls, **kwargs)
        for field, e in list(filters.items()):
            for valid in ["name", "country", "city"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    field = "facility__{}".format(valid)
                    qset = fn(qset=qset, field=field, **e)
                    break

        return qset.select_related("network", "facility"), filters

    def has_create_perms(self, user, data):
        # we dont want users to be able to create netfac links if the parent
        # network or facility status is pending or deleted
        if data.get("network") and data.get("network").status != "ok":
            raise ParentStatusException(
                data.get("network"), self.Meta.model.handleref.tag
            )
        if data.get("facility") and data.get("facility").status != "ok":
            raise ParentStatusException(
                data.get("facility"), self.Meta.model.handleref.tag
            )
        return super(NetworkFacilitySerializer, self).has_create_perms(user, data)

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(
            data["network"].org.id, data["network"].id, "create"
        )

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
            except:
                pass
        return super(NetworkFacilitySerializer, self).run_validation(data=data)

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
        required=False, allow_blank=True,
        validators=[URLValidator(schemes=["http", "https", "telnet", "ssh"])]
    )

    looking_glass = serializers.CharField(
        required=False, allow_blank=True,
        validators=[URLValidator(schemes=["http", "https", "telnet", "ssh"])]
    )


    info_prefixes4 = SaneIntegerField(
        allow_null=False, required=False, validators=[validate_info_prefixes4]
    )
    info_prefixes6 = SaneIntegerField(
        allow_null=False, required=False, validators=[validate_info_prefixes6]
    )

    suggest = serializers.BooleanField(required=False, write_only=True)
    validators = [AsnRdapValidator(), FieldMethodValidator("suggest", ["POST"])]

    #irr_as_set = serializers.CharField(validators=[validate_irr_as_set])

    class Meta:
        model = Network
        depth = 1
        fields = [
            "id",
            "org_id",
            "org",
            "name",
            "aka",
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
            "notes",
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
        list_exclude = ["org"]
        extra_kwargs = {"allow_ixp_update": {"write_only": True}}

        _ref_tag = model.handleref.tag

    @classmethod
    def prepare_query(cls, qset, **kwargs):
        """
        Allows filtering by indirect relationships

        Currently supports: ixlan_id, ix_id, netixlan_id, netfac_id, fac_id
        """

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
            ],
            cls,
            **kwargs
        )

        for field, e in list(filters.items()):
            for valid in ["ix", "ixlan", "netixlan", "netfac", "fac"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    qset = fn(qset=qset, field=field, **e)
                    break

        if "name_search" in kwargs:
            name = kwargs.get("name_search", [""])[0]
            qset = qset.filter(Q(name__icontains=name) | Q(aka__icontains=name))
            filters.update({"name_search": kwargs.get("name_search")})

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
        if "suggest" in data:
            data["org_id"] = settings.SUGGEST_ENTITY_ORG

        # if an asn exists already but is currently deleted, fail
        # with a specific error message indicating it (#288)

        if Network.objects.filter(asn=data.get("asn"), status="deleted").exists():
            errmsg = _("Network has been deleted. Please contact {}").format(
                settings.DEFAULT_FROM_EMAIL
            )
            raise RestValidationError({"asn": errmsg})

        return super(NetworkSerializer, self).to_internal_value(data)

    def has_create_perms(self, user, data):
        # we dont want users to be able to create networks if the parent
        # organization status is pending or deleted
        if data.get("org") and data.get("org").status != "ok":
            raise ParentStatusException(data.get("org"), self.Meta.model.handleref.tag)
        return super(NetworkSerializer, self).has_create_perms(user, data)

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(data.get("org").id, "create")

    def get_org(self, inst):
        return self.sub_serializer(OrganizationSerializer, inst.org)

    def create(self, validated_data):
        request = self._context.get("request")
        user = request.user

        asn = validated_data.get("asn")

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
                rdap = RdapLookup().get_asn(asn)

        # add network to existing org
        if rdap and user.validate_rdap_relationship(rdap):
            # user email exists in RiR data, skip verification queue
            validated_data["status"] = "ok"
            net = super(ModelSerializer, self).create(validated_data)
            ticket_queue_asnauto_skipvq(
                user, validated_data["org"], net, rdap
            )
            return net

        elif self.Meta.model in QUEUE_ENABLED:
            # user email does NOT exist in RiR data, put into verification
            # queue
            validated_data["status"] = "pending"
        else:
            # verification queue is disabled regardless
            validated_data["status"] = "ok"

        return super(ModelSerializer, self).create(validated_data)


    def finalize_create(self, request):
        rdap_error = getattr(request, "rdap_error", None)
        if rdap_error:
            ticket_queue_rdap_error(*rdap_error)


    def validate_irr_as_set(self, value):
        if value:
            return validate_irr_as_set(value)
        else:
            return value


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

    prefix = IPPrefixField(
        validators=[
            validators.UniqueValidator(queryset=IXLanPrefix.objects.all()),
            validate_address_space,
            validate_prefix_overlap,
        ]
    )

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

    @classmethod
    def prepare_query(cls, qset, **kwargs):
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

    def has_create_perms(self, user, data):
        # we dont want users to be able to create prefixes if the parent
        # ixlan status is pending or deleted
        if data.get("ixlan") and data.get("ixlan").status != "ok":
            raise ParentStatusException(
                data.get("ixlan"), self.Meta.model.handleref.tag
            )
        return super(IXLanPrefixSerializer, self).has_create_perms(user, data)

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(
            data["ixlan"].ix.org.id, data["ixlan"].ix.id, data["ixlan"].id, "create"
        )

    def get_ixlan(self, inst):
        return self.sub_serializer(IXLanSerializer, inst.ixlan)

    def validate(self, data):

        # validate prefix against selected protocol
        #
        # Note: While the IPPrefixField already has this validator set on it
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
        return data


class IXLanSerializer(ModelSerializer):
    """
    Serializer for peeringdb_server.models.IXLan

    Possible relationship queries:
      - ix_id, handled by serializer
    """

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

    def has_create_perms(self, user, data):
        # we dont want users to be able to create ixlans if the parent
        # ix status is pending or deleted
        if data.get("ix") and data.get("ix").status != "ok":
            raise ParentStatusException(data.get("ix"), self.Meta.model.handleref.tag)
        return super(IXLanSerializer, self).has_create_perms(user, data)

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(
            data["ix"].org_id, data["ix"].id, "create"
        )

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
            "ixf_ixp_import_enabled",
        ] + HandleRefSerializer.Meta.fields
        related_fields = ["ix", "net_set", "ixpfx_set"]

        list_exclude = ["ix"]

        extra_kwargs = {
            "ixf_ixp_member_list_url": {"write_only": True},
            "ixf_ixp_import_enabled": {"write_only": True},
        }

        _ref_tag = model.handleref.tag

    @classmethod
    def prepare_query(cls, qset, **kwargs):
        return qset.select_related("ix"), {}

    def get_ix(self, inst):
        return self.sub_serializer(InternetExchangeSerializer, inst.ix)


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

    net_count = serializers.SerializerMethodField()

    suggest = serializers.BooleanField(required=False, write_only=True)

    website = serializers.URLField(required=True)
    tech_email = serializers.EmailField(required=True)
    looking_glass = serializers.CharField(
        required=False, allow_blank=True,
        validators=[URLValidator(schemes=["http", "https", "telnet", "ssh"])]
    )


    tech_phone = serializers.CharField(required=False, allow_blank=True, default="")
    policy_phone = serializers.CharField(required=False, allow_blank=True, default="")

    # For the creation of the initial prefix during exchange
    # creation. It will be a required field during `POST` requests
    # but will be ignored during `PUT` so we cannot just do
    # required=True here
    prefix = IPPrefixField(
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

    validators = [
        FieldMethodValidator("suggest", ["POST"]),
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
            "looking_glass",
            "tech_email",
            "tech_phone",
            "policy_email",
            "policy_phone",
            "fac_set",
            "ixlan_set",
            "suggest",
            "prefix",
            "net_count",
        ] + HandleRefSerializer.Meta.fields
        _ref_tag = model.handleref.tag
        related_fields = ["org", "fac_set", "ixlan_set"]
        list_exclude = ["org"]

    @classmethod
    def prepare_query(cls, qset, **kwargs):

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
            ],
            cls,
            **kwargs
        )

        for field, e in list(filters.items()):
            for valid in ["ixlan", "ixfac", "fac", "net"]:
                if validate_relation_filter_field(field, valid):
                    fn = getattr(cls.Meta.model, "related_to_%s" % valid)
                    qset = fn(qset=qset, field=field, **e)
                    break

            if field == "network_count":
                qset = cls.Meta.model.filter_net_count(qset=qset, **e)

        if "ipblock" in kwargs:
            qset = cls.Meta.model.related_to_ipblock(
                kwargs.get("ipblock", [""])[0], qset=qset
            )
            filters.update({"ipblock": kwargs.get("ipblock")})

        if "name_search" in kwargs:
            name = kwargs.get("name_search", [""])[0]
            qset = qset.filter(Q(name__icontains=name) | Q(name_long__icontains=name))
            filters.update({"name_search": kwargs.get("name_search")})

        if "asn_overlap" in kwargs:
            asns = kwargs.get("asn_overlap", [""])[0].split(",")
            qset = cls.Meta.model.overlapping_asns(asns, qset=qset)
            filters.update({"asn_overlap": kwargs.get("asn_overlap")})

        return qset, filters

    def has_create_perms(self, user, data):
        # we dont want users to be able to create internet exchanges if the parent
        # organization status is pending or deleted
        if data.get("org") and data.get("org").status != "ok":
            raise ParentStatusException(data.get("org"), self.Meta.model.handleref.tag)
        return super(InternetExchangeSerializer, self).has_create_perms(user, data)

    def to_internal_value(self, data):
        # if `suggest` keyword is provided, hard-set the org to
        # whichever org is specified in `SUGGEST_ENTITY_ORG`
        #
        # this happens here so it is done before the validators run
        if "suggest" in data:
            data["org_id"] = settings.SUGGEST_ENTITY_ORG
        return super(InternetExchangeSerializer, self).to_internal_value(data)


    def to_representation(self, data):
        # When an ix is created we want to add the ixlan_id and ixpfx_id
        # that were created to the representation (see #609)

        representation = super().to_representation(data)
        request=  self.context.get("request")
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
        # data because we dont need it during the ix creation
        prefix = validated_data.pop("prefix")

        # create ix
        r = super(InternetExchangeSerializer, self).create(validated_data)

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

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id(data.get("org").id, "create")

    def get_org(self, inst):
        return self.sub_serializer(OrganizationSerializer, inst.org)

    def get_net_count(self, inst):
        return inst.network_count

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


class OrganizationSerializer(ModelSerializer):
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

    def nsp_namespace_create(self, data):
        return self.Meta.model.nsp_namespace_from_id("create")

    class Meta:  # (AddressSerializer.Meta):
        model = Organization
        depth = 1
        fields = (
            ["id", "name", "website", "notes", "net_set", "fac_set", "ix_set"]
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

        return qset, filters


REFTAG_MAP = dict(
    [
        (cls.Meta.model.handleref.tag, cls)
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
    ]
)
