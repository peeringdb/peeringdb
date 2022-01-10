"""
REST API view definitions.

REST API path routing.

REST API permission checking (facilitated through django-grainy).

REST API error handling.

REST API list filtering logic.

peeringdb-py client compatibility checking.

The peeringdb REST API is implemented through django-rest-framework.
"""

import datetime
import importlib
import re
import time
import traceback

import reversion
import unidecode
from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldError, ObjectDoesNotExist, ValidationError
from django.db import connection, transaction
from django.db.models import DateTimeField
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django_grainy.rest import PermissionDenied
from rest_framework import routers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.exceptions import ValidationError as RestValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from peeringdb_server.api_cache import APICacheLoader, CacheRedirect
from peeringdb_server.deskpro import ticket_queue_deletion_prevented
from peeringdb_server.models import UTC, Network, ProtectedAction
from peeringdb_server.permissions import (
    APIPermissionsApplicator,
    ModelViewSetPermissions,
    check_permissions_from_request,
    get_org_key_from_request,
    get_user_key_from_request,
)
from peeringdb_server.rest_throttles import IXFImportThrottle
from peeringdb_server.search import make_name_search_query
from peeringdb_server.serializers import ASSetSerializer, ParentStatusException
from peeringdb_server.util import coerce_ipaddr


class DataException(ValueError):
    pass


class DataMissingException(DataException):

    """ ""
    Raised when the json data sent with a POST, PUT or PATCH
    request is missing.
    """

    def __init__(self, method):
        super().__init__(f"No data was supplied with the {method} request")


class DataParseException(DataException):

    """
    Raised when the json data sent with a POST, PUT or PATCH
    request could not be parsed.
    """

    def __init__(self, method, exc):
        super().__init__(
            "Data supplied with the {} request could not be parsed: {}".format(
                method, exc
            )
        )


###############################################################################


class RestRouter(routers.DefaultRouter):

    schema_title = "PeeringDB API"
    schema_url = ""
    schema_renderers = None

    routes = [
        # List route.
        routers.Route(
            url=r"^{prefix}{trailing_slash}$",
            mapping={"get": "list", "post": "create"},
            name="{basename}-list",
            detail=False,
            initkwargs={"suffix": "List"},
        ),
        # Detail route.
        routers.Route(
            url=r"^{prefix}/{lookup}{trailing_slash}$",
            mapping={
                "get": "retrieve",
                "put": "update",
                "patch": "partial_update",
                "delete": "destroy",
            },
            name="{basename}-detail",
            detail=True,
            initkwargs={"suffix": "Instance"},
        ),
        routers.DynamicRoute(
            url=r"^{prefix}/{lookup}/{url_path}$",
            name="{basename}-{url_name}",
            detail=True,
            initkwargs={},
        ),
        # Dynamically generated routes.
        # Generated using @action or @link decorators on methods of the
        # viewset.
        routers.Route(
            url=r"^{prefix}/{lookup}/{url_path}{trailing_slash}$",
            name="{basename}-{url_name}",
            mapping={},
            detail=True,
            initkwargs={},
        ),
    ]

    def __init__(self, trailing_slash=False):
        self.trailing_slash = trailing_slash and "/" or ""
        super(routers.DefaultRouter, self).__init__(trailing_slash=False)


###############################################################################


def pdb_exception_handler(exc):

    print(traceback.format_exc())

    return exception_handler(exc)


class client_check:
    """
    Decorator that can be attached to rest viewset responses and will
    generate an error response if the requesting peeringdb client
    is running a client or backend version that is incompatible with
    the server.

    Compatibilty is controlled via facsimile during deploy and can
    be configured in env.misc.api.compat
    """

    def __init__(self):
        self.min_version = settings.CLIENT_COMPAT.get("client").get("min")
        self.max_version = settings.CLIENT_COMPAT.get("client").get("max")
        self.backends = settings.CLIENT_COMPAT.get("backends", {})

    def __call__(self, fn):
        compat_check = self.compat_check

        def wrapped(self, request, *args, **kwargs):
            try:
                compat_check(request)
            except ValueError as exc:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST, data={"detail": str(exc)}
                )

            return fn(self, request, *args, **kwargs)

        return wrapped

    def version_tuple(self, str_version):
        """Take a semantic version string and turn into a tuple."""
        return tuple(int(i) for i in str_version.split("."))

    def version_pad(self, version):
        """Take a semantic version tuple and zero pad to dev version."""
        while len(version) < 4:
            version = version + (0,)
        return version

    def version_string(self, version):
        """Take a semantic version tuple and turn into a "." delimited string."""
        return ".".join([str(i) for i in version])

    def backend_min_version(self, backend):
        """Return the min supported version for the specified backend."""
        return self.backends.get(backend, {}).get("min")

    def backend_max_version(self, backend):
        """Return the max supported version for the specified backend."""
        return self.backends.get(backend, {}).get("max")

    def client_info(self, request):
        """
        Parse the useragent in the request and return client version
        info if possible.

        Any connecting client that is NOT the peeringdb client will currently
        return an empty dict and not compatibility checking will be done.
        """

        # if no user agent was specified in headers we bail
        try:
            agent = request.META["HTTP_USER_AGENT"]
        except KeyError:
            return {}

        # check if connecting client is peeringdb-py client and
        # if it parse
        # - the client version
        # - backend name
        # - backend version
        m = re.match(r"PeeringDB/([\d\.]+) (\S+)/([\d\.]+)", agent)
        if m:
            return {
                "client": self.version_tuple(m.group(1)),
                "backend": {
                    "name": m.group(2),
                    "version": self.version_tuple(m.group(3)),
                },
            }
        return {}

    def compat_check(self, request):
        """
        Check if the connecting client is compatible with the API.

        This is currently only sensible when the request is made through
        the official peeringdb-py client, any other client will be
        passed through without checks.

        On incompatibility a ValueError is raised.
        """

        info = self.client_info(request)
        compat = True
        if info:
            backend = info["backend"]["name"]

            if backend not in self.backends:
                return

            backend_min = self.backend_min_version(backend)
            backend_max = self.backend_max_version(backend)
            client_version = info.get("client")
            backend_version = info.get("backend").get("version")

            if self.version_pad(self.min_version) > self.version_pad(client_version):
                # client version is too low
                compat = False
            elif self.version_pad(self.max_version) < self.version_pad(client_version):
                # client version is too high
                compat = False

            if self.version_pad(backend_min) > self.version_pad(backend_version):
                # client backend version is too low
                compat = False
            elif self.version_pad(backend_max) < self.version_pad(backend_version):
                # client backend version is too high
                compat = False

            if not compat:
                raise ValueError(
                    "Your client version is incompatible with server version of the api, please install peeringdb>={},<={} {}>={},<={}".format(
                        self.version_string(self.min_version),
                        self.version_string(self.max_version),
                        backend,
                        self.version_string(backend_min),
                        self.version_string(backend_max),
                    )
                )


###############################################################################
# VIEW SETS


class ModelViewSet(viewsets.ModelViewSet):
    """
    Generic ModelViewSet Base Class.
    This should probably be moved to a common lib ?
    """

    paginate_by_param = ("limit",)
    permission_classes = (ModelViewSetPermissions,)

    def get_queryset(self):
        """
        Prepare the queryset.
        """

        qset = self.model.handleref.all()

        enforced_limit = getattr(settings, "API_DEPTH_ROW_LIMIT", 250)

        self.request.meta_response = {}

        if hasattr(self.serializer_class, "prepare_query"):
            try:
                qset, p_filters = self.serializer_class.prepare_query(
                    qset, **self.request.query_params
                )
            except ValidationError as inst:
                raise RestValidationError({"detail": str(inst)})
            except ValueError as inst:
                raise RestValidationError({"detail": str(inst)})
            except TypeError as inst:
                raise RestValidationError({"detail": str(inst)})
            except FieldError:
                raise RestValidationError({"detail": "Invalid query"})

        else:
            p_filters = {}

        try:
            since = int(float(self.request.query_params.get("since", 0)))
        except ValueError:
            raise RestValidationError(
                {"detail": "'since' needs to be a unix timestamp (epoch seconds)"}
            )
        try:
            skip = int(self.request.query_params.get("skip", 0))
        except ValueError:
            raise RestValidationError({"detail": "'skip' needs to be a number"})
        try:
            limit = int(self.request.query_params.get("limit", 0))
        except ValueError:
            raise RestValidationError({"detail": "'limit' needs to be a number"})

        try:
            depth = int(self.request.query_params.get("depth", 0))
        except ValueError:
            raise RestValidationError({"detail": "'depth' needs to be a number"})

        field_names = dict(
            [(fld.name, fld) for fld in self.model._meta.get_fields()]
            + self.serializer_class.queryable_relations()
        )

        date_fields = ["DateTimeField", "DateField"]

        # haystack search for the legacy `name_search` parameter
        q = self.request.query_params.get("name_search")
        q_ids = []
        if q:
            search_query = make_name_search_query(q).models(self.model)
            q_ids = [sq.pk for sq in search_query]
            # no results found - return empty query
            if not q_ids:
                return qset.none()

        # db field filters
        filters = {}
        for k, v in list(self.request.query_params.items()):

            if k == "q":
                continue

            # if we are doing spatial distance matching, we need to ignore
            # exact filters for location fields
            if getattr(qset, "spatial", False):
                if k in [
                    "latitude",
                    "longitude",
                    "address1",
                    "city",
                    "state",
                    "zipcode",
                ]:
                    continue

            v = unidecode.unidecode(v)

            if k == "ipaddr6":
                v = coerce_ipaddr(v)

            if re.match("^.+[^_]_id$", k) and k not in field_names:
                # if k[-3:] == "_id" and k not in field_names:
                k = k[:-3]

            xl = self.serializer_class.queryable_field_xl

            # only apply filter if the field actually exists and uses a
            # valid suffix
            m = re.match("^(.+)__(lt|lte|gt|gte|contains|startswith|in)$", k)

            # run queryable field translation
            # on the targeted field so that the filter is actually run on
            # a field that django orm is aware of - which in most cases is
            # identical to the serializer field anyways, but in some cases it
            # may need to be substituted
            if m:
                flt = xl(m.group(1))
                k = k.replace(m.group(1), flt, 1)
                if re.match("^.+[^_]_id$", flt) and flt not in field_names:
                    flt = flt[:-3]
            else:
                k = xl(k)
                flt = None

            # prepare db filters
            if m and flt in field_names:
                # filter by function provided in suffix
                try:
                    intyp = field_names.get(flt).get_internal_type()
                except Exception:
                    intyp = "CharField"

                # for greater than date checks we want to force the time to 1
                # msecond before midnight
                if intyp in date_fields:
                    if m.group(2) in ["gt", "lte"]:
                        if len(v) == 10:
                            v = "%s 23:59:59.999" % v

                    # convert to datetime and make tz aware
                    try:
                        v = DateTimeField().to_python(v)
                    except ValidationError as inst:
                        raise RestValidationError({"detail": str(inst[0])})
                    if timezone.is_naive(v):
                        v = timezone.make_aware(v)
                    if "_ctf" in self.request.query_params:
                        self.request._ctf = {f"{m.group(1)}__{m.group(2)}": v}

                # contains should become icontains because we always
                # want it to do case-insensitive checks
                if m.group(2) == "contains":
                    filters["%s__icontains" % flt] = v
                elif m.group(2) == "startswith":
                    filters["%s__istartswith" % flt] = v
                # when the 'in' filters is found attempt to split the
                # provided search value into a list
                elif m.group(2) == "in":
                    filters[k] = v.split(",")
                else:
                    filters[k] = v
            elif k in field_names:
                # filter exact matches
                try:
                    intyp = field_names.get(k).get_internal_type()
                except Exception:
                    intyp = "CharField"
                if intyp == "ForeignKey":
                    filters["%s_id" % k] = v
                elif intyp == "DateTimeField" or intyp == "DateField":
                    filters["%s__startswith" % k] = v
                else:
                    filters["%s__iexact" % k] = v

        # any object ids we got back from processing a `q` (haystack)
        # search we will now merge into the `id__in` filter

        if q_ids:
            if filters.get("id__in"):
                filters["id__in"] += q_ids
            else:
                filters["id__in"] = q_ids

        if filters:
            try:
                qset = qset.filter(**filters)
            except ValidationError as inst:
                raise RestValidationError({"detail": str(inst[0])})
            except ValueError as inst:
                raise RestValidationError({"detail": str(inst[0])})
            except TypeError as inst:
                raise RestValidationError({"detail": str(inst[0])})
            except FieldError:
                raise RestValidationError({"detail": "Invalid query"})

        # check if request qualifies for a cache load
        filters.update(p_filters)
        api_cache = APICacheLoader(self, qset, filters)
        if api_cache.qualifies():
            raise CacheRedirect(api_cache)

        if not self.kwargs:
            if since > 0:
                # .filter(status__in=["ok","deleted"])
                qset = (
                    qset.since(
                        timestamp=datetime.datetime.fromtimestamp(since).replace(
                            tzinfo=UTC()
                        ),
                        deleted=True,
                    )
                    .order_by("updated")
                    .filter(status__in=["ok", "deleted"])
                )
            else:
                qset = qset.filter(status="ok")
        else:
            qset = qset.filter(status__in=["ok", "pending"])

        if not self.kwargs:
            if limit > 0:
                qset = qset[skip : skip + limit]
            else:
                qset = qset[skip:]

            row_count = qset.count()
            if enforced_limit and depth > 0 and row_count > enforced_limit:
                qset = qset[:enforced_limit]
                self.request.meta_response["truncated"] = (
                    "Your search query (with depth %d) returned more than %d rows and has been truncated. Please be more specific in your filters, use the limit and skip parameters to page through the resultset or drop the depth parameter"
                    % (depth, enforced_limit)
                )

        if depth > 0 or self.kwargs:
            return self.serializer_class.prefetch_related(
                qset, self.request, is_list=(len(self.kwargs) == 0)
            )
        else:
            return qset

    @client_check()
    def list(self, request, *args, **kwargs):
        t = time.time()
        try:
            r = super().list(request, *args, **kwargs)
        except ValueError as inst:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": str(inst)}
            )
        except TypeError as inst:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": str(inst)}
            )
        except CacheRedirect as inst:
            r = Response(status=200, data=inst.loader.load())
        d = time.time() - t

        # FIXME: this waits for peeringdb-py fix to deal with 404 raise properly
        if not r or not len(r.data):
            if self.serializer_class.is_unique_query(request):
                return Response(
                    status=404, data={"data": [], "detail": "Entity not found"}
                )

        print("done in %.5f seconds, %d queries" % (d, len(connection.queries)))

        applicator = APIPermissionsApplicator(request)

        if not applicator.is_generating_api_cache:
            r.data = applicator.apply(r.data)

        return r

    @client_check()
    def retrieve(self, request, *args, **kwargs):
        # could add fk relationships here, one at a time, but we need to define
        # them somewhere by the time we get the serializer, the data is already
        # populated

        t = time.time()
        r = super().retrieve(request, *args, **kwargs)
        d = time.time() - t
        print("done in %.5f seconds, %d queries" % (d, len(connection.queries)))

        applicator = APIPermissionsApplicator(request)

        if not applicator.is_generating_api_cache:
            r.data = applicator.apply(r.data)
            if r.data == applicator.denied:
                return Response(status=status.HTTP_403_FORBIDDEN)
        return r

    def require_data(self, request):
        """
        Test that the request contains data in its body that
        can be parsed to the required format (json) and is not
        empty.

        Will raise DataParseException error if request payload could
        not be parsed.

        Will raise DataMissingException error if request payload is
        missing or was parsed to an empty object.
        """
        try:
            request.data
        except ParseError as exc:
            raise DataParseException(request.method, exc)

        if not request.data:
            raise DataMissingException(request.method)

    @transaction.atomic
    @client_check()
    def create(self, request, *args, **kwargs):
        """
        Create object.
        """
        try:
            self.require_data(request)

            org_key = get_org_key_from_request(request)
            user_key = get_user_key_from_request(request)

            with reversion.create_revision():
                if request.user and request.user.is_authenticated:
                    reversion.set_user(request.user)
                if org_key:
                    reversion.set_comment(f"API-key: {org_key.prefix}")
                if user_key:
                    reversion.set_comment(f"API-key: {user_key.prefix}")

                r = super().create(request, *args, **kwargs)
                if "_grainy" in r.data:
                    del r.data["_grainy"]

                # used by api tests to test atomicity
                if self._test_mode_force_failure:
                    raise IOError("simulated failure")

                return r
        except PermissionDenied:
            return Response(status=status.HTTP_403_FORBIDDEN)
        except (ParentStatusException, DataException) as inst:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": str(inst)}
            )
        finally:
            self.get_serializer().finalize_create(request)

    @transaction.atomic
    @client_check()
    def update(self, request, *args, **kwargs):
        """
        Update object.
        """
        try:
            self.require_data(request)

            org_key = get_org_key_from_request(request)
            user_key = get_user_key_from_request(request)

            with reversion.create_revision():
                if request.user and request.user.is_authenticated:
                    reversion.set_user(request.user)
                if org_key:
                    reversion.set_comment(f"API-key: {org_key.prefix}")
                if user_key:
                    reversion.set_comment(f"API-key: {user_key.prefix}")

                r = super().update(request, *args, **kwargs)
                if "_grainy" in r.data:
                    del r.data["_grainy"]

                # used by api tests to test atomicity
                if self._test_mode_force_failure:
                    raise IOError("simulated failure")

                return r

        except PermissionDenied:
            return Response(status=status.HTTP_403_FORBIDDEN)
        except TypeError as inst:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": str(inst)}
            )
        except ValueError as inst:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": str(inst)}
            )
        finally:
            self.get_serializer().finalize_update(request)

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH (partial update) is currently disabled.
        """
        return Response(status=status.HTTP_403_FORBIDDEN)

    @transaction.atomic
    @client_check()
    def destroy(self, request, pk, format=None):
        """
        Delete object.
        """
        try:
            try:
                obj = self.model.objects.get(pk=pk)
            except ValueError:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST, data={"extra": "Invalid id"}
                )
            except self.model.DoesNotExist:
                return Response(status=status.HTTP_204_NO_CONTENT)

            user_key = get_user_key_from_request(request)
            org_key = get_org_key_from_request(request)
            if check_permissions_from_request(request, obj, "d"):
                with reversion.create_revision():
                    if request.user and request.user.is_authenticated:
                        reversion.set_user(request.user)
                    if org_key:
                        reversion.set_comment(f"API-key: {org_key.prefix}")
                    if user_key:
                        reversion.set_comment(f"API-key: {user_key.prefix}")
                    obj.delete()

                # used by api tests to test atomicity
                if self._test_mode_force_failure:
                    raise IOError("simulated failure")

                return Response(status=status.HTTP_204_NO_CONTENT)
            else:
                return Response(status=status.HTTP_403_FORBIDDEN)
        except ProtectedAction as exc:
            exc_message = f"{exc} - " + _(
                "Please contact {} to help with the deletion of this object"
            ).format(settings.DEFAULT_FROM_EMAIL)

            ticket_queue_deletion_prevented(request, exc.protected_object)

            return Response(
                status=status.HTTP_403_FORBIDDEN, data={"detail": exc_message}
            )
        finally:
            self.get_serializer().finalize_delete(request)


class InternetExchangeMixin:

    """
    Custom API endpoints for the internet exchange
    object, exposed to api/ix/{id}/{action}
    """

    @transaction.atomic
    @action(detail=True, methods=["POST"], throttle_classes=[IXFImportThrottle])
    def request_ixf_import(self, request, *args, **kwargs):

        """
        Allows managers of an ix to request an ix-f import.
        (#779)
        """

        ix = self.get_object()

        if not check_permissions_from_request(request, ix, "u"):
            return Response(status=status.HTTP_403_FORBIDDEN)

        if request.user.is_authenticated:
            # user or user api key
            ix.request_ixf_import(request.user)
        else:
            # org key
            ix.request_ixf_import()

        return self.retrieve(request, *args, **kwargs)


# TODO: why are we doing the import like this??!
pdb_serializers = importlib.import_module("peeringdb_server.serializers")
router = RestRouter(trailing_slash=False)

# router helpers


def ref_dict():
    return {tag: view.model for tag, view, na in router.registry}


def model_view_set(model, methods=None, mixins=None):
    """
    Shortcut for peeringdb models to generate viewset and register in the API urls.
    """

    # lookup Serializer class
    scls = getattr(pdb_serializers, model + "Serializer")

    model_t = apps.get_model("peeringdb_server", model)

    # setup class attributes
    clsdict = {
        "model": model_t,
        "serializer_class": scls,
    }

    # create the type
    if not mixins:
        viewset_t = type(model + "ViewSet", (ModelViewSet,), clsdict)
    else:
        viewset_t = type(model + "ViewSet", mixins + (ModelViewSet,), clsdict)

    if methods:
        viewset_t.http_method_names = methods

    # register with the rest router for incoming requests
    ref_tag = model_t.handleref.tag
    router.register(ref_tag, viewset_t, basename=ref_tag)

    # property required for testing api view atomicity
    viewset_t._test_mode_force_failure = False

    return viewset_t


FacilityViewSet = model_view_set("Facility")
InternetExchangeViewSet = model_view_set(
    "InternetExchange", mixins=(InternetExchangeMixin,)
)
InternetExchangeFacilityViewSet = model_view_set("InternetExchangeFacility")
IXLanViewSet = model_view_set("IXLan", methods=["get", "put"])
IXLanPrefixViewSet = model_view_set("IXLanPrefix")
NetworkViewSet = model_view_set("Network")
NetworkContactViewSet = model_view_set("NetworkContact")
NetworkFacilityViewSet = model_view_set("NetworkFacility")
NetworkIXLanViewSet = model_view_set("NetworkIXLan")
OrganizationViewSet = model_view_set("Organization")


class ReadOnlyMixin:
    def destroy(self, request, pk, format=None):
        """
        This endpoint is readonly.
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def create(self, request, *args, **kwargs):
        """
        This endpoint is readonly.
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def update(self, request, *args, **kwargs):
        """
        This endpoint is readonly.
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def patch(self, request, *args, **kwargs):
        """
        This endpoint is readonly.
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class ASSetViewSet(ReadOnlyMixin, viewsets.ModelViewSet):
    """
    AS-SET endpoint.

    List all as sets mapped by asn.
    """

    lookup_field = "asn"
    http_method_names = ["get"]
    model = Network
    serializer_class = ASSetSerializer

    def get_queryset(self):
        return Network.objects.filter(status="ok").exclude(irr_as_set="")

    def list(self, request):
        return Response(Network.as_set_map(self.get_queryset()))

    def retrieve(self, request, asn):
        try:
            network = Network.objects.get(asn=int(asn))
        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": "Invalid ASN"}
            )
        except ObjectDoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({network.asn: network.irr_as_set})


router.register("as_set", ASSetViewSet, basename="as_set")


# set here in case we want to add more urls later
urls = router.urls

REFTAG_MAP = {
    cls.model.handleref.tag: cls
    for cls in [
        OrganizationViewSet,
        NetworkViewSet,
        FacilityViewSet,
        InternetExchangeViewSet,
        InternetExchangeFacilityViewSet,
        NetworkFacilityViewSet,
        NetworkIXLanViewSet,
        NetworkContactViewSet,
        IXLanViewSet,
        IXLanPrefixViewSet,
    ]
}
