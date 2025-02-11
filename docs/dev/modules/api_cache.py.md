Generated from api_cache.py on 2025-02-11 10:26:48.481231

# peeringdb_server.api_cache

Handle loading of api-cache data.

# Classes
---

## APICacheLoader

```
APICacheLoader(builtins.object)
```

Checks if an API GET request qualifies for a cache load
and if it does allows you to provide the cached result.


### Methods

#### \__init__
`def __init__(self, viewset, qset, filters)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### filter_fields
`def filter_fields(self, row)`

Remove any unwanted fields from the resultset
according to the `fields` filter specified in the request.

---
#### load
`def load(self)`

Load the cached response according to tag and depth.

---
#### qualifies
`def qualifies(self)`

Check if request qualifies for a cache load.

---

## CacheRedirect

```
CacheRedirect(builtins.Exception)
```

Raise this error to redirect to cache response during viewset.get_queryset
or viewset.list()

Argument should be an APICacheLoader instance.


### Methods

#### \__init__
`def __init__(self, loader)`

Initialize self.  See help(type(self)) for accurate signature.

---
