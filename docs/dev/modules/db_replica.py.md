Generated from db_replica.py on 2026-07-14 21:31:39.993597

# peeringdb_server.db_replica

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

# Functions
---

## mark_request_wrote
`def mark_request_wrote()`

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

---
## primary_db
`def primary_db(func)`

Decorator form of ``use_primary_db()``.

---
## use_primary_db
`def use_primary_db()`

Force reads to hit the primary database for this context.

Affects every read inside the block, including transitive calls
through view code, third-party apps, signal handlers — any ORM
query whose router consultation happens while the contextvar is
set will return ``"default"``.

Use inside a GET handler that needs read-your-own-writes semantics
(for example, a view that writes a row and then immediately reads
it back in the same request).

---
## use_replica_for_read
`def use_replica_for_read()`

Returns True if the current context opted to read from the replica.

---
# Classes
---

## ReadReplicaRouterMiddleware

```
ReadReplicaRouterMiddleware(builtins.object)
```

Pin reads to the ``read`` replica on safe methods, and stamp a
short-TTL pin cookie on responses to requests that performed a
write.

Only added to ``MIDDLEWARE`` when both gates in settings are on.


### Methods

#### \__call__
`def __call__(self, request)`

Call self as a function.

---
#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

---
