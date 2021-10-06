Generated from util.py on 2021-10-06 18:04:54.446347

# peeringdb_server.util

Assorted utility functions for peeringdb site templates.

# Functions
---

## coerce_ipaddr
`def coerce_ipaddr(value)`

ipaddresses can have multiple formats that are equivalent.
This function will standardize a ipaddress string.

Note: this function is not a validator. If it errors
It will return the original string.

---
# Classes
---

## APIPermissionsApplicator

```
APIPermissionsApplicator(grainy.core.NamespaceKeyApplicator)
```

Applicator that looks for permission namespaces from
a specified field in the dict it is scanning


### Instanced Attributes

These attributes / properties will be available on instances of the class

- is_generating_api_cache (`@property`): None

### Methods

#### \__init__
`def __init__(self, user)`

Initialize self.  See help(type(self)) for accurate signature.

---
