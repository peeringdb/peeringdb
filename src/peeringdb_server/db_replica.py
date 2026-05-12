"""
Read-replica routing support.

When a read replica is configured (``DATABASE_REPLICA_HOST``) and the
middleware kill-switch is on (``DATABASE_REPLICA_ROUTING_ENABLED``), the
``ReadReplicaRouterMiddleware`` defined here pins reads on safe HTTP
methods (GET / HEAD / OPTIONS) to the ``read`` database alias.

The decision is made once at request start. After a write occurs in a
request, a short-TTL cookie (``multidb_pin_writes``) is stamped on the
response so the same client's subsequent GETs stay on primary until the
replica is expected to have caught up.

``use_primary_db()`` is provided as an in-request escape hatch for the
rare GET handler that needs read-your-own-writes semantics.

With either gate off this module's middleware is not installed and the
router (``peeringdb_server.db_router.DatabaseRouter``) defaults to
``default``, so importing this module is always safe.
"""

import contextvars
from contextlib import contextmanager
from functools import wraps

from django.conf import settings
from django.db.models.signals import post_delete, post_save

# Cookie name follows the django-multidb-router convention verbatim.
# We evaluated adopting the library directly and chose to vendor the
# pattern; keeping the same cookie name means a future swap to the
# library remains low-friction. Don't rename without revisiting that
# decision.
PIN_COOKIE = "multidb_pin_writes"

# True for the duration of a request whose reads should hit the replica.
_use_replica = contextvars.ContextVar("peeringdb_use_replica", default=False)

# True if a write to the "default" alias has been observed during the
# current request. Read by the middleware on response.
_request_wrote = contextvars.ContextVar("peeringdb_request_wrote", default=False)

# Marks that an HTTP request is currently active. The signal receivers
# only flip _request_wrote when this is True, so writes from management
# commands or other non-request paths don't trigger pin cookies that
# nobody will see.
_request_active = contextvars.ContextVar("peeringdb_request_active", default=False)


def use_replica_for_read():
    """Returns True if the current context opted to read from the replica."""
    return _use_replica.get()


@contextmanager
def use_primary_db():
    """
    Force reads to hit the primary database for this context.

    Affects every read inside the block, including transitive calls
    through view code, third-party apps, signal handlers — any ORM
    query whose router consultation happens while the contextvar is
    set will return ``"default"``.

    Use inside a GET handler that needs read-your-own-writes semantics
    (for example, a view that writes a row and then immediately reads
    it back in the same request).
    """
    token = _use_replica.set(False)
    try:
        yield
    finally:
        _use_replica.reset(token)


def primary_db(func):
    """Decorator form of ``use_primary_db()``."""

    @wraps(func)
    def _wrapped(*args, **kwargs):
        with use_primary_db():
            return func(*args, **kwargs)

    return _wrapped


def mark_request_wrote():
    """
    Force a pin cookie on the current request's response.

    Use after a bulk write that bypasses ``Model.save()`` /
    ``Model.delete()`` and therefore doesn't fire ``post_save`` /
    ``post_delete`` (``QuerySet.update``, ``bulk_create``,
    ``bulk_update``, raw SQL via ``cursor.execute``). Call site looks
    like::

        Network.objects.filter(...).update(...)
        mark_request_wrote()

    No-op outside an active request scope (e.g., in management commands
    or background tasks), so it's safe to call from helpers that run in
    both contexts.
    """
    if _request_active.get():
        _request_wrote.set(True)


def _on_write(sender, **kwargs):
    if not _request_active.get():
        return
    # A write through .using("read") would be a bug elsewhere, but
    # filtering on the alias keeps us from pinning a client because of
    # something we didn't actually persist to primary.
    if kwargs.get("using") != "default":
        return
    _request_wrote.set(True)


# Connect at import time. No sender filter — any model write counts.
post_save.connect(_on_write, dispatch_uid="peeringdb_replica_post_save")
post_delete.connect(_on_write, dispatch_uid="peeringdb_replica_post_delete")


class ReadReplicaRouterMiddleware:
    """
    Pin reads to the ``read`` replica on safe methods, and stamp a
    short-TTL pin cookie on responses to requests that performed a
    write.

    Only added to ``MIDDLEWARE`` when both gates in settings are on.
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        wrote_token = _request_wrote.set(False)
        active_token = _request_active.set(True)

        if request.method in self.SAFE_METHODS and PIN_COOKIE not in request.COOKIES:
            replica_token = _use_replica.set(True)
        else:
            replica_token = _use_replica.set(False)

        try:
            response = self.get_response(request)
            if _request_wrote.get():
                response.set_cookie(
                    PIN_COOKIE,
                    "1",
                    max_age=getattr(
                        settings, "DATABASE_REPLICA_PIN_COOKIE_MAX_AGE", 15
                    ),
                    httponly=True,
                    samesite="Lax",
                    secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
                )
            return response
        finally:
            _use_replica.reset(replica_token)
            _request_wrote.reset(wrote_token)
            _request_active.reset(active_token)
