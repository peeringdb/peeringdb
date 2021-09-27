Generated from rest_throttles.py on 2021-09-27 17:07:21.196869

# peeringdb_server.rest_throttles

Custom rate limit handlers for the REST API.

# Classes
---

## FilterDistanceThrottle

```
FilterDistanceThrottle(peeringdb_server.rest_throttles.FilterThrottle)
```

Rate limiting for ?distance= queries


## FilterThrottle

```
FilterThrottle(rest_framework.throttling.SimpleRateThrottle)
```

Base class for API throttling targeted at specific query filters

Scope name will be 'filter_{self.filter_name}'


### Methods

#### \__init__
`def __init__(self)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### allow_request
`def allow_request(self, request, view)`

Implement the check to see if the request should be throttled.

On success calls `throttle_success`.
On failure calls `throttle_failure`.

---
#### get_cache_key
`def get_cache_key(self, request, view)`

Should return a unique cache-key which can be used for throttling.
Must be overridden.

May return `None` if the request should not be throttled.

---

## IXFImportThrottle

```
IXFImportThrottle(rest_framework.throttling.UserRateThrottle)
```

Limits the rate of API calls that may be made by a given user.

The user id will be used as a unique cache key if the user is
authenticated.  For anonymous requests, the IP address of the request will
be used.


### Methods

#### get_cache_key
`def get_cache_key(self, request, view)`

Should return a unique cache-key which can be used for throttling.
Must be overridden.

May return `None` if the request should not be throttled.

---
