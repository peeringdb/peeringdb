"""
Tests for the read-replica routing primitives.

Most tests exercise the router, middleware, signal receivers and
``use_primary_db()`` / ``mark_request_wrote()`` helpers directly via
Django's ``RequestFactory``. The trailing block uses Django's test
``client`` and a router spy to confirm the routing path is live during
real GET requests (the test settings install the production router and
middleware against an alias mirrored to default — see
``mainsite/settings/__init__.py`` and ``tests/conftest.py``).
"""

import pytest
from django.db.models.signals import post_delete, post_save
from django.http import HttpResponse
from django.test import RequestFactory

from peeringdb_server import db_replica
from peeringdb_server.db_replica import (
    PIN_COOKIE,
    ReadReplicaRouterMiddleware,
    mark_request_wrote,
    primary_db,
    use_primary_db,
    use_replica_for_read,
)
from peeringdb_server.db_router import DatabaseRouter

# These tests don't touch model data, but the project's conftest has an
# autouse `cleanup` fixture that flushes Django caches — and one of the
# default caches is DB-backed, so unmarked tests are blocked by
# pytest-django.
pytestmark = pytest.mark.django_db


# -- router ---------------------------------------------------------------


def test_router_db_for_read_default_off():
    """Without the middleware setting the flag, reads go to default."""
    assert db_replica.use_replica_for_read() is False
    assert DatabaseRouter().db_for_read(model=None) == "default"


def test_router_db_for_read_when_replica_flag_set():
    token = db_replica._use_replica.set(True)
    try:
        assert DatabaseRouter().db_for_read(model=None) == "read"
    finally:
        db_replica._use_replica.reset(token)


def test_router_db_for_write_always_default():
    token = db_replica._use_replica.set(True)
    try:
        assert DatabaseRouter().db_for_write(model=None) == "default"
    finally:
        db_replica._use_replica.reset(token)


def test_router_allow_migrate_blocks_read_alias():
    r = DatabaseRouter()
    assert r.allow_migrate("read", "peeringdb_server") is False
    assert r.allow_migrate("default", "peeringdb_server") is True


# -- middleware -----------------------------------------------------------


def _captured_middleware():
    captured = {}

    def view(request):
        captured["use_replica"] = use_replica_for_read()
        return HttpResponse("ok")

    return ReadReplicaRouterMiddleware(view), captured


@pytest.mark.parametrize("method", ["get", "head", "options"])
def test_middleware_pins_replica_on_safe_methods(method):
    mw, captured = _captured_middleware()
    request = getattr(RequestFactory(), method)("/")
    mw(request)
    assert captured["use_replica"] is True
    # flag must be cleared once the request unwinds
    assert use_replica_for_read() is False


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_middleware_does_not_pin_replica_on_write_methods(method):
    mw, captured = _captured_middleware()
    request = getattr(RequestFactory(), method)("/")
    mw(request)
    assert captured["use_replica"] is False


def test_middleware_does_not_pin_when_pin_cookie_present():
    mw, captured = _captured_middleware()
    rf = RequestFactory()
    rf.cookies[PIN_COOKIE] = "1"
    request = rf.get("/")
    mw(request)
    assert captured["use_replica"] is False


def test_middleware_sets_pin_cookie_when_request_writes(settings):
    settings.DATABASE_REPLICA_PIN_COOKIE_MAX_AGE = 17
    settings.SESSION_COOKIE_SECURE = True

    def view(request):
        # Simulate a model write inside the request.
        post_save.send(sender=object, instance=None, using="default")
        return HttpResponse("ok")

    response = ReadReplicaRouterMiddleware(view)(RequestFactory().post("/"))
    assert PIN_COOKIE in response.cookies
    cookie = response.cookies[PIN_COOKIE]
    assert cookie.value == "1"
    assert cookie["max-age"] == 17
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["secure"] is True


def test_middleware_pin_cookie_not_secure_when_session_cookie_not_secure(settings):
    settings.SESSION_COOKIE_SECURE = False

    def view(request):
        post_save.send(sender=object, instance=None, using="default")
        return HttpResponse("ok")

    response = ReadReplicaRouterMiddleware(view)(RequestFactory().post("/"))
    assert response.cookies[PIN_COOKIE]["secure"] == ""


def test_middleware_does_not_set_cookie_when_no_write():
    def view(request):
        return HttpResponse("ok")

    response = ReadReplicaRouterMiddleware(view)(RequestFactory().get("/"))
    assert PIN_COOKIE not in response.cookies


def test_middleware_ignores_writes_via_non_default_alias():
    def view(request):
        post_save.send(sender=object, instance=None, using="read")
        return HttpResponse("ok")

    response = ReadReplicaRouterMiddleware(view)(RequestFactory().post("/"))
    assert PIN_COOKIE not in response.cookies


def test_post_delete_also_triggers_pin():
    def view(request):
        post_delete.send(sender=object, instance=None, using="default")
        return HttpResponse("ok")

    response = ReadReplicaRouterMiddleware(view)(RequestFactory().post("/"))
    assert PIN_COOKIE in response.cookies


# -- signal receivers without an active request --------------------------


def test_signal_outside_request_does_not_set_wrote_flag():
    """Writes from management commands etc. must not flip the flag."""
    assert db_replica._request_active.get() is False
    post_save.send(sender=object, instance=None, using="default")
    assert db_replica._request_wrote.get() is False


# -- use_primary_db / decorator -------------------------------------------


def test_use_primary_db_flips_and_restores():
    outer = db_replica._use_replica.set(True)
    try:
        assert use_replica_for_read() is True
        with use_primary_db():
            assert use_replica_for_read() is False
        assert use_replica_for_read() is True
    finally:
        db_replica._use_replica.reset(outer)


def test_primary_db_decorator():
    @primary_db
    def view():
        return use_replica_for_read()

    outer = db_replica._use_replica.set(True)
    try:
        assert view() is False
        assert use_replica_for_read() is True
    finally:
        db_replica._use_replica.reset(outer)


# -- mark_request_wrote ---------------------------------------------------


def test_mark_request_wrote_inside_request_pins_cookie():
    """Manual write-marker (for bulk paths that bypass post_save)."""

    def view(request):
        mark_request_wrote()
        return HttpResponse("ok")

    response = ReadReplicaRouterMiddleware(view)(RequestFactory().post("/"))
    assert PIN_COOKIE in response.cookies


def test_mark_request_wrote_outside_request_is_noop():
    """Calling outside a request scope must not flip global state."""
    assert db_replica._request_active.get() is False
    mark_request_wrote()
    assert db_replica._request_wrote.get() is False


# -- end-to-end routing through a real request --------------------------


def test_get_request_routes_orm_reads_to_read_alias(client, monkeypatch):
    """
    Spy on the production DatabaseRouter to assert that an actual GET
    request routes ORM reads through the "read" alias. The connection
    -aliasing fixture means we can't observe via ``connections["read"]``
    queries directly (same object as default), so we record the router's
    decisions instead.
    """
    decisions = []
    real_db_for_read = DatabaseRouter.db_for_read

    def spy(self, model, **hints):
        alias = real_db_for_read(self, model, **hints)
        decisions.append(alias)
        return alias

    monkeypatch.setattr(DatabaseRouter, "db_for_read", spy)

    response = client.get("/api/org")
    assert response.status_code in (200, 301)

    # At least one ORM read must have routed to "read" — the safe-method
    # path through the middleware. (Some reads may go to "default" via
    # use_primary_db() inside outer middleware; we just need to confirm
    # the routing path is live.)
    assert (
        "read" in decisions
    ), f"expected at least one read to route to 'read', got {decisions!r}"


# -- settings smoke -------------------------------------------------------


def test_test_environment_installs_production_routing_with_mirror():
    """
    The test settings install the production router and middleware and
    back the "read" alias with default's connection (TEST.MIRROR=default)
    so the routing path is exercised by the suite without bootstrapping
    a second database.
    """
    from django.conf import settings

    assert "read" in settings.DATABASES
    assert settings.DATABASES["read"]["TEST"]["MIRROR"] == "default"
    assert "peeringdb_server.db_router.DatabaseRouter" in settings.DATABASE_ROUTERS
    assert (
        "peeringdb_server.db_replica.ReadReplicaRouterMiddleware" in settings.MIDDLEWARE
    )
