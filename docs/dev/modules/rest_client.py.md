Generated from rest_client.py on 2026-08-15 04:17:12.049436

# peeringdb_server.rest_client

Minimal REST client used by the API test harness (pdb_api_test, tests/).

Vendored from twentyc.rpc (https://github.com/20c/twentyc.rpc), which is
unmaintained and calls pkg_resources.declare_namespace at import -- that made
it fail on setuptools >= 82, where pkg_resources is gone.

# Classes
---

## InvalidRequestException

```
InvalidRequestException(builtins.ValueError)
```

Inappropriate argument value (of correct type).


### Methods

#### \__init__
`def __init__(self, msg, extra)`

Initialize self.  See help(type(self)) for accurate signature.

---

## NotFoundException

```
NotFoundException(builtins.LookupError)
```

Base class for lookup errors.


## PermissionDeniedException

```
PermissionDeniedException(builtins.OSError)
```

Base class for I/O related errors.

