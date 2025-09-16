Generated from db_router.py on 2025-09-16 15:00:08.206614

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
