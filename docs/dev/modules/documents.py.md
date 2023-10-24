Generated from documents.py on 2023-08-15 16:04:08.595120

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
InternetExchangeDocument(peeringdb_server.documents.GeocodeMixin, django_elasticsearch_dsl.documents.DocType)
```

Cleans up invalid lat/lng values beforee passing
them to the geo code field


## NetworkDocument

```
NetworkDocument(peeringdb_server.documents.GeocodeMixin, django_elasticsearch_dsl.documents.DocType)
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
