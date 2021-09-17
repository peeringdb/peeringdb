# peeringdb_server.db_router

custom django database routers

allows us to split read and write database connections if needed

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

