from __future__ import annotations

import copy
import logging
import re
from types import FrameType
from urllib.parse import parse_qsl, urlencode

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
from django.http import HttpRequest, QueryDict
from django.template.context import BaseContext
from django.utils.datastructures import MultiValueDict
from django.utils.log import AdminEmailHandler
from django.views.debug import ExceptionReporter as DjangoExceptionReporter
from django.views.debug import SafeExceptionReporterFilter


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
        super().emit(record)


class ExceptionReporterFilter(SafeExceptionReporterFilter):
    """
    Masks credentials in error reports by name: POST and query string
    parameters, local variables and the keys of dicts in local variables.
    Applies to every view, also those that do not declare
    `sensitive_post_parameters` or `sensitive_variables`.
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
        meta = super().get_safe_request_meta(request)
        if not self.is_active(request):
            return meta
        if isinstance(meta.get("QUERY_STRING"), str):
            meta["QUERY_STRING"] = self.cleanse_query_string(meta["QUERY_STRING"])
        for name in self.uri_meta:
            if isinstance(meta.get(name), str):
                meta[name] = self.cleanse_uri(meta[name])
        return meta

    def get_post_parameters(self, request: HttpRequest | None) -> QueryDict | dict:
        post = super().get_post_parameters(request)
        if request is None or not self.is_active(request):
            return post
        return self.cleanse_mapping(post)

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
    """

    def get_traceback_data(self) -> dict:
        data = super().get_traceback_data()
        if (
            self.request is None
            or not isinstance(self.filter, ExceptionReporterFilter)
            or not self.filter.is_active(self.request)
        ):
            return data
        data["request_GET_items"] = self.filter.cleanse_mapping(
            self.request.GET
        ).items()
        data["request_insecure_uri"] = self.filter.cleanse_uri(
            data["request_insecure_uri"]
        )
        return data
