Generated from middleware.py on 2021-10-15 07:56:57.376975

# peeringdb_server.middleware

Custom django middleware.

# Classes
---

## CurrentRequestContext

```
CurrentRequestContext(builtins.object)
```

Middleware that sets the current request context.

This allows access to the current request from anywhere.


### Methods

#### \__call__
`def __call__(self, request)`

Call self as a function.

---
#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

---
