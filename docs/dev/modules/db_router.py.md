Generated from db_router.py on 2026-03-10 15:05:04.911321

# peeringdb_server.db_router

Custom django database routers.

Split read and write database connections if needed.

# Classes
---

## DatabaseRouter

```
DatabaseRouter(builtins.object)
```

A very basic database router that routes to a different
read and write db.


## TestRouter

```
TestRouter(peeringdb_server.db_router.DatabaseRouter)
```

A very basic database router that routes to a different
read and write db.
