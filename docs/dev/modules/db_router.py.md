Generated from db_router.py on 2022-09-12 13:25:46.155090

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
