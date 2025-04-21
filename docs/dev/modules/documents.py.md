Generated from documents.py on 2025-04-21 14:27:07.752913

# peeringdb_server.documents

# Functions
---

## is_valid_latitude
`def is_valid_latitude(lat)`

Validates a latitude.

---
## is_valid_longitude
`def is_valid_longitude(long)`

Validates a longitude.

---
# Classes
---

## CampusDocument

```
CampusDocument(peeringdb_server.documents.GeocodeMixin, django_elasticsearch_dsl.documents.DocType)
```

Cleans up invalid lat/lng values beforee passing
them to the geo code field


## CarrierDocument

```
CarrierDocument(peeringdb_server.documents.GeocodeMixin, django_elasticsearch_dsl.documents.DocType)
```

Cleans up invalid lat/lng values beforee passing
them to the geo code field


## FacilityDocument

```
FacilityDocument(peeringdb_server.documents.GeocodeMixin, django_elasticsearch_dsl.documents.DocType)
```

Cleans up invalid lat/lng values beforee passing
them to the geo code field


## GeocodeMixin

```
GeocodeMixin(peeringdb_server.documents.StatusMixin)
```

Cleans up invalid lat/lng values beforee passing
them to the geo code field


### Methods

#### cached_facilities
`def cached_facilities(self, instance)`

Caches all facilties for network or internet exchange relations.
This is to speed up processing of those documents as they will
need to collect all facilities associated with the object to determine
geo coordinates and country and state

---
#### prepare_country
`def prepare_country(self, instance)`

Prepares country for the country field

For Facility and organization this will read country from the object itself

For Network and internet exchange this will return a list of country codes
for all facilities associated with the object

---
#### prepare_geocode_coordinates
`def prepare_geocode_coordinates(self, instance)`

Prepares geo coordinates for the geocode_coordinates field

For Facility and organization this will read lat/lng from the object itself

For Network and internet exchange this will return lists of coordinates
for all facilities associated with the object

---
#### prepare_state
`def prepare_state(self, instance)`

Prepares state for the state field

For Facility and organization this will read state from the object itself

For Network and internet exchange this will return a list of states
for all facilities associated with the object

---

## InternetExchangeDocument

```
InternetExchangeDocument(peeringdb_server.documents.GeocodeMixin, peeringdb_server.documents.IpAddressMixin, django_elasticsearch_dsl.documents.DocType)
```

Cleans up invalid lat/lng values beforee passing
them to the geo code field


## MultipleChoiceKeywordField

```
MultipleChoiceKeywordField(django_elasticsearch_dsl.fields.KeywordField)
```

:arg boost:
:arg eager_global_ordinals:
:arg index:
:arg index_options:
:arg script:
:arg on_script_error:
:arg normalizer:
:arg norms:
:arg null_value:
:arg similarity:
:arg split_queries_on_whitespace:
:arg time_series_dimension: For internal use by Elastic only. Marks
    the field as a time series dimension. Defaults to false.
:arg doc_values:
:arg copy_to:
:arg store:
:arg meta: Metadata about the field.
:arg properties:
:arg ignore_above:
:arg dynamic:
:arg fields:
:arg synthetic_source_keep:


### Methods

#### get_value_from_instance
`def get_value_from_instance(self, instance, field_value_to_ignore=None)`

Given an model instance to index with ES, return the value that
should be put into ES for this field.

---

## NetworkDocument

```
NetworkDocument(peeringdb_server.documents.GeocodeMixin, peeringdb_server.documents.IpAddressMixin, django_elasticsearch_dsl.documents.DocType)
```

Cleans up invalid lat/lng values beforee passing
them to the geo code field


## OrganizationDocument

```
OrganizationDocument(peeringdb_server.documents.GeocodeMixin, django_elasticsearch_dsl.documents.DocType)
```

Cleans up invalid lat/lng values beforee passing
them to the geo code field


## StatusMixin

```
StatusMixin(builtins.object)
```

Ensures only objects with status=ok are indexed
and deleted from the index if status is no longer ok


### Methods

#### update
`def update(self, thing, **kwargs)`

Updates the document with the given kwargs.

---
