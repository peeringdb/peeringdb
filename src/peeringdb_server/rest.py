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
import logging
import re
import time
import traceback

import reversion
import unidecode
from django.apps import apps
from django.conf import settings
from django.conf import settings as dj_settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import FieldError, ObjectDoesNotExist, ValidationError
from django.db import connection, transaction
from django.db.models import DateTimeField, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import re_path
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_grainy.exceptions import PermissionDenied
from django_ratelimit.exceptions import Ratelimited
from django_security_keys.models import SecurityKeyDevice
from grainy.const import PERM_CREATE, PERM_DELETE, PERM_READ, PERM_UPDATE
from rest_framework import permissions, routers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, schema
from rest_framework.exceptions import APIException, ParseError
from rest_framework.exceptions import ValidationError as RestValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import exception_handler
from rest_framework.viewsets import GenericViewSet
from two_factor.utils import devices_for_user

from peeringdb_server.api_cache import APICacheLoader, CacheRedirect
from peeringdb_server.auth import enable_api_key_auth
from peeringdb_server.deskpro import ticket_queue_deletion_prevented
from peeringdb_server.models import (
    UTC,
    CarrierFacility,
    Facility,
    InternetExchange,
    Network,
    NetworkIXLan,
    Organization,
    OrganizationAPIKey,
    OrganizationAPIPermission,
    ParentStatusException,
    ProtectedAction,
    User,
    UserAPIKey,
)
from peeringdb_server.permissions import (
    APIPermissionsApplicator,
    ModelViewSetPermissions,
    check_permissions_from_request,
    get_org_key_from_request,
    get_permission_holder_from_request,
    get_user_from_request,
    get_user_key_from_request,
)
from peeringdb_server.rest_throttles import IXFImportThrottle, OrganizationUsersThrottle
from peeringdb_server.search_v2 import search_v2
from peeringdb_server.serializers import (
    ASSetSerializer,
    FacilitySerializer,
    NetworkIXLanSerializer,
    UserSerializer,
)
from peeringdb_server.util import coerce_ipaddr
from peeringdb_server.views import extract_query, perform_search

RATELIMITS = dj_settings.RATELIMITS

logger = logging.getLogger(__name__)


class DataException(ValueError):
    pass


class InactiveKeyException(APIException):
    """
    Raised on api authentications with inactive api keys
    """

    status_code = 403
    default_detail = _(
        "Inactive API key - please contact PeeringDB support for assistance."
    )
    default_code = "permission_denied"


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
            f"Data supplied with the {method} request could not be parsed: {exc}"
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
        auth_check = self.auth_check

        def wrapped(self, request, *args, **kwargs):
            try:
                auth_check(request)
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

    def auth_check(self, request):
        for header in request.META.keys():
            if header.startswith("HTTP_AUTH") and header != "HTTP_AUTHORIZATION":
                if "HTTP_AUTHORIZATION" not in request.META:
                    raise ValueError("Malformed authorization header")
                break

        if "HTTP_AUTHORIZATION" in request.META:
            permission_holder = get_permission_holder_from_request(request)

            if isinstance(permission_holder, AnonymousUser):
                raise ValueError("Unknown authorization method")

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
                    f"Your client version is incompatible with server version of the api, please install peeringdb>={self.version_string(self.min_version)},<={self.version_string(self.max_version)} {backend}>={self.version_string(backend_min)},<={self.version_string(backend_max)}"
                )


class BasicAuthMFABlockWrite(permissions.BasePermission):
    """
    When an account has MFA enabled and basic-auth is used
    to authenticate the account for a write operation on the API
    block the request.
    """

    message = "Cannot perform write operations with a MFA enabled account when authenticating with Basic authentication."

    def has_permission(self, request, view):
        # only check write operations

        if request.method not in ["POST", "PUT", "DELETE", "PATCH"]:
            return True

        # only check basic auth

        if request.headers.get("Authorization", "").split(" ")[0].lower() != "basic":
            return True

        # if user has any U2F devices, block operation

        if request.user.webauthn_security_keys.exists():
            return False

        # if user has any TOPT devices, block operation

        for device in devices_for_user(request.user):
            if isinstance(device, SecurityKeyDevice):
                # security keys are already checked above, and a user will always
                # have one instance of SecurityKeyDevice once they have
                # added a security key, even after they have removed all their
                # keys, so ignore it for this check.

                continue
            else:
                # topt device found, block operation

                return False

        # No MFA found, allow operation

        return True


class InactiveKeyBlock(permissions.BasePermission):
    """
    When an OrganizationAPIKey or a UserAPIKey has status `inactive`
    requests made with such keys should be blocked
    """

    def has_permission(self, request, view):
        permission_holder = get_permission_holder_from_request(request)

        if not isinstance(permission_holder, UserAPIKey | OrganizationAPIKey):
            return True

        if permission_holder.status == "inactive":
            raise InactiveKeyException()

        if isinstance(permission_holder, UserAPIKey):
            if not permission_holder.user.is_active:
                raise InactiveKeyException()

        return True


###############################################################################
# VIEW SETS


class UnlimitedIfNoPagePagination(PageNumberPagination):
    page_size = dj_settings.PAGE_SIZE  # default page_size
    page_size_query_param = "per_page"
    max_page_size = 250

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        if "page" in request.query_params:
            self.pagination_applied = True
            return super().paginate_queryset(queryset, request)
        else:
            self.pagination_applied = False
            return list(queryset)  # Return all without pagination

    def get_paginated_response(self, data):
        return Response(
            {
                "count": len(data),
                "next": None,
                "previous": None,
                "results": data,
            }
        )


class ModelViewSet(viewsets.ModelViewSet):
    """
    Generic ModelViewSet Base Class.
    This should probably be moved to a common lib ?
    """

    paginate_by_param = ("limit",)
    permission_classes = (
        ModelViewSetPermissions,
        BasicAuthMFABlockWrite,
        InactiveKeyBlock,
    )

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

        # get `name_search` parameter
        q = self.request.query_params.get("name_search")
        q_ids = []
        if q:
            model_to_index = {
                "Facility": "fac",
                "Network": "net",
                "InternetExchange": "ix",
                "Organization": "org",
                "Campus": "campus",
                "Carrier": "carrier",
            }
            index_name = model_to_index.get(self.model.__name__, None)
            if index_name:
                search_results = search_v2([q])
                if index_name in search_results:
                    q_ids = [
                        item.get("id") for item in search_results.get(index_name, [])
                    ]
            # no results found - return empty query
            if not q_ids:
                return qset.none()

        # db field filters
        filters = {}
        query_params = self.request.query_params

        if hasattr(self.serializer_class, "finalize_query_params"):
            qset, query_params = self.serializer_class.finalize_query_params(
                qset, query_params
            )

        for k, v in list(query_params.items()):
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
                    "city__in",
                    "state",
                    "zipcode",
                ]:
                    continue
            else:
                if k in ["address1", "city", "country", "state"]:
                    filters[f"{k}__icontains"] = v
                    continue

            v = unidecode.unidecode(v)

            # if country and state are specified, try to normalize state #1079
            if k == "state" and hasattr(
                self.serializer_class, "normalize_state_lookup"
            ):
                v = self.serializer_class.normalize_state_lookup(query_params)

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
                            v = f"{v} 23:59:59.999"

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
                    filters[f"{flt}__icontains"] = v
                elif m.group(2) == "startswith":
                    filters[f"{flt}__istartswith"] = v
                # when the 'in' filters is found attempt to split the
                # provided search value into a list
                elif m.group(2) == "in":
                    filters[k] = v.split(",")
                    print(filters[k])
                else:
                    filters[k] = v
            elif k in field_names:
                # filter exact matches
                try:
                    intyp = field_names.get(k).get_internal_type()
                except Exception:
                    intyp = "CharField"
                if intyp == "ForeignKey":
                    filters[f"{k}_id"] = v
                elif intyp == "DateTimeField" or intyp == "DateField":
                    filters[f"{k}__startswith"] = v
                elif intyp == "BooleanField":
                    filters[k] = v.lower() == "true" or v == "1"
                else:
                    filters[f"{k}__iexact"] = v

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

        # using nested filters will produce duplicates of the same object
        # unless we call distinct()
        qset = qset.distinct()

        if not self.kwargs:
            if since > 0:
                # incremental update query (used by peeringdb-py client
                # to handle incremental updates, will include `deleted` objects)

                allowed_status = ["ok", "deleted"]

                if self.model.HandleRef.tag == "campus":
                    # Special treatment for campus objects, since their status
                    # is fluid, depending on the number of facilities. #1472
                    #
                    # If the campus has less than 2 facilities in it is considered pending
                    # If the campus has 2 or more facilities in it is considered ok
                    #
                    # Pending campuses need to be included in the incremental update , since
                    # a pending campus may be referenced by a facility

                    allowed_status.append("pending")

                qset = (
                    qset.since(
                        timestamp=datetime.datetime.fromtimestamp(since).replace(
                            tzinfo=UTC()
                        ),
                        deleted=True,
                    )
                    .order_by("updated")
                    .filter(status__in=allowed_status)
                )
            else:
                qset = qset.filter(status="ok")
        else:
            qset = qset.filter(status__in=["ok", "pending"])

        if hasattr(self, "apply_pre_slice_filters"):
            qset = self.apply_pre_slice_filters(qset)

        is_specific_object_request = "pk" in self.kwargs

        if limit > 0:
            qset = qset[skip : skip + limit]
        else:
            qset = qset[skip:]

        if not is_specific_object_request:
            # we are handling a list request and need to apply the limit and skip
            # parameters if they are present

            row_count = qset.count()
            if enforced_limit and depth > 0 and row_count > enforced_limit:
                qset = qset[:enforced_limit]
                self.request.meta_response["truncated"] = (
                    f"Your search query (with depth {depth}) returned more than {enforced_limit} rows and has been truncated. Please be more specific in your filters, use the limit and skip parameters to page through the resultset or drop the depth parameter"
                )

        if depth > 0 or self.kwargs:
            return self.serializer_class.prefetch_related(
                qset, self.request, is_list=(len(self.kwargs) == 0)
            )
        else:
            return qset

    pagination_class = UnlimitedIfNoPagePagination

    @client_check()
    def list(self, request, *args, **kwargs):
        t = time.time()
        r = None  # Initialize r to None

        try:
            # *** START OF PAGINATION LOGIC ***
            queryset = self.filter_queryset(self.get_queryset())

            # page_number = self.request.GET.get('page')
            # results_per_page = self.request.GET.get('per_page', self.page_size)

            paginator = self.pagination_class()
            paginator.request = request
            page = paginator.paginate_queryset(queryset, request, view=self)

            if getattr(paginator, "pagination_applied", True):
                serializer = self.get_serializer(page, many=True)
                r = paginator.get_paginated_response(serializer.data)
                self.request.meta_response["pagination"] = {
                    "count": paginator.page.paginator.count,
                    "has_next": paginator.page.has_next(),
                    "has_previous": paginator.page.has_previous(),
                    "next": paginator.get_next_link(),
                    "previous": paginator.get_previous_link(),
                    "page": paginator.page.number,
                    "per_page": paginator.page.paginator.per_page,
                    "total_pages": paginator.page.paginator.num_pages,
                }
            else:
                serializer = self.get_serializer(queryset, many=True)
                r = Response(serializer.data)

            # FIXME: this waits for peeringdb-py fix to deal with 404 raise properly
            if not r or (hasattr(r, "data") and not len(r.data)):
                if self.serializer_class.is_unique_query(request):
                    return Response(
                        status=status.HTTP_404_NOT_FOUND,
                        data={"data": [], "detail": "Entity not found"},
                    )

            applicator = APIPermissionsApplicator(request)

            if not applicator.is_generating_api_cache:
                r.data = applicator.apply(r.data)

            return r

        except ValueError as inst:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": str(inst)}
            )
        except TypeError as inst:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": str(inst)}
            )
        except CacheRedirect as inst:
            cache_data = inst.loader.load()
            if isinstance(cache_data, Response):
                return cache_data

            r = Response(status=200, data=cache_data)
            r.context_data = {"apicache": True}

            applicator = APIPermissionsApplicator(request)
            if not applicator.is_generating_api_cache:
                r.data = applicator.apply(r.data)
            return r
        finally:
            d = time.time() - t
            print(f"done in {d:.5f} seconds, {len(connection.queries)} queries")

    @client_check()
    def retrieve(self, request, *args, **kwargs):
        # could add fk relationships here, one at a time, but we need to define
        # them somewhere by the time we get the serializer, the data is already
        # populated

        t = time.time()
        r = super().retrieve(request, *args, **kwargs)
        d = time.time() - t
        print("done in %.5f seconds, %d queries" % (d, len(connection.queries)))

        applicator = APIPermissionsApplicator(self.request)

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
                    raise OSError("simulated failure")

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
                    raise OSError("simulated failure")

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
                    raise OSError("simulated failure")

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
        Allows managers of an ix to request an IX-F import.
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


class CarrierFacilityMixin:
    """
    Custom API endpoints for the carrier-facility
    object, exposed to api/carrierfac/{id}/{action}
    """

    @transaction.atomic
    @action(detail=True, methods=["POST"])
    def approve(self, request, pk, *args, **kwargs):
        """
        Allows the org to approve a carrier listing at their facility
        """

        carrierfac = CarrierFacility.objects.get(id=pk)

        if not check_permissions_from_request(request, carrierfac.facility, "c"):
            return Response(status=status.HTTP_403_FORBIDDEN)

        carrierfac.status = "ok"
        carrierfac.save()

        return Response(self.serializer_class(carrierfac).data)

    @transaction.atomic
    @action(detail=True, methods=["POST"])
    def reject(self, request, pk, *args, **kwargs):
        """
        Allows the org to reject a carrier listing at their facility
        """

        carrierfac = CarrierFacility.objects.get(id=pk)

        if not check_permissions_from_request(request, carrierfac.facility, "c"):
            return Response(status=status.HTTP_403_FORBIDDEN)

        response = Response(self.serializer_class(carrierfac).data)

        carrierfac.delete()

        return response


class CampusFacilityMixin:
    """
    Custom API endpoints for the campus-facility
    object, exposed to /api/campus/{campus_id}/add-facility/{fac_id}
    and /api/campus/{campus_id}/remove-facility/{fac_id}
    """

    @transaction.atomic
    @action(detail=True, methods=["POST"], url_path=r"add-facility/(?P<fac_id>[^/.]+)")
    def add_facility(self, request, *args, **kwargs):
        """
        Allows the org to approve a campus listing at their facility
        """

        facility_id = self.kwargs.get("fac_id")
        fac = Facility.objects.get(id=facility_id)

        if not check_permissions_from_request(request, fac, "u"):
            return Response(status=status.HTTP_403_FORBIDDEN)

        campus = self.get_object()

        if campus.org_id == fac.org_id:
            fac.campus_id = campus.id
            try:
                fac.save()
            except ValidationError as inst:
                raise RestValidationError({"non_field_errors": inst.messages})

            return Response(FacilitySerializer(fac).data)

        return Response(status=status.HTTP_400_BAD_REQUEST)

    @transaction.atomic
    @action(
        detail=True, methods=["post"], url_path=r"remove-facility/(?P<fac_id>[^/.]+)"
    )
    def remove_facility(self, request, *args, **kwargs):
        """
        Allows the org to reject a campus listing at their facility
        """

        fac = Facility.objects.get(id=self.kwargs.get("fac_id"))

        if not fac.campus_id:
            return Response(FacilitySerializer(fac).data)

        campus = fac.campus

        if not check_permissions_from_request(request, fac, "u"):
            return Response(status=status.HTTP_403_FORBIDDEN)

        fac.campus_id = None
        fac.save()
        campus.save()

        return Response(FacilitySerializer(fac).data)


class NetworkIXLanMixin:
    """
    Custom API endpoint for setting or unsetting the net_side and ix_side values on a NetworkIXLan object.
    Exposed at /api/netixlan/{id}/set-net-side and /api/netixlan/{id}/set-ix-side (POST).

    These endpoints allow networks and exchanges to set (or unset) the net_side and ix_side values
    on a NetworkIXLan by providing a valid fac_id in the payload, or unset by passing null.

    Paths:
    /api/netixlan/{id}/set-net-side:
    /api/netixlan/{id}/set-ix-side:
    POST:
        Summary: Set or unset the net_side or ix_side value on a NetworkIXLan
        Description: Allows networks or exchanges to update the corresponding side values.
        Parameters:
            - id: The ID of the NetworkIXLan to update (in path, required, integer)
        RequestBody:
            - fac_id: The ID of the Facility to set as net_side or ix_side. Null to unset (integer or null, required)
    """

    @transaction.atomic
    @action(detail=True, methods=["POST"], url_path=r"set-net-side")
    def add_net_side(self, request, *args, **kwargs):
        """
        Set or unset the net_side value on a NetworkIXLan.
        This method sets a facility as the net_side based on the facility ID from the request payload.
        If fac_id is null, the net_side will be unset. Permissions are checked before saving changes.
        """
        return self._set_side(
            request, side="net_side", attr="netfac_set", obj="net", model=Network
        )

    @transaction.atomic
    @action(detail=True, methods=["POST"], url_path=r"set-ix-side")
    def add_ix_side(self, request, *args, **kwargs):
        """
        Set or unset the ix_side value on a NetworkIXLan.
        This method sets a facility as the ix_side based on the facility ID from the request payload.
        If fac_id is null, the ix_side will be unset. Permissions are checked before saving changes.
        """
        return self._set_side(
            request, side="ix_side", attr="ixfac_set", obj="ix", model=InternetExchange
        )

    def _set_side(self, request, side, attr, obj, model):
        try:
            netixlan_id = self.kwargs.get("pk")
            netixlan = NetworkIXLan.objects.get(id=netixlan_id)

            obj_id = getattr(netixlan, f"{obj}_id")
            obj_instance = model.objects.get(pk=obj_id)
            if obj == "ix":
                source_obj = netixlan.ixlan.ix
            elif obj == "net":
                source_obj = netixlan.network
            else:
                return Response(status=status.HTTP_403_FORBIDDEN)
            if not self._has_permission(request, source_obj):
                return Response(
                    {"detail": f"Only admins of {obj} can set or unset the {side}"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            fac_id = request.data.get("fac_id")
            if fac_id:
                try:
                    if str(fac_id).strip() == 0:
                        raise ValueError
                    fac_id = int(fac_id)
                    facility_relation = getattr(obj_instance, attr).get(
                        facility_id=fac_id
                    )
                    facility = facility_relation.facility
                except model.DoesNotExist:
                    return Response(
                        {"detail": "Facility not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                except ValueError:
                    raise ValidationError("invalid facility")

                setattr(netixlan, side, facility)
            else:
                setattr(netixlan, side, None)

            netixlan.save()
            return Response(
                NetworkIXLanSerializer(netixlan).data, status=status.HTTP_200_OK
            )

        except NetworkIXLan.DoesNotExist:
            return Response(
                {"detail": "NetworkIXLan not found."}, status=status.HTTP_404_NOT_FOUND
            )
        except model.DoesNotExist:
            return Response(
                {"detail": f"{obj.capitalize()} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValidationError as inst:
            return Response({"detail": str(inst)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _has_permission(self, request, source_obj):
        return check_permissions_from_request(request, source_obj, "c")


class IXFilterMixin:
    """Filter for hide ixs without facility"""

    def apply_pre_slice_filters(self, qset):
        auth_user = get_user_from_request(self.request)

        if "hide_ix_no_fac" in self.request.GET:
            hide_ix_no_fac = self.request.GET.get("hide_ix_no_fac")
            should_hide = hide_ix_no_fac.lower() in ["true", "1"]
        elif auth_user and not isinstance(auth_user, AnonymousUser):
            should_hide = (
                hasattr(auth_user, "hide_ixs_without_fac")
                and auth_user.hide_ixs_without_fac
            )
        else:
            should_hide = False

        if not should_hide:
            return qset

        model_tag = self.model.handleref.tag
        if model_tag == "ix":
            qset = qset.filter(fac_count__gt=0)
        elif model_tag == "ixlan":
            qset = qset.filter(ix__fac_count__gt=0)
        elif model_tag == "net":
            qset = qset.filter(ix_count__gt=0)
        elif model_tag == "netixlan":
            qset = qset.filter(ixlan__ix__fac_count__gt=0)

        return qset

    def get_queryset(self):
        return super().get_queryset()


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
CarrierViewSet = model_view_set("Carrier")
CarrierFacilityViewSet = model_view_set(
    "CarrierFacility", mixins=(CarrierFacilityMixin,)
)
InternetExchangeViewSet = model_view_set(
    "InternetExchange", mixins=(InternetExchangeMixin, IXFilterMixin)
)
InternetExchangeFacilityViewSet = model_view_set("InternetExchangeFacility")
IXLanViewSet = model_view_set("IXLan", methods=["get", "put"], mixins=(IXFilterMixin,))
IXLanPrefixViewSet = model_view_set("IXLanPrefix")
NetworkViewSet = model_view_set("Network", mixins=(IXFilterMixin,))
NetworkContactViewSet = model_view_set("NetworkContact")
NetworkFacilityViewSet = model_view_set("NetworkFacility")
NetworkIXLanViewSet = model_view_set(
    "NetworkIXLan", mixins=(NetworkIXLanMixin, IXFilterMixin)
)
OrganizationViewSet = model_view_set("Organization")
CampusViewSet = model_view_set("Campus", mixins=(CampusFacilityMixin,))


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


@api_view(["GET"])
@schema(None)
@permission_classes([ModelViewSetPermissions, BasicAuthMFABlockWrite])
def view_self_entity(request, data_type):
    """
    This API View redirect self entity API to the corresponding url
    """

    query = request.META["QUERY_STRING"]
    supported_tags = ["org", "net", "ix", "fac", "carrier", "campus"]

    if data_type not in supported_tags:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if (
        request.user.is_authenticated
        and hasattr(request.user, "self_entity_org")
        and request.user.primary_org
    ):
        org = Organization.objects.get(id=request.user.primary_org)

        if data_type == "org":
            obj = org
        else:
            obj = getattr(org, f"{data_type}_set").filter(status="ok").first()
            if not obj:
                obj = REFTAG_MAP[data_type].model.objects.get(
                    id=getattr(settings, f"DEFAULT_SELF_{data_type.upper()}")
                )

        return (
            redirect(f"/api/{data_type}/{obj.id}?{query}")
            if query
            else redirect(f"/api/{data_type}/{obj.id}")
        )

    else:
        obj = REFTAG_MAP[data_type].model.objects.get(
            id=getattr(settings, f"DEFAULT_SELF_{data_type.upper()}")
        )

        return (
            redirect(f"/api/{data_type}/{obj.id}?{query}")
            if query
            else redirect(f"/api/{data_type}/{obj.id}")
        )


class OrganizationUsersViewSet(GenericViewSet):
    """
    ViewSet for managing users within an organization.

    This ViewSet provides endpoints for:
    - Listing all users in an organization
    - Adding new users to an organization
    - Updating user roles within an organization
    - Removing users from an organization

    All operations require:
    1. Valid user OR organization API keys
    2. User must be an admin of the organization OR organization key that has specific permission
    3. API key must be active (InactiveKeyBlock)

    Rate Limits:
    - All endpoints are rate-limited to 1 request per 1 second (OrganizationUsersThrottle)

    Error Handling:
    - Returns appropriate DRF's Response status codes (400, 403, 404, 429)
    - Provides detailed error messages in response
    """

    serializer_class = UserSerializer
    permission_classes = [InactiveKeyBlock]
    throttle_classes = [OrganizationUsersThrottle]

    def get_queryset(self):
        """
        Get the base queryset for organization users.
        Returns all users that belong to the organization either as members or admins.
        """
        try:
            org_id = self.kwargs.get("org_id")
            organization = get_object_or_404(Organization, id=org_id, status="ok")

            return User.objects.filter(
                Q(groups=organization.usergroup)
                | Q(groups=organization.admin_usergroup)
            ).distinct()
        except Organization.DoesNotExist:
            logger.info(f"Organization not found: {org_id}")
            raise
        except Exception as e:
            logger.error(f"Error getting organization users: {str(e)}", exc_info=True)
            raise

    def check_permissions_for_action(self, permission_type):
        """
        Check if the authenticated entity has permission to perform the requested action.

        This function handles permission checking for both user API key authentication and
        organization API key authentication:

        1. For user API key authentication:
            - Uses User.is_org_admin() to verify if the user is an admin of the organization
            - Raises PermissionDenied if the user is not an admin

        2. For organization API key authentication:
            - Checks if the API key has the specific permission (read/write/update/delete)
                on the 'peeringdb.organization.{org_id}.users' namespace
            - Raises PermissionDenied if the API key lacks sufficient permissions

        Parameters:
        permission_type (int): The permission type constant to check against
                            (PERM_READ, PERM_CREATE, PERM_UPDATE, PERM_DELETE)

        Returns:
        None

        Raises:
        PermissionDenied: If the authenticated entity lacks sufficient permissions
        NotFound: If the organization does not exist
        """
        org_id = self.kwargs.get("org_id")
        organization = get_object_or_404(Organization, id=org_id, status="ok")

        permission_holder = get_permission_holder_from_request(self.request)

        if isinstance(permission_holder, UserAPIKey):
            user = permission_holder.user
            if not user.is_org_admin(organization):
                raise PermissionDenied("User is not an admin of this organization")
            return

        if isinstance(permission_holder, OrganizationAPIKey):
            namespace = f"peeringdb.organization.{org_id}.users"
            has_permission = False
            try:
                permission = OrganizationAPIPermission.objects.get(
                    org_api_key=permission_holder, namespace=namespace
                )
                has_permission = (
                    permission.permission & permission_type == permission_type
                )
            except OrganizationAPIPermission.DoesNotExist:
                has_permission = False

            if not has_permission:
                raise PermissionDenied("Insufficient permissions for this operation")

        else:
            raise PermissionDenied("Invalid authentication")

    def handle_exception(self, exc):
        """Override to handle rate limit and other exceptions"""
        if isinstance(exc, Ratelimited):
            return Response(
                {"detail": "Rate limit exceeded. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return super().handle_exception(exc)

    @action(detail=True, methods=["GET"])
    def list_organization_users(self, request, org_id=None):
        """
        List all users associated with an organization
        Requires 'read' permission on org.{id}.users namespace
        """
        try:
            self.check_permissions_for_action(PERM_READ)

            organization = get_object_or_404(Organization, id=org_id, status="ok")
            users = self.get_queryset()

            serializer = UserSerializer(
                users, many=True, context={"organization": organization}
            )
            return Response(serializer.data, status=status.HTTP_200_OK)

        except PermissionDenied as e:
            logger.error(
                f"Permission denied list organization users: {str(e)}", exc_info=True
            )
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(
                f"Error getting lists organization users: {str(e)}", exc_info=True
            )
            raise

    @action(detail=True, methods=["POST"])
    def add_organization_user(self, request, org_id=None):
        """
        Add a user to the organization
        Requires 'create' permission on org.{id}.users namespace
        """
        try:
            self.check_permissions_for_action(PERM_CREATE)

            organization = get_object_or_404(Organization, id=org_id, status="ok")
            user_email = request.data.get("user_email")

            if not user_email:
                return Response(
                    {"detail": "user_email is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            existing_users = self.get_queryset()
            if existing_users.filter(email=user_email).exists():
                return Response(
                    {"detail": "User is already in the organization"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = get_object_or_404(User, email=user_email)

            if not user.emailaddress_set.filter(
                verified=True, email=user_email
            ).exists():
                return Response(
                    {"detail": "User email is not verified"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = UserSerializer(
                data={"role": request.data.get("role", "member")}
            )
            if not serializer.is_valid():
                return Response(
                    {"detail": serializer.errors.get("role", ["Invalid role"])[0]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            role = serializer.validated_data["role"]

            if role == "admin":
                organization.admin_usergroup.user_set.add(user)
            else:
                organization.usergroup.user_set.add(user)

            return Response(
                UserSerializer(user, context={"organization": organization}).data,
                status=status.HTTP_201_CREATED,
            )

        except PermissionDenied as e:
            logger.error(
                f"Permission denied add organization user: {str(e)}", exc_info=True
            )
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(f"Error adding organization user: {str(e)}", exc_info=True)
            raise

    @action(detail=True, methods=["PUT"])
    def update_role_organization_user(self, request, org_id=None, user_id=None):
        """
        Update a user's role in the organization
        Requires 'update' permission on org.{id}.users namespace
        """
        try:
            self.check_permissions_for_action(PERM_UPDATE)

            organization = get_object_or_404(Organization, id=org_id, status="ok")
            role = request.data.get("role")

            if not role:
                return Response(
                    {"detail": "role is required"}, status=status.HTTP_400_BAD_REQUEST
                )

            serializer = UserSerializer(data={"role": role})
            if not serializer.is_valid():
                return Response(
                    {"detail": serializer.errors.get("role", ["Invalid role"])[0]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            role = serializer.validated_data["role"]

            existing_users = self.get_queryset()
            user = existing_users.filter(id=user_id).first()

            if not user:
                return Response(
                    {"detail": "User is not in the organization"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            organization.admin_usergroup.user_set.remove(user)
            organization.usergroup.user_set.remove(user)

            if role == "admin":
                organization.admin_usergroup.user_set.add(user)
            else:
                organization.usergroup.user_set.add(user)

            return Response(
                UserSerializer(user, context={"organization": organization}).data,
                status=status.HTTP_200_OK,
            )

        except PermissionDenied as e:
            logger.error(
                f"Permission denied update role organization user: {str(e)}",
                exc_info=True,
            )
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(f"Error update organization user: {str(e)}", exc_info=True)
            raise

    @action(detail=True, methods=["DELETE"])
    def remove_organization_user(self, request, org_id=None):
        """
        Remove a user from the organization
        Requires 'delete' permission on org.{id}.users namespace
        """
        try:
            self.check_permissions_for_action(PERM_DELETE)

            organization = get_object_or_404(Organization, id=org_id, status="ok")
            user_email = request.data.get("user_email")

            if not user_email:
                return Response(
                    {"detail": "user_email is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            existing_users = self.get_queryset()
            user = existing_users.filter(email=user_email).first()

            if not user:
                return Response(
                    {"detail": "User is not in the organization"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            organization.admin_usergroup.user_set.remove(user)
            organization.usergroup.user_set.remove(user)

            return Response(status=status.HTTP_204_NO_CONTENT)
        except PermissionDenied as e:
            logger.error(
                f"Permission denied remove organization user: {str(e)}", exc_info=True
            )
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(f"Error remove organization user: {str(e)}", exc_info=True)
            raise


def serialize_search_results(result: dict) -> dict:
    """
    Serialize search results into a consistent API response format.
    Removes internal fields while preserving the structure.

    Args:
        result: Raw search results dictionary

    Returns:
        dict: Cleaned API response
    """

    def clean_entity(entity: dict) -> dict:
        """Remove internal fields and format entity data"""
        cleaned = {
            "id": entity["id"],
            "name": entity["name"],
            "org_id": entity["org_id"],
        }

        if "asn" in entity.get("extra", {}):
            cleaned["asn"] = entity["extra"]["asn"]

        if entity.get("sub_name"):
            cleaned["sub_name"] = entity["sub_name"]

        return cleaned

    return {
        entity_type: [clean_entity(item) for item in items]
        for entity_type, items in result.items()
    }


@enable_api_key_auth
def search_api_view(request):
    """
    API endpoint for search functionality.
    Supports the same query parameters as web search v2.
    Requires API key authentication.
    """
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header:
        return JsonResponse(
            {
                "error": "No API key provided. Please include an Authorization header with your API key."
            },
            status=401,
        )

    auth = auth_header.split()
    if len(auth) != 2 or not auth[1].strip():
        return JsonResponse({"error": "API key cannot be empty"}, status=401)

    q, geo, original_query = extract_query(request, version=2)

    if not q and not geo:
        return JsonResponse({})

    result = perform_search(
        q, geo, version=2, original_query=original_query, user=request.user
    )

    response_data = serialize_search_results(result)

    return JsonResponse(
        response_data, json_dumps_params={"indent": 2, "ensure_ascii": False}
    )


# set here in case we want to add more urls later
urlpatterns = [
    re_path("(net|ix|org|fac|carrier|campus)/self", view_self_entity),
    re_path(
        r"^org/(?P<org_id>\d+)/users/?$",
        OrganizationUsersViewSet.as_view({"get": "list_organization_users"}),
        name="organization-users-list",
    ),
    re_path(
        r"^org/(?P<org_id>\d+)/users/add/?$",
        OrganizationUsersViewSet.as_view({"post": "add_organization_user"}),
        name="organization-users-add",
    ),
    re_path(
        r"^org/(?P<org_id>\d+)/users/(?P<user_id>\d+)/?$",
        OrganizationUsersViewSet.as_view({"put": "update_role_organization_user"}),
        name="organization-users-update-role",
    ),
    re_path(
        r"^org/(?P<org_id>\d+)/users/remove/?$",
        OrganizationUsersViewSet.as_view({"delete": "remove_organization_user"}),
        name="organization-users-remove",
    ),
    re_path("search", search_api_view),
]
rout_urls = router.urls
urls = urlpatterns + rout_urls

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
        CampusViewSet,
        CarrierViewSet,
        CarrierFacilityViewSet,
    ]
}
