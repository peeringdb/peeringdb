Generated from serializers.py on 2025-02-11 10:26:48.481231

# peeringdb_server.serializers

REST API Serializer definitions.
REST API POST / PUT data validators.

New serializers should extend ModelSerializer class, which is a custom extension
of django-rest-framework's ModelSerializer.

Custom ModelSerializer implements logic for the expansion of relationships driven by the `depth` url parameter. The depth parameter indicates how many objects to recurse into.

Special api filtering implementation should be done through the `prepare_query`
method.

# Functions
---

## nested
`def nested(serializer, exclude=[], getter=None, through=None, **kwargs)`

Use this function to create nested serializer fields. Making
depth work otherwise while fetching related lists via handlref remains a mystery.

---
## queryable_field_xl
`def queryable_field_xl(fld)`

Translate <fld>_id into <fld> and also translate fac and net queries into "facility"
and "network" queries.

FIXME: should be renamed on model schema.

---
# Classes
---

## ASSetSerializer

```
ASSetSerializer(peeringdb_server.serializers.NetworkSerializer)
```

Serializer for peeringdb_server.models.Network

Possible realtionship queries:
  - org_id, handled by serializer
  - ix_id, handled by prepare_query
  - ixlan_id, handled by prepare_query
  - netfac_id, handled by prepare_query
  - fac_id, handled by prepare_query


## AddressSerializer

```
AddressSerializer(rest_framework.serializers.ModelSerializer)
```

A `ModelSerializer` is just a regular `Serializer`, except that:

* A set of default fields are automatically populated.
* A set of default validators are automatically populated.
* Default `.create()` and `.update()` implementations are provided.

The process of automatically determining a set of serializer fields
based on the model fields is reasonably complex, but you almost certainly
don't need to dig into the implementation.

If the `ModelSerializer` class *doesn't* generate the set of fields that
you need you should either declare the extra/differing fields explicitly on
the serializer class, or simply use a `Serializer` class.


## AsnRdapValidator

```
AsnRdapValidator(builtins.object)
```

A validator that queries rdap entries for the provided value (Asn)
and will fail if no matching asn is found.


### Methods

#### \__call__
`def __call__(self, attrs, serializer_field)`

Call self as a function.

---
#### \__init__
`def __init__(self, field=asn, message=None, methods=None)`

Initialize self.  See help(type(self)) for accurate signature.

---

## CampusSerializer

```
CampusSerializer(peeringdb_server.serializers.SpatialSearchMixin, peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.Campus


### Class Methods

#### prepare_query
`def prepare_query(cls, qset, **kwargs)`

Allows filtering by indirect relationships.

Currently supports: facility

---

### Methods

#### to_representation
`def to_representation(self, data)`

Object instance -> Dict of primitive datatypes.

---

## CarrierFacilitySerializer

```
CarrierFacilitySerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.CarrierFacility


## CarrierSerializer

```
CarrierSerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.Carrier


### Class Methods

#### prepare_query
`def prepare_query(cls, qset, **kwargs)`

Allows filtering by indirect relationships, similar to NetworkSerializer.

---

### Methods

#### to_representation
`def to_representation(self, data)`

Object instance -> Dict of primitive datatypes.

---

## FacilitySerializer

```
FacilitySerializer(peeringdb_server.serializers.SpatialSearchMixin, peeringdb_server.serializers.GeocodeSerializerMixin, peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.Facility

Possible relationship queries:
  - net_id, handled by prepare_query
  - ix_id, handled by prepare_query
  - org_id, handled by serializer
  - org_name, hndled by prepare_query


### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### to_internal_value
`def to_internal_value(self, data)`

Dict of native values <- Dict of primitive datatypes.

---
#### to_representation
`def to_representation(self, instance)`

Object instance -> Dict of primitive datatypes.

---
#### update
`def update(self, instance, validated_data)`

When updating a geo-enabled object,
update the model first
and then normalize the geofields.

---

## FieldMethodValidator

```
FieldMethodValidator(builtins.object)
```

A validator that will only allow a field to be set for certain
methods.


### Methods

#### \__call__
`def __call__(self, attrs)`

Call self as a function.

---
#### \__init__
`def __init__(self, field, methods, message=None)`

Initialize self.  See help(type(self)) for accurate signature.

---

## GeocodeSerializerMixin

```
GeocodeSerializerMixin(builtins.object)
```

Override create() and update() method of serializer
to normalize the location against the Google Maps Geocode API
and resave the model instance with normalized address fields.

Can only be used if the model includes the GeocodeBaseMixin.


### Class Methods

#### normalize_state_lookup
`def normalize_state_lookup(cls, filters)`

for non-distance search the specifies state and country
attempt to normalize the state field using melissa global address
lookup. (#1079)

this does NOT need to be done on distance search since distance search
already normalizes the search to geo-coordinates using melissa.

---

### Methods

#### _add_meta_information
`def _add_meta_information(self, metadata)`

Adds a dictionary of metadata to the "meta" field of the API
request, so that it ends up in the API response.

---
#### _geosync_information_present
`def _geosync_information_present(self, instance, validated_data)`

Determine if there is enough address information
to necessitate a geosync attempt.

---
#### _need_geosync
`def _need_geosync(self, instance, validated_data)`

Determine if any geofields that have changed need normalization.
Returns False if the only change is that fields have been deleted.

---
#### handle_geo_error
`def handle_geo_error(self, exc, instance)`

Issue #939: In the event that there is an error in geovalidating
the address (including address not found), a warning is returned in
the "meta" field of the response and null the latitude and
longitude on the instance.

---
#### needs_address_suggestion
`def needs_address_suggestion(self, suggested_address, instance)`

Issue #940: If the geovalidated address meaningfully differs
from the address the user provided, we return True to signal
a address suggestion should be provided to the user.

---
#### update
`def update(self, instance, validated_data, ignore_geosync=False)`

When updating a geo-enabled object,
update the model first
and then normalize the geofields.

---
#### validate_floor
`def validate_floor(self, floor)`

As per #1482 the floor field is being deprecated
and only empty values are allowed.

---

## IXLanPrefixSerializer

```
IXLanPrefixSerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.IXLanPrefix

Possible relationship queries:
  - ixlan_id, handled by serializer
  - ix_id, handled by prepare_query


## IXLanSerializer

```
IXLanSerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.IXLan

Possible relationship queries:
  - ix_id, handled by serializer


## InternetExchangeFacilitySerializer

```
InternetExchangeFacilitySerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.InternetExchangeFacility

Possible relationship queries:
  - fac_id, handled by serializer
  - ix_id, handled by serializer


## InternetExchangeSerializer

```
InternetExchangeSerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.InternetExchange

Possible relationship queries:
  - org_id, handled by serializer
  - fac_id, handled by prepare_query
  - net_id, handled by prepare_query
  - ixfac_id, handled by prepare_query
  - ixlan_id, handled by prepare_query


### Methods

#### create
`def create(self, validated_data)`

Entities created via the API should go into the verification
queue with status pending if they are in the QUEUE_ENABLED
list or suggest is True.

---
#### to_representation
`def to_representation(self, data)`

Object instance -> Dict of primitive datatypes.

---

## ModelSerializer

```
ModelSerializer(rest_framework.serializers.ModelSerializer)
```

ModelSerializer that provides DB API with custom params.

Main problem with doing field ops here is data is already fetched, so while
it's fine for single columns, it doesn't help on speed for fk relationships.
However data is not yet serialized so there may be some gain.

Using custom method fields to introspect doesn't work at all, because
they're not called until they're serialized, and then are called once per row,

for example
test_depth = serializers.SerializerMethodField('check_for_fk')
def check_for_fk(self, obj):
    print "check ", type(obj)

class Meta:
    fields = [
        'test_depth',
        ...

Best bet so far looks like overloading the single object GET in the model
view set, and adding on the relationships, but need to GET to GET the fields
defined yet not included in the query, may have to rewrite the base class,
which would mean talking to the dev and committing back or we'll have this problem
every update.

After testing, the time is all in serialization and transfer, so culling
related here should be fine.

arg[0] is a queryset, but seems to have already been evaluated

Addition Query arguments:
`fields` comma separated list of only fields to display

    could cull the default list down quite a bit by default and make people ask explicitly for them
    self.Meta.default_fields, but I'm not sure it matters, more testing


### Instanced Attributes

These attributes / properties will be available on instances of the class

- current_depth (`@property`): None
- depth (`@property`): None
- in_list (`@property`): None
- is_root (`@property`): None

### Class Methods

#### default_depth
`def default_depth(cls, is_list)`

Return default depth according to whether resultset is list or single GET.

---
#### depth_from_request
`def depth_from_request(cls, request, is_list)`

Derive aproporiate depth parameter from request. Max and default depth will vary depending on whether
result set is a list or single object.

This will return the depth specified in the request or the next best
possible depth.

---
#### is_unique_query
`def is_unique_query(cls, request)`

Check if the request parameters are expected to return a unique entity.

---
#### max_depth
`def max_depth(cls, is_list)`

Return max depth according to whether resultset is list or single GET.

---
#### prefetch_related
`def prefetch_related(cls, qset, request, prefetch=None, related=None, nested=, depth=None, is_list=False, single=None, selective=None)`

Prefetch related sets according to depth specified in the request.

Prefetched set data will be located off the instances in an attribute
called "<tag>_set_active_prefetched" where tag is the handleref tag
of the objects the set will be holding.

---
#### queryable_relations
`def queryable_relations(self)`

Returns a list of all second level queryable relation fields.

---

### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### _handle_netixlan_reclaim
`def _handle_netixlan_reclaim(self, ipaddr4, ipaddr6)`

Handles logic of reclaiming ipaddresses from soft-deleted
netixlans in case where ipv4 and ipv6 are on separate netixlan objects

Will raise a django DoesNotExist error if either ipaddress does not
exist on a deleted netixlan

---
#### _render_social_media
`def _render_social_media(self, output)`

Until v3 the `website` field still drives the website url of the object
but we can start rendering in the `social_media` field as well.

---
#### create
`def create(self, validated_data, auto_approve=False, suggest=False)`

Entities created via the API should go into the verification
queue with status pending if they are in the QUEUE_ENABLED
list or suggest is True.

---
#### finalize_create
`def finalize_create(self, request)`

This will be called on the end of POST request to this serializer.

---
#### finalize_delete
`def finalize_delete(self, request)`

This will be called on the end of DELETE request to this serializer.

---
#### finalize_update
`def finalize_update(self, request)`

This will be called on the end of PUT request to this serializer.

---
#### run_validation
`def run_validation(self, data=<class 'rest_framework.fields.empty'>)`

Custom validation handling.

Will run the vanilla django-rest-framework validation but
wrap it with logic to handle unique constraint errors to
restore soft-deleted objects that are blocking a save on basis
of a unique constraint violation.

---
#### save
`def save(self, **kwargs)`

Entities created via API that have status pending should
attempt to store which user created the item in the
verification queue instance.

---
#### to_representation
`def to_representation(self, data)`

Object instance -> Dict of primitive datatypes.

---

## NetworkContactSerializer

```
NetworkContactSerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.NetworkContact

Possible relationship queries:
  - net_id, handled by serializer


### Methods

#### to_representation
`def to_representation(self, data)`

Object instance -> Dict of primitive datatypes.

---

## NetworkFacilitySerializer

```
NetworkFacilitySerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.NetworkFacility

Possible relationship queries:
  - fac_id, handled by serializer
  - net_id, handled by seralizers


### Methods

#### run_validation
`def run_validation(self, data=<class 'rest_framework.fields.empty'>)`

Custom validation handling.

Will run the vanilla django-rest-framework validation but
wrap it with logic to handle unique constraint errors to
restore soft-deleted objects that are blocking a save on basis
of a unique constraint violation.

---

## NetworkIXLanSerializer

```
NetworkIXLanSerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.NetworkIXLan

Possible relationship queries:
  - net_id, handled by serializer
  - ixlan_id, handled by serializer
  - ix_id, handled by prepare_query
  - ixlan_id, handled by serializer
  - ix_side_id, handled by serializer


### Class Methods

#### prepare_query
`def prepare_query(cls, qset, **kwargs)`

Allows filtering by indirect relationships.

Currently supports: ix_id

---

### Methods

#### _validate_network_contact
`def _validate_network_contact(self, data)`

Per github ticket #826, a Netixlan is only allowed to be added
if there is a network contact that the AC can contact to resolve issues.

---
#### run_validation
`def run_validation(self, data=<class 'rest_framework.fields.empty'>)`

Custom validation handling.

Will run the vanilla django-rest-framework validation but
wrap it with logic to handle unique constraint errors to
restore soft-deleted objects that are blocking a save on basis
of a unique constraint violation.

---

## NetworkSerializer

```
NetworkSerializer(peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.Network

Possible realtionship queries:
  - org_id, handled by serializer
  - ix_id, handled by prepare_query
  - ixlan_id, handled by prepare_query
  - netfac_id, handled by prepare_query
  - fac_id, handled by prepare_query


### Class Methods

#### prepare_query
`def prepare_query(cls, qset, **kwargs)`

Allows filtering by indirect relationships.

Currently supports: ixlan_id, ix_id, netixlan_id, netfac_id, fac_id

---

### Methods

#### create
`def create(self, validated_data)`

Entities created via the API should go into the verification
queue with status pending if they are in the QUEUE_ENABLED
list or suggest is True.

---
#### finalize_create
`def finalize_create(self, request)`

This will be called on the end of POST request to this serializer.

---
#### get_rir_status
`def get_rir_status(self, inst)`

Normalized RIR status for network

---
#### to_internal_value
`def to_internal_value(self, data)`

Dict of native values <- Dict of primitive datatypes.

---
#### to_representation
`def to_representation(self, data)`

Object instance -> Dict of primitive datatypes.

---

## OrganizationSerializer

```
OrganizationSerializer(peeringdb_server.serializers.SpatialSearchMixin, peeringdb_server.serializers.GeocodeSerializerMixin, peeringdb_server.serializers.ModelSerializer)
```

Serializer for peeringdb_server.models.Organization


### Class Methods

#### prepare_query
`def prepare_query(cls, qset, **kwargs)`

Add special filter options

Currently supports:

- asn: filter by network asn

---

## RequestAwareListSerializer

```
RequestAwareListSerializer(rest_framework.serializers.ListSerializer)
```

A List serializer that has access to the originating
request.

Used as the list serializer class for all nested lists
so time filters can be applied to the resultset if the _ctf param
is set in the request.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- request (`@property`): Retrieve the request from the root serializer.

### Methods

#### to_representation
`def to_representation(self, data)`

List of object instances -> List of dicts of primitive datatypes.

---

## RequiredForMethodValidator

```
RequiredForMethodValidator(builtins.object)
```

A validator that makes a field required for certain
methods.


### Methods

#### \__call__
`def __call__(self, attrs, serializer_field)`

Call self as a function.

---
#### \__init__
`def __init__(self, field, methods=['POST', 'PUT'], message=None)`

Initialize self.  See help(type(self)) for accurate signature.

---

## SaneIntegerField

```
SaneIntegerField(rest_framework.fields.IntegerField)
```

Integer field that renders null values to 0.


### Methods

#### get_attribute
`def get_attribute(self, instance)`

Given the *outgoing* object instance, return the primitive value
that should be used for this field.

---

## SocialMediaSerializer

```
SocialMediaSerializer(rest_framework.serializers.Serializer)
```

Renders the social_media property


## SoftRequiredValidator

```
SoftRequiredValidator(builtins.object)
```

A validator that allows us to require that at least
one of the specified fields is set.


### Methods

#### \__call__
`def __call__(self, attrs)`

Call self as a function.

---
#### \__init__
`def __init__(self, fields, message=None)`

Initialize self.  See help(type(self)) for accurate signature.

---

## SpatialSearchMixin

```
SpatialSearchMixin(builtins.object)
```

Mixin that enables spatial search for a model
with address fields.

At minimum, a model needs a country and city field, but
address1, address2, zipcode and state are also considered
if they exist.


### Class Methods

#### convert_to_spatial_search
`def convert_to_spatial_search(cls, filters)`

Checks if the a single city and country are provided
in the query and will convert the query to a distance search.

Order of operations:

1. check if `city` and `country` are provided
    a. This is also valid if `city__in` or `country__in` contain
       a single value
    b. if country is not provided, attempt to retrieve it from
       the google geocode api result
2. retrieve the city bounding box via google geocode
3. set distance on the filters based on the bounding box, turning
      the query into a spatial distance search.

---
