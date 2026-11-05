Generated from api_cache.py on 2026-11-05 20:07:16.953937

# peeringdb_server.api_cache

Handle loading of api-cache data.

# Functions
---

## narrows
`def narrows(cached, current)`

Return whether visibility `current` is narrower than `cached`.

---
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
`def __init__(self, viewset, qset, filters, query_adjusted=False)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### _apply_visibility_to_row
`def _apply_visibility_to_row(self, row, contacts, ixlans)`

Update the row in place and return False if it is to be dropped.

---
#### apply_changes_since_generation
`def apply_changes_since_generation(self, data, generated)`

Apply restrictions made since the file was generated to the contacts
and exchange LANs in the cached rows: drop the ones deleted, and give
the others their current visibility where it is narrower, so the
permission check at serve time hides what is no longer public.

---
#### changed_visibility
`def changed_visibility(self, model, field, since)`

Return id -> current visibility of the rows of `model` updated since
`since`, with None for rows that are no longer live.

---
#### filter_fields
`def filter_fields(self, row)`

Remove any unwanted fields from the resultset
according to the `fields` filter specified in the request.

---
#### generated_at
`def generated_at(self, meta)`

Return when the data in the cache file was read from the database.

This is the earlier of the generation time recorded in the file and
the file's modification time: `pdb_api_cache --date` records a date
that can lie after the actual read.

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
