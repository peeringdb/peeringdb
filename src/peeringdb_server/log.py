from __future__ import annotations

import copy
import logging
import re
from types import FrameType, SimpleNamespace, TracebackType
from urllib.parse import parse_qsl, urlencode

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
from django.forms import BaseForm, PasswordInput
from django.http import HttpRequest, QueryDict
from django.template.context import BaseContext
from django.urls import Resolver404, resolve
from django.utils.datastructures import MultiValueDict
from django.utils.log import AdminEmailHandler
from django.views.debug import ExceptionReporter as DjangoExceptionReporter
from django.views.debug import (
    SafeExceptionReporterFilter,
    get_exception_reporter_filter,
)


class ThrottledAdminEmailHandler(AdminEmailHandler):
    """
    Throttled admin email handler
    """

    CACHE_KEY = "THROTTLE_ERROR_EMAILS"

    @property
    def cache(self) -> BaseCache:
        """
        returns the specific cache handler set up for this purpose
        """
        return caches["error_emails"]

    def increment_counter(self) -> int | None:
        try:
            self.cache.incr(self.CACHE_KEY)
        except ValueError:
            self.cache.set(self.CACHE_KEY, 1, settings.ERROR_EMAILS_PERIOD)
        return self.cache.get(self.CACHE_KEY)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            counter = self.increment_counter()
        except Exception:
            counter = None
        # counter is None when the cache backend silently fails (e.g.
        # DJANGO_REDIS_IGNORE_EXCEPTIONS swallowed a connection error).
        # Without a counter we can't enforce the throttle, and a sustained
        # cache outage would otherwise mean one email per error. Fail closed.
        if counter is None or counter > settings.ERROR_EMAILS_LIMIT:
            return
        super().emit(self.masked_record(record))

    def masked_record(self, record: logging.LogRecord) -> logging.LogRecord:
        """
        Returns a copy of the record with the request path masked in its
        message (the mail subject) when the report for the request is masked
        wholesale. Other handlers keep the record as it is.
        """
        request = getattr(record, "request", None)
        if request is None:
            return record
        try:
            reporter_filter = get_exception_reporter_filter(request)
            if not isinstance(reporter_filter, ExceptionReporterFilter):
                return record
            if not reporter_filter.for_report(request).mask_all:
                return record
            paths = (request.path, request.path_info)
            masked = copy.copy(record)
            if not isinstance(record.args, tuple):
                raise TypeError("record arguments are not a tuple")
            masked.args = tuple(
                (
                    reporter_filter.cleansed_substitute
                    if isinstance(arg, str) and arg in paths
                    else arg
                )
                for arg in record.args
            )
            return masked
        except Exception:
            masked = copy.copy(record)
            masked.msg = "message withheld"
            masked.args = ()
            return masked


class ExceptionReporterFilter(SafeExceptionReporterFilter):
    """
    Masks credentials in error reports.

    By name: POST and query string parameters, local variables and the keys
    of dicts in local variables. Applies to every view, also those that do
    not declare `sensitive_post_parameters` or `sensitive_variables`.

    By module: every local variable in the frames of the libraries that hold
    credentials under other names, and of form cleaning when the form has a
    credential field.

    Wholesale: every frame variable and all request data, for routes whose
    path carries a credential and when masking itself fails. ExceptionReporter
    works on a copy of the filter per report (`for_report`), so the shared
    default filter keeps no state.
    """

    sensitive_name_pattern = re.compile(
        r"password|secret|token|otp", flags=re.IGNORECASE
    )

    # credentials whose names the pattern does not cover, such as the OAuth
    # authorization code, the signed security key assertion, the Basic auth
    # and API key values the authentication middleware reads, the session
    # cookie in copies of request.META and the TOTP seed during device setup
    sensitive_names = {
        "auth",
        "auth_header",
        "authorization",
        "b32key",
        "code",
        "code_verifier",
        "cookie",
        "credential",
        "credentials",
        "device_code",
        "http_auth",
        "http_authorization",
        "http_cookie",
        "rawkey",
        "req_key",
        "user_code",
    }

    # request.META entries that carry a URL or a query string; the referer is
    # the page a request came from, such as the password reset link
    uri_meta = ("HTTP_REFERER", "RAW_URI", "REQUEST_URI")

    # how far cleanse_value descends into nested containers
    cleanse_depth = 4

    # libraries that hold credentials under neutral names, such as the token
    # request body and Authorization header in the OAuth provider, an API key
    # held as `key` and a TOTP seed during device setup (#537)
    sensitive_modules = (
        "django_otp",
        "mainsite.oauth2",
        "oauth2_provider",
        "oauthlib",
        "peeringdb_server.permissions",
        "rest_framework_api_key",
        "two_factor",
    )

    # form cleaning holds a submitted value as `value`
    form_modules = ("django.forms", "django.core.validators")

    # field and validator frames find their form this many callers up
    form_search_depth = 6

    # routes with a credential in the path
    masked_routes = frozenset({"account_confirm_email"})

    # per report, see for_report
    mask_all = False
    failed = False

    def for_report(self, request: HttpRequest | None) -> ExceptionReporterFilter:
        """
        Returns a copy of the filter for one report, set to mask wholesale on
        a route with a credential in the path, or when that can't be told.
        """
        report_filter = copy.copy(self)
        report_filter.failed = False
        report_filter.mask_all = False
        if request is not None and self.is_active(request):
            try:
                report_filter.mask_all = self.is_masked_route(request)
            except Exception:
                report_filter.mask_all = True
        return report_filter

    def is_masked_route(self, request: HttpRequest) -> bool:
        match = getattr(request, "resolver_match", None)
        if match is None:
            try:
                match = resolve(request.path_info)
            except Resolver404:
                return False
        return match.url_name in self.masked_routes

    @staticmethod
    def in_modules(module: str, prefixes: tuple[str, ...]) -> bool:
        return any(
            module == prefix or module.startswith(prefix + ".") for prefix in prefixes
        )

    def is_sensitive_frame(self, tb_frame: FrameType) -> bool:
        module = tb_frame.f_globals.get("__name__")
        if not isinstance(module, str):
            return False
        if self.in_modules(module, self.sensitive_modules):
            return True
        return self.in_modules(
            module, self.form_modules
        ) and self.cleans_credential_form(tb_frame)

    def cleans_credential_form(self, frame: FrameType | None) -> bool:
        """
        Whether the form the frame belongs to has a credential field: a
        password input, or a field name masked by name. PeeringDB's own
        password forms use plain text fields.
        """
        for _ in range(self.form_search_depth):
            if frame is None:
                return False
            form = frame.f_locals.get("self")
            if isinstance(form, BaseForm):
                return any(
                    self.is_sensitive_name(name)
                    or isinstance(field.widget, PasswordInput)
                    for name, field in form.fields.items()
                )
            frame = frame.f_back
        return False

    def mask_wholesale(self, request: HttpRequest, attribute: str) -> dict:
        """
        Returns the names of a request mapping, such as META or POST, with
        every value masked.
        """
        try:
            return dict.fromkeys(getattr(request, attribute), self.cleansed_substitute)
        except Exception:
            return {}

    def is_sensitive_name(self, name: object) -> bool:
        return isinstance(name, str) and (
            name.lower() in self.sensitive_names
            or self.sensitive_name_pattern.search(name) is not None
        )

    def cleanse_query_string(self, query: str) -> str:
        params = parse_qsl(query, keep_blank_values=True)
        if not any(self.is_sensitive_name(name) for name, _ in params):
            return query
        return urlencode(
            [
                (
                    name,
                    self.cleansed_substitute if self.is_sensitive_name(name) else value,
                )
                for name, value in params
            ],
            safe="*",
        )

    def cleanse_uri(self, uri: str) -> str:
        path, separator, query = uri.partition("?")
        if not separator:
            return uri
        return f"{path}?{self.cleanse_query_string(query)}"

    def cleanse_mapping(self, mapping: dict) -> dict:
        names = [name for name in mapping if self.is_sensitive_name(name)]
        if not names:
            return mapping
        # shallow: QueryDict.copy() deep-copies, which fails on uploaded files
        cleansed = copy.copy(mapping)
        for name in names:
            cleansed[name] = self.cleansed_substitute
        return cleansed

    def cleanse_request_repr(self, request: HttpRequest) -> str:
        """
        Returns the request's repr with the query string cleansed.
        """
        try:
            path = self.cleanse_uri(request.get_full_path())
        except Exception:
            return self.cleansed_substitute
        return f"<{type(request).__name__}: {request.method} {path!r}>"

    def cleanse_value(
        self, value: object, depth: int = 0, path: frozenset[int] = frozenset()
    ) -> object:
        """
        Cleanses a local variable: the query string of a request and the
        sensitive keys of a dict, also inside dicts, lists, tuples and
        template contexts, such as the `args` of view decorators.

        `path` holds the ids of the containers being cleansed, so a container
        that contains itself is left as it is.
        """
        if isinstance(value, HttpRequest):
            return self.cleanse_request_repr(value)
        if id(value) in path:
            return value
        if isinstance(value, MultiValueDict) or (
            isinstance(value, dict) and depth >= self.cleanse_depth
        ):
            return self.cleanse_mapping(value)
        if depth >= self.cleanse_depth:
            return value
        path = path | {id(value)}
        if isinstance(value, BaseContext):
            return [self.cleanse_value(item, depth + 1, path) for item in value.dicts]
        if isinstance(value, dict):
            cleansed = self.cleanse_mapping(value)
            nested = {}
            for name, item in cleansed.items():
                cleansed_item = self.cleanse_value(item, depth + 1, path)
                if cleansed_item is not item:
                    nested[name] = cleansed_item
            if not nested:
                return cleansed
            if cleansed is value:
                cleansed = copy.copy(value)
            cleansed.update(nested)
            return cleansed
        if type(value) is list or type(value) is tuple:
            items = [self.cleanse_value(item, depth + 1, path) for item in value]
            if all(item is original for item, original in zip(items, value)):
                return value
            return items if type(value) is list else tuple(items)
        return value

    def get_safe_request_meta(self, request: HttpRequest) -> dict:
        if self.mask_all:
            return self.mask_wholesale(request, "META")
        meta = super().get_safe_request_meta(request)
        if not self.is_active(request):
            return meta
        try:
            if isinstance(meta.get("QUERY_STRING"), str):
                meta["QUERY_STRING"] = self.cleanse_query_string(meta["QUERY_STRING"])
            for name in self.uri_meta:
                if isinstance(meta.get(name), str):
                    meta[name] = self.cleanse_uri(meta[name])
        except Exception:
            self.failed = True
            return {}
        return meta

    def get_safe_cookies(self, request: HttpRequest) -> dict:
        if self.mask_all:
            return self.mask_wholesale(request, "COOKIES")
        return super().get_safe_cookies(request)

    def get_post_parameters(self, request: HttpRequest | None) -> QueryDict | dict:
        if request is not None and self.mask_all:
            return self.mask_wholesale(request, "POST")
        post = super().get_post_parameters(request)
        if request is None or not self.is_active(request):
            return post
        try:
            return self.cleanse_mapping(post)
        except Exception:
            self.failed = True
            return {}

    def get_cleansed_multivaluedict(
        self, request: HttpRequest | None, multivaluedict: MultiValueDict
    ) -> MultiValueDict | str:
        # a failure here would lose the whole report, so mask the value instead
        try:
            multivaluedict = super().get_cleansed_multivaluedict(
                request, multivaluedict
            )
            if not self.is_active(request):
                return multivaluedict
            return self.cleanse_mapping(multivaluedict)
        except Exception:
            return self.cleansed_substitute

    def get_traceback_frame_variables(
        self, request: HttpRequest | None, tb_frame: FrameType
    ) -> list[tuple[str, object]]:
        variables = super().get_traceback_frame_variables(request, tb_frame)
        if not self.is_active(request):
            return variables
        mask_frame = self.mask_all
        if not mask_frame:
            try:
                mask_frame = self.is_sensitive_frame(tb_frame)
            except Exception:
                self.failed = mask_frame = True
        if mask_frame:
            return [(name, self.cleansed_substitute) for name, _ in variables]
        cleansed: list[tuple[str, object]] = []
        for name, value in variables:
            if self.is_sensitive_name(name):
                value = self.cleansed_substitute
            else:
                try:
                    value = self.cleanse_value(value)
                except Exception:
                    value = self.cleansed_substitute
            cleansed.append((name, value))
        return cleansed


class ExceptionReporter(DjangoExceptionReporter):
    """
    Masks credentials passed in the query string, such as the password reset
    token, in the request URL and GET parameters of error reports.

    When the filter masks the report wholesale, or a masking step failed, the
    report is built with every frame variable and all request data masked,
    and the request path hidden. The traceback and the exception stay.
    """

    def __init__(
        self,
        request: HttpRequest | None,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | str | None,
        tb: TracebackType | None,
        is_email: bool = False,
    ) -> None:
        super().__init__(request, exc_type, exc_value, tb, is_email)
        # set by the base class
        reporter_filter = getattr(self, "filter", None)
        if isinstance(reporter_filter, ExceptionReporterFilter):
            self.filter = reporter_filter.for_report(request)

    def get_traceback_data(self) -> dict:
        data = super().get_traceback_data()
        if (
            self.request is None
            or not isinstance(self.filter, ExceptionReporterFilter)
            or not self.filter.is_active(self.request)
        ):
            return data
        if not self.filter.mask_all:
            try:
                data["request_GET_items"] = self.filter.cleanse_mapping(
                    self.request.GET
                ).items()
                data["request_insecure_uri"] = self.filter.cleanse_uri(
                    data["request_insecure_uri"]
                )
            except Exception:
                self.filter.failed = True
            if not self.filter.failed:
                return data
            self.filter.mask_all = True
            data = super().get_traceback_data()
        return self.mask_request_wholesale(data)

    def mask_request_wholesale(self, data: dict) -> dict:
        substitute = self.filter.cleansed_substitute
        get_items = self.filter.mask_wholesale(self.request, "GET").items()
        files_items = self.filter.mask_wholesale(self.request, "FILES").items()
        data["request_GET_items"] = get_items
        data["request_FILES_items"] = files_items
        data["request_insecure_uri"] = substitute
        # the templates read the path and method from the request itself
        data["request"] = SimpleNamespace(
            path_info=substitute,
            META={"REQUEST_METHOD": getattr(self.request, "method", None)},
            GET=bool(get_items),
            FILES=bool(files_items),
            COOKIES=bool(data["request_COOKIES_items"]),
        )
        return data
