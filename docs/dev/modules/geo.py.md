Generated from geo.py on 2021-11-02 10:01:21.611533

# peeringdb_server.geo

Utilities for geocoding and geo normalization.

# Classes
---

## Melissa

```
Melissa(builtins.object)
```

Handle requests to the melissa global address
service used for geocoding and address normalization.


### Methods

#### \__init__
`def __init__(self, key, timeout=5)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### global_address
`def global_address(self, **kwargs)`

Send request to the global address service.

Keyword arguments:

- address1
- address2
- city
- country
- zipcode

---
#### sanitize
`def sanitize(self, **kwargs)`

Take an international address and sanitize it
using the melissa global address service.

---
#### sanitize_address_model
`def sanitize_address_model(self, instance)`

Take an instance of AddressModel and
run its address through the normalization
process.

Note that this will not actually change fields
on the instance.

Return dict with normalized address data and
geo coordinates.

---

## NotFound

```
NotFound(builtins.OSError)
```

Base class for I/O related errors.


## RequestError

```
RequestError(builtins.OSError)
```

Base class for I/O related errors.


### Methods

#### \__init__
`def __init__(self, exc)`

Initialize self.  See help(type(self)) for accurate signature.

---

## Timeout

```
Timeout(builtins.OSError)
```

Base class for I/O related errors.


### Methods

#### \__init__
`def __init__(self)`

Initialize self.  See help(type(self)) for accurate signature.

---
