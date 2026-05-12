"""
Regression tests for the Redis-resilience changes:

- SessionStore.create() probe-and-fail-fast when the session cache is unreachable
- ThrottledAdminEmailHandler tolerates a None counter from a swallowed cache error
- RATELIMIT_FAIL_OPEN allows requests through when the rate-limit cache is unreachable

Each test substitutes a real cache backend (DummyCache or SilentlyBrokenCache)
for the relevant alias to mirror the "swallowed Redis error" condition without
mocking the cache layer.
"""

import logging

import pytest
from django.core.cache.backends.dummy import DummyCache
from django.test import RequestFactory, override_settings
from django_ratelimit.core import get_usage

from peeringdb_server.log import ThrottledAdminEmailHandler
from peeringdb_server.sessions import SessionStore

# Conftest's autouse cleanup fixture iterates caches and calls .clear(),
# which touches the DB-backed cache aliases in the test config. Every test
# in this module therefore needs DB access.
pytestmark = pytest.mark.django_db


class SilentlyBrokenCache(DummyCache):
    """
    A real Django cache backend that mirrors django-redis's behaviour when
    DJANGO_REDIS_IGNORE_EXCEPTIONS=True and Redis is unreachable: writes
    silently fail (add returns False, set is a no-op) and reads return None.

    DummyCache by itself isn't a faithful simulation here because its add()
    returns True — django-ratelimit then treats the rate-limit counter as
    successfully initialised, which is the opposite of what we need.
    """

    def add(self, key, value, timeout=None, version=None):
        return False

    def incr(self, key, delta=1, version=None):
        return None


DUMMY_CACHE = {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}
BROKEN_CACHE = {"BACKEND": "tests.test_redis_resilience.SilentlyBrokenCache"}


def _all_dummy_caches():
    return {
        alias: DUMMY_CACHE
        for alias in ("default", "session", "negative", "error_emails", "geo")
    }


def _all_broken_caches():
    return {
        alias: BROKEN_CACHE
        for alias in ("default", "session", "negative", "error_emails", "geo")
    }


class TestSessionStoreFailFast:
    @override_settings(CACHES=_all_dummy_caches())
    def test_create_raises_when_cache_unavailable(self):
        store = SessionStore()
        with pytest.raises(RuntimeError, match="Session cache is unavailable"):
            store.create()

    def test_create_succeeds_with_working_cache(self):
        store = SessionStore()
        store.create()
        assert store.session_key
        assert len(store.session_key) >= 8

    def test_probe_key_is_unique_per_call(self):
        # The per-call probe key prevents the "two workers stomp each other's
        # probe and one falsely raises" race. Verify the contract directly:
        # consecutive create() calls write to distinct probe keys.
        store = SessionStore()
        cache = store._cache
        seen_keys = []
        original_set = cache.set

        def tracking_set(key, value, timeout=None, version=None):
            if isinstance(key, str) and key.startswith(SessionStore._PROBE_PREFIX):
                seen_keys.append(key)
            return original_set(key, value, timeout)

        cache.set = tracking_set
        try:
            store.create()
            SessionStore().create()
        finally:
            cache.set = original_set

        assert len(seen_keys) == 2
        assert seen_keys[0] != seen_keys[1]
        # Sanity: the constant prefix alone would be the bug we just fixed.
        assert seen_keys[0] != SessionStore._PROBE_PREFIX


class TestThrottledAdminEmailHandler:
    def _record(self):
        return logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="boom",
            args=None,
            exc_info=None,
        )

    @override_settings(CACHES=_all_dummy_caches())
    def test_emit_does_not_raise_when_counter_is_none(self):
        # Original bug: TypeError when counter > settings.ERROR_EMAILS_LIMIT
        # with counter=None crashed the logger and masked the original error.
        ThrottledAdminEmailHandler().emit(self._record())  # must not raise

    @override_settings(CACHES=_all_dummy_caches())
    def test_emit_drops_email_when_counter_is_none(self, mailoutbox):
        # Fail-closed: a sustained cache outage shouldn't translate into
        # one admin email per error.
        ThrottledAdminEmailHandler().emit(self._record())
        assert len(mailoutbox) == 0


class TestRatelimitFailOpen:
    @override_settings(RATELIMIT_FAIL_OPEN=True, CACHES=_all_broken_caches())
    def test_get_usage_returns_none_when_cache_unavailable(self):
        request = RequestFactory().get("/test/")
        usage = get_usage(
            request,
            group="test_failopen",
            key="ip",
            rate="1/m",
            increment=True,
        )
        assert usage is None

    @override_settings(RATELIMIT_FAIL_OPEN=False, CACHES=_all_broken_caches())
    def test_get_usage_fails_closed_when_flag_disabled(self):
        request = RequestFactory().get("/test/")
        usage = get_usage(
            request,
            group="test_failclosed",
            key="ip",
            rate="1/m",
            increment=True,
        )
        assert usage["should_limit"] is True
