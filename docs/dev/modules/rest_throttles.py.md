Generated from rest_throttles.py on 2026-11-17 18:01:18.661144

# peeringdb_server.rest_throttles

Custom rate limit handlers for the REST API.

# Classes
---

## APIAnonUserThrottle

```
APIAnonUserThrottle(peeringdb_server.rest_throttles.TargetedRateThrottle)
```

General rate limiting for anonymous users via the request ip-address


## APIUserThrottle

```
APIUserThrottle(peeringdb_server.rest_throttles.TargetedRateThrottle)
```

General rate limiting for authenticated requests (users or orgs)


## ClientIdentMixin

```
ClientIdentMixin(builtins.object)
```

Keys callers without a user or key identity on the client address from
util.get_client_ident, the same one the login throttle, the page rate
limit and the negative cache use (#531).


## FilterDistanceThrottle

```
FilterDistanceThrottle(peeringdb_server.rest_throttles.FilterThrottle)
```

Rate limiting for ?distance= queries.


## FilterThrottle

```
FilterThrottle(peeringdb_server.rest_throttles.ClientIdentMixin, rest_framework.throttling.SimpleRateThrottle)
```

Base class for API throttling targeted at specific query filters.

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

## IRRLookupThrottle

```
IRRLookupThrottle(peeringdb_server.rest_throttles.ClientIdentMixin, rest_framework.throttling.UserRateThrottle)
```

Keys callers without a user or key identity on the client address from
util.get_client_ident, the same one the login throttle, the page rate
limit and the negative cache use (#531).


## IXFImportThrottle

```
IXFImportThrottle(peeringdb_server.rest_throttles.ClientIdentMixin, rest_framework.throttling.UserRateThrottle)
```

Keys callers without a user or key identity on the client address from
util.get_client_ident, the same one the login throttle, the page rate
limit and the negative cache use (#531).


### Methods

#### get_cache_key
`def get_cache_key(self, request, view)`

Should return a unique cache-key which can be used for throttling.
Must be overridden.

May return `None` if the request should not be throttled.

---

## LocationLookupThrottle

```
LocationLookupThrottle(peeringdb_server.rest_throttles.ClientIdentMixin, rest_framework.throttling.SimpleRateThrottle)
```

Keys callers without a user or key identity on the client address from
util.get_client_ident, the same one the login throttle, the page rate
limit and the negative cache use (#531).


### Methods

#### get_cache_key
`def get_cache_key(self, request, view)`

Should return a unique cache-key which can be used for throttling.
Must be overridden.

May return `None` if the request should not be throttled.

---
#### get_rate
`def get_rate(self)`

Determine the string representation of the allowed request rate.

---

## MelissaThrottle

```
MelissaThrottle(peeringdb_server.rest_throttles.TargetedRateThrottle)
```

Rate limits requests that do a melissa lookup (#1124)


## OrganizationUsersThrottle

```
OrganizationUsersThrottle(peeringdb_server.rest_throttles.ClientIdentMixin, rest_framework.throttling.UserRateThrottle)
```

Keys callers without a user or key identity on the client address from
util.get_client_ident, the same one the login throttle, the page rate
limit and the negative cache use (#531).


### Methods

#### \__init__
`def __init__(self)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### get_rate
`def get_rate(self)`

Determine the string representation of the allowed request rate.

---

## ResponseSizeThrottle

```
ResponseSizeThrottle(peeringdb_server.rest_throttles.TargetedRateThrottle)
```

Rate limit repeated requests based request content-size

See #1126 for rationale


### Class Methods

#### cache_response_size
`def cache_response_size(cls, request, size)`

Caches the response size for the request

The api renderer (renderers.py) calls this automatically
when it renders the response

---
#### expected_response_size
`def expected_response_size(cls, request)`

Returns the expected response size (number of bytes) for the request as `int`

It will return None if there is no cached response size for the request.

---
#### size_cache_key
`def size_cache_key(cls, request)`

Returns the cache key to use for storing response size cache

---

## TargetedRateThrottle

```
TargetedRateThrottle(peeringdb_server.rest_throttles.ClientIdentMixin, rest_framework.throttling.SimpleRateThrottle)
```

Base class for targeted rate throttling depending
on authentication status

Rate throttle by
    - user (sess-auth, basic-auth, key),
    - org (key),
    - anonymous (inet, cdir)


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
#### get_rate
`def get_rate(self)`

Determine the string representation of the allowed request rate.

---
#### wait
`def wait(self)`

Returns the recommended next request time in seconds.

This is a custom implmentation of the original wait() logic that can
also handle dynamic downward adjustments of rate limits (through
changing EnvironmentSetting variables for example)

---

## WriteRateThrottle

```
WriteRateThrottle(peeringdb_server.rest_throttles.ClientIdentMixin, rest_framework.throttling.UserRateThrottle)
```

Keys callers without a user or key identity on the client address from
util.get_client_ident, the same one the login throttle, the page rate
limit and the negative cache use (#531).


### Methods

#### \__init__
`def __init__(self)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### get_cache_key
`def get_cache_key(self, request, view)`

Should return a unique cache-key which can be used for throttling.
Must be overridden.

May return `None` if the request should not be throttled.

---
#### get_rate
`def get_rate(self)`

Determine the string representation of the allowed request rate.

---
