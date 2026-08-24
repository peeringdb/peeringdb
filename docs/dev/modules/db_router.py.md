Generated from db_router.py on 2026-08-15 04:17:12.049436

# peeringdb_server.db_router

Custom django database routers.

Split read and write database connections if needed.

# Classes
---

## DatabaseRouter

```
DatabaseRouter(builtins.object)
```

Routes reads to the "read" replica only when the request middleware
has opted-in for this request via a thread-local flag.

Writes always go to "default" (primary).

See peeringdb_server.db_replica for the middleware that drives this.
