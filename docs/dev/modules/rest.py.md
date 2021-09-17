# peeringdb_server.rest

REST API view definitions

REST API path routing

REST API permission checking (facilitated through django-grainy)

REST API error handling

REST API list filtering logic

peeringdb-py client compatibility checking

The peeringdb REST API is implemented through django-rest-framework

# Functions
---

## model_view_set
`def model_view_set(model, methods=None, mixins=None)`

shortcut for peeringdb models to generate viewset and register in the API urls

---
# Classes
---

## ASSetViewSet

```
ASSetViewSet(peeringdb_server.rest.ReadOnlyMixin, rest_framework.viewsets.ModelViewSet)
```

AS-SET endpoint

lists all as sets mapped by asn


### Methods

#### get_queryset
`def get_queryset(self)`

Get the list of items for this view.
This must be an iterable, and may be a queryset.
Defaults to using `self.queryset`.

This method should always be used rather than accessing `self.queryset`
directly, as `self.queryset` gets evaluated only once, and those results
are cached for all subsequent requests.

You may want to override this if you need to provide different
querysets depending on the incoming request.

(Eg. return a list of items that is specific to the user)

---

## DataException

```
DataException(builtins.ValueError)
```

Inappropriate argument value (of correct type).


## DataMissingException

```
DataMissingException(peeringdb_server.rest.DataException)
```

""
Will be raised when the json data sent with a POST, PUT or PATCH
request is missing


### Methods

#### \__init__
`def __init__(self, method)`

Initialize self.  See help(type(self)) for accurate signature.

---

## DataParseException

```
DataParseException(peeringdb_server.rest.DataException)
```

Will be raised when the json data sent with a POST, PUT or PATCH
request could not be parsed


### Methods

#### \__init__
`def __init__(self, method, exc)`

Initialize self.  See help(type(self)) for accurate signature.

---

## FacilityViewSet

```
FacilityViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## IXLanPrefixViewSet

```
IXLanPrefixViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## IXLanViewSet

```
IXLanViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## InternetExchangeFacilityViewSet

```
InternetExchangeFacilityViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## InternetExchangeMixin

```
InternetExchangeMixin(builtins.object)
```

Custom api endpoints for the internet exchange
object, exposed to api/ix/{id}/{action}


### Methods

#### request_ixf_import
`def request_ixf_import(self, request, *args, **kwargs)`

Allows managers of an ix to request an ix-f import
#779

---

## InternetExchangeViewSet

```
InternetExchangeViewSet(peeringdb_server.rest.InternetExchangeMixin, peeringdb_server.rest.ModelViewSet)
```

Custom api endpoints for the internet exchange
object, exposed to api/ix/{id}/{action}


## ModelViewSet

```
ModelViewSet(rest_framework.viewsets.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


### Methods

#### get_queryset
`def get_queryset(self)`

Prepare the queryset

---
#### partial_update
`def partial_update(self, request, *args, **kwargs)`

PATCH (partial update) is currently disabled

---
#### require_data
`def require_data(self, request)`

Test that the request contains data in its body that
can be parsed to the required format (json) and is not
empty

Will raise DataParseException error if request payload could
not be parsed

Will raise DataMissingException error if request payload is
missing or was parsed to an empty object

---

## NetworkContactViewSet

```
NetworkContactViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## NetworkFacilityViewSet

```
NetworkFacilityViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## NetworkIXLanViewSet

```
NetworkIXLanViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## NetworkViewSet

```
NetworkViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## OrganizationViewSet

```
OrganizationViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class
This should probably be moved to a common lib ?


## RestRouter

```
RestRouter(rest_framework.routers.DefaultRouter)
```

The default router extends the SimpleRouter, but also adds in a default
API root view, and adds format suffix patterns to the URLs.


### Methods

#### \__init__
`def __init__(self, trailing_slash=False)`

Initialize self.  See help(type(self)) for accurate signature.

---

## client_check

```
client_check(builtins.object)
```

decorator that can be attached to rest viewset responses and will
generate an error response if the requesting peeringdb client
is running a client or backend version that is incompatible with
the server

compatibilty is controlled via facsimile during deploy and can
be configured in env.misc.api.compat


### Methods

#### \__call__
`def __call__(self, fn)`

Call self as a function.

---
#### \__init__
`def __init__(self)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### backend_max_version
`def backend_max_version(self, backend)`

return the max supported version for the specified backend

---
#### backend_min_version
`def backend_min_version(self, backend)`

return the min supported version for the specified backend

---
#### client_info
`def client_info(self, request)`

parse the useragent in the request and return client version
info if possible.

any connecting client that is NOT the peeringdb client will currently
return an empty dict and not compatibility checking will be done

---
#### compat_check
`def compat_check(self, request)`

Check if the connecting client is compatible with the api

This is currently only sensible when the request is made through
the official peeringdb-py client, any other client will be
passed through without checks

On incompatibility a ValueError is raised

---
#### version_pad
`def version_pad(self, version)`

take a semantic version tuple and zero pad to dev version

---
#### version_string
`def version_string(self, version)`

take a semantic version tuple and turn into a "." delimited string

---
#### version_tuple
`def version_tuple(self, str_version)`

take a semantic version string and turn into a tuple

---
