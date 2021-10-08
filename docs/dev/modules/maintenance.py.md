Generated from maintenance.py on 2021-10-06 18:04:54.446347

# peeringdb_server.maintenance

Django middleware to handle maintenance mode.

# Functions
---

## active
`def active()`

return True if maintenance mode is currently active

---
## off
`def off()`

turn maintenance mode off

---
## on
`def on(timeout=None)`

turns maintenance mode on

Keyword Arguments:

    - timeout<int=None>: if specified will automatically
        end maintenance mode after n seconds

---
## raise_if_active
`def raise_if_active()`

raise ActionBlocked exception if maintenance mode is active

---
# Classes
---

## ActionBlocked

```
ActionBlocked(builtins.Exception)
```

Common base class for all non-exit exceptions.


### Methods

#### \__init__
`def __init__(self)`

Initialize self.  See help(type(self)) for accurate signature.

---

## Middleware

```
Middleware(builtins.object)
```

Middleware will return 503 json responses for all write
ops (POST PUT PATCH DELETE)


### Methods

#### \__call__
`def __call__(self, request)`

Call self as a function.

---
#### \__init__
`def __init__(self, get_response=None)`

Initialize self.  See help(type(self)) for accurate signature.

---
