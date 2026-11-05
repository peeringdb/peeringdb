"""
Cache keys built from a request path keep the path and query string out of
the key, so a CacheKeyWarning can't print credentials sent in a URL (#495).
"""

import base64
import warnings
from datetime import datetime

import pytest
from django.core.cache.backends.base import memcache_key_warnings
from django.test import RequestFactory, override_settings
from django.utils.timezone import make_aware
from rest_framework.test import APIClient

from peeringdb_server.middleware import (
    RedisNegativeCacheMiddleware,
    get_inactive_cache_key,
)
from peeringdb_server.rest_throttles import ResponseSizeThrottle

pytestmark = pytest.mark.django_db

SECRET = "AbCd1234.CacheKeySecretValue0123"
# long enough to take the key past memcached's 250 characters
LONG_QUERY = f"key={SECRET}&" + "&".join(f"name__contains=x{i}" for i in range(20))


def request(query=LONG_QUERY):
    return RequestFactory().get("/api/net", QUERY_STRING=query)


def cache_keys(req):
    return [
        ResponseSizeThrottle.size_cache_key(req),
        ResponseSizeThrottle().ident_prefix(req),
        RedisNegativeCacheMiddleware(lambda r: None).generate_cache_key(req),
    ]


# a username read from a file with CRLF line endings, and a key without a dot
CREDENTIAL_HEADERS = [
    "Basic " + base64.b64encode(f"{SECRET}\r:x".encode()).decode(),
    "Api-Key " + SECRET.replace(".", "") * 10,
]


def test_cache_keys_leave_out_path_and_query():
    for key in cache_keys(request()):
        assert SECRET not in key
        assert "/api/net" not in key
        assert not list(memcache_key_warnings(key))


def test_cache_keys_still_tell_requests_apart():
    first = cache_keys(request("name=a"))
    assert cache_keys(request("name=a")) == first
    for key, other in zip(first, cache_keys(request("name=b"))):
        assert key != other


@override_settings(API_CACHE_ENABLED=False)
def test_long_api_url_no_credential_in_warnings():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # once to fill the caches, once to read them back
        for _ in range(2):
            APIClient().get(f"/api/net?{LONG_QUERY}")
    assert not [w for w in caught if SECRET in str(w.message)]


@pytest.mark.parametrize("header", CREDENTIAL_HEADERS)
def test_auth_identity_left_out_of_cache_keys(header):
    req = RequestFactory().get("/api/net", HTTP_AUTHORIZATION=header)
    secret = SECRET.split(".")[1]
    keys = cache_keys(req)
    keys.append(get_inactive_cache_key(f"user__{SECRET}\r"))
    for key in keys:
        assert secret not in key
        assert not list(memcache_key_warnings(key))


@pytest.mark.parametrize("header", CREDENTIAL_HEADERS)
@override_settings(
    API_CACHE_ENABLED=False,
    # basic auth is refused before the cache lookup once MFA enforcement is
    # live, so push both start dates out of the way
    MFA_FORCE_SOFT_START=make_aware(datetime(2099, 1, 1)),
    MFA_FORCE_HARD_START=make_aware(datetime(2099, 1, 1)),
)
def test_credentials_not_in_warnings(header):
    secret = SECRET.split(".")[1]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(2):
            APIClient().get("/api/net", HTTP_AUTHORIZATION=header)
    assert not [w for w in caught if secret in str(w.message)]
