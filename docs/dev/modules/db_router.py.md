Generated from db_router.py on 2026-05-12 15:10:38.212377

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

