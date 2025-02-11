Generated from rest.py on 2025-02-11 10:26:48.481231

# peeringdb_server.rest

REST API view definitions.

REST API path routing.

REST API permission checking (facilitated through django-grainy).

REST API error handling.

REST API list filtering logic.

peeringdb-py client compatibility checking.

The peeringdb REST API is implemented through django-rest-framework.

# Functions
---

## model_view_set
`def model_view_set(model, methods=None, mixins=None)`

Shortcut for peeringdb models to generate viewset and register in the API urls.

---
## view_self_entity
`def view_self_entity(request, args, kwargs)`

This API View redirect self entity API to the corresponding url

---
# Classes
---

## ASSetViewSet

```
ASSetViewSet(peeringdb_server.rest.ReadOnlyMixin, rest_framework.viewsets.ModelViewSet)
```

AS-SET endpoint.

List all as sets mapped by asn.


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

## BasicAuthMFABlockWrite

```
BasicAuthMFABlockWrite(rest_framework.permissions.BasePermission)
```

When an account has MFA enabled and basic-auth is used
to authenticate the account for a write operation on the API
block the request.


### Methods

#### has_permission
`def has_permission(self, request, view)`

Return `True` if permission is granted, `False` otherwise.

---

## CampusFacilityMixin

```
CampusFacilityMixin(builtins.object)
```

Custom API endpoints for the campus-facility
object, exposed to /api/campus/{campus_id}/add-facility/{fac_id}
and /api/campus/{campus_id}/remove-facility/{fac_id}


### Methods

#### add_facility
`def add_facility(self, request, args, kwargs)`

Allows the org to approve a campus listing at their facility

---
#### remove_facility
`def remove_facility(self, request, args, kwargs)`

Allows the org to reject a campus listing at their facility

---

## CampusViewSet

```
CampusViewSet(peeringdb_server.rest.CampusFacilityMixin, peeringdb_server.rest.ModelViewSet)
```

Custom API endpoints for the campus-facility
object, exposed to /api/campus/{campus_id}/add-facility/{fac_id}
and /api/campus/{campus_id}/remove-facility/{fac_id}


## CarrierFacilityMixin

```
CarrierFacilityMixin(builtins.object)
```

Custom API endpoints for the carrier-facility
object, exposed to api/carrierfac/{id}/{action}


### Methods

#### approve
`def approve(self, request, pk, args, kwargs)`

Allows the org to approve a carrier listing at their facility

---
#### reject
`def reject(self, request, pk, args, kwargs)`

Allows the org to reject a carrier listing at their facility

---

## CarrierFacilityViewSet

```
CarrierFacilityViewSet(peeringdb_server.rest.CarrierFacilityMixin, peeringdb_server.rest.ModelViewSet)
```

Custom API endpoints for the carrier-facility
object, exposed to api/carrierfac/{id}/{action}


## CarrierViewSet

```
CarrierViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


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
Raised when the json data sent with a POST, PUT or PATCH
request is missing.


### Methods

#### \__init__
`def __init__(self, method)`

Initialize self.  See help(type(self)) for accurate signature.

---

## DataParseException

```
DataParseException(peeringdb_server.rest.DataException)
```

Raised when the json data sent with a POST, PUT or PATCH
request could not be parsed.


### Methods

#### \__init__
`def __init__(self, method, exc)`

Initialize self.  See help(type(self)) for accurate signature.

---

## FacilityViewSet

```
FacilityViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


## IXLanPrefixViewSet

```
IXLanPrefixViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


## IXLanViewSet

```
IXLanViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


## InactiveKeyBlock

```
InactiveKeyBlock(rest_framework.permissions.BasePermission)
```

When an OrganizationAPIKey or a UserAPIKey has status `inactive`
requests made with such keys should be blocked


### Methods

#### has_permission
`def has_permission(self, request, view)`

Return `True` if permission is granted, `False` otherwise.

---

## InactiveKeyException

```
InactiveKeyException(rest_framework.exceptions.APIException)
```

Raised on api authentications with inactive api keys


## InternetExchangeFacilityViewSet

```
InternetExchangeFacilityViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


## InternetExchangeMixin

```
InternetExchangeMixin(builtins.object)
```

Custom API endpoints for the internet exchange
object, exposed to api/ix/{id}/{action}


### Methods

#### request_ixf_import
`def request_ixf_import(self, request, args, kwargs)`

Allows managers of an ix to request an IX-F import.
(#779)

---

## InternetExchangeViewSet

```
InternetExchangeViewSet(peeringdb_server.rest.InternetExchangeMixin, peeringdb_server.rest.ModelViewSet)
```

Custom API endpoints for the internet exchange
object, exposed to api/ix/{id}/{action}


## ModelViewSet

```
ModelViewSet(rest_framework.viewsets.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


### Methods

#### get_queryset
`def get_queryset(self)`

Prepare the queryset.

---
#### partial_update
`def partial_update(self, request, *args, **kwargs)`

PATCH (partial update) is currently disabled.

---
#### require_data
`def require_data(self, request)`

Test that the request contains data in its body that
can be parsed to the required format (json) and is not
empty.

Will raise DataParseException error if request payload could
not be parsed.

Will raise DataMissingException error if request payload is
missing or was parsed to an empty object.

---

## NetworkContactViewSet

```
NetworkContactViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


## NetworkFacilityViewSet

```
NetworkFacilityViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


## NetworkIXLanMixin

```
NetworkIXLanMixin(builtins.object)
```

Custom API endpoint for setting or unsetting the net_side and ix_side values on a NetworkIXLan object.
Exposed at /api/netixlan/{id}/set-net-side and /api/netixlan/{id}/set-ix-side (POST).

These endpoints allow networks and exchanges to set (or unset) the net_side and ix_side values
on a NetworkIXLan by providing a valid fac_id in the payload, or unset by passing null.

Paths:
/api/netixlan/{id}/set-net-side:
/api/netixlan/{id}/set-ix-side:
POST:
    Summary: Set or unset the net_side or ix_side value on a NetworkIXLan
    Description: Allows networks or exchanges to update the corresponding side values.
    Parameters:
        - id: The ID of the NetworkIXLan to update (in path, required, integer)
    RequestBody:
        - fac_id: The ID of the Facility to set as net_side or ix_side. Null to unset (integer or null, required)


### Methods

#### add_ix_side
`def add_ix_side(self, request, args, kwargs)`

Set or unset the ix_side value on a NetworkIXLan.
This method sets a facility as the ix_side based on the facility ID from the request payload.
If fac_id is null, the ix_side will be unset. Permissions are checked before saving changes.

---
#### add_net_side
`def add_net_side(self, request, args, kwargs)`

Set or unset the net_side value on a NetworkIXLan.
This method sets a facility as the net_side based on the facility ID from the request payload.
If fac_id is null, the net_side will be unset. Permissions are checked before saving changes.

---

## NetworkIXLanViewSet

```
NetworkIXLanViewSet(peeringdb_server.rest.NetworkIXLanMixin, peeringdb_server.rest.ModelViewSet)
```

Custom API endpoint for setting or unsetting the net_side and ix_side values on a NetworkIXLan object.
Exposed at /api/netixlan/{id}/set-net-side and /api/netixlan/{id}/set-ix-side (POST).

These endpoints allow networks and exchanges to set (or unset) the net_side and ix_side values
on a NetworkIXLan by providing a valid fac_id in the payload, or unset by passing null.

Paths:
/api/netixlan/{id}/set-net-side:
/api/netixlan/{id}/set-ix-side:
POST:
    Summary: Set or unset the net_side or ix_side value on a NetworkIXLan
    Description: Allows networks or exchanges to update the corresponding side values.
    Parameters:
        - id: The ID of the NetworkIXLan to update (in path, required, integer)
    RequestBody:
        - fac_id: The ID of the Facility to set as net_side or ix_side. Null to unset (integer or null, required)


## NetworkViewSet

```
NetworkViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
This should probably be moved to a common lib ?


## OrganizationViewSet

```
OrganizationViewSet(peeringdb_server.rest.ModelViewSet)
```

Generic ModelViewSet Base Class.
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

## UnlimitedIfNoPagePagination

```
UnlimitedIfNoPagePagination(rest_framework.pagination.PageNumberPagination)
```

A simple page number based style that supports page numbers as
query parameters. For example:

http://api.example.org/accounts/?page=4
http://api.example.org/accounts/?page=4&page_size=100


### Methods

#### paginate_queryset
`def paginate_queryset(self, queryset, request, view=None)`

Paginate a queryset if required, either returning a
page object, or `None` if pagination is not configured for this view.

---

## client_check

```
client_check(builtins.object)
```

Decorator that can be attached to rest viewset responses and will
generate an error response if the requesting peeringdb client
is running a client or backend version that is incompatible with
the server.

Compatibilty is controlled via facsimile during deploy and can
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

Return the max supported version for the specified backend.

---
#### backend_min_version
`def backend_min_version(self, backend)`

Return the min supported version for the specified backend.

---
#### client_info
`def client_info(self, request)`

Parse the useragent in the request and return client version
info if possible.

Any connecting client that is NOT the peeringdb client will currently
return an empty dict and not compatibility checking will be done.

---
#### compat_check
`def compat_check(self, request)`

Check if the connecting client is compatible with the API.

This is currently only sensible when the request is made through
the official peeringdb-py client, any other client will be
passed through without checks.

On incompatibility a ValueError is raised.

---
#### version_pad
`def version_pad(self, version)`

Take a semantic version tuple and zero pad to dev version.

---
#### version_string
`def version_string(self, version)`

Take a semantic version tuple and turn into a "." delimited string.

---
#### version_tuple
`def version_tuple(self, str_version)`

Take a semantic version string and turn into a tuple.

---
