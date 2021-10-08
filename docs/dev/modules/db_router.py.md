Generated from db_router.py on 2021-10-06 18:04:54.446347

# peeringdb_server.db_router

Custom django database routers.

Split read and write database connections if needed.

# Classes
---

## DatabaseRouter

```
DatabaseRouter(builtins.object)
```

A very basic databases router that routes to a different
read and write db


## TestRouter

```
TestRouter(peeringdb_server.db_router.DatabaseRouter)
```

A very basic databases router that routes to a different
read and write db

