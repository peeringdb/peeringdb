Generated from search_indexes.py on 2025-02-11 10:26:48.481231

# peeringdb_server.search_indexes

Defines django-haystack search indexes.

# Classes
---

## CampusIndex

```
CampusIndex(peeringdb_server.search_indexes.MainEntity, haystack.constants.Indexable)
```

Search index for org, net, ix and fac entities.


### Methods

#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---

## CarrierIndex

```
CarrierIndex(peeringdb_server.search_indexes.MainEntity, haystack.constants.Indexable)
```

Search index for org, net, ix and fac entities.


### Methods

#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---

## EntityIndex

```
EntityIndex(haystack.indexes.SearchIndex)
```

Search index for org, net, ix and fac entities.


### Methods

#### build_queryset
`def build_queryset(self, using=None, start_date=None, end_date=None)`

Get the default QuerySet to index when doing an index update.

Subclasses can override this method to take into account related
model modification times.

The default is to use ``SearchIndex.index_queryset`` and filter
based on ``SearchIndex.get_updated_field``

---
#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---
#### get_updated_field
`def get_updated_field(self)`

Use this field to determine object age. This
is required for the --age parameter to function
in the update_index command.

---
#### prepare
`def prepare(self, obj)`

Fetches and adds/alters data before indexing.

---

## FacilityIndex

```
FacilityIndex(peeringdb_server.search_indexes.MainEntity, haystack.constants.Indexable)
```

Search index for org, net, ix and fac entities.


### Methods

#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---

## IXLanPrefixIndex

```
IXLanPrefixIndex(peeringdb_server.search_indexes.EntityIndex, haystack.constants.Indexable)
```

Search index for org, net, ix and fac entities.


### Methods

#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---

## InternetExchangeIndex

```
InternetExchangeIndex(peeringdb_server.search_indexes.MainEntity, haystack.constants.Indexable)
```

Search index for org, net, ix and fac entities.


### Methods

#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---

## MainEntity

```
MainEntity(peeringdb_server.search_indexes.EntityIndex)
```

Search index for org, net, ix and fac entities.


### Methods

#### prepare
`def prepare(self, obj)`

Fetches and adds/alters data before indexing.

---

## NetworkIXLanIndex

```
NetworkIXLanIndex(peeringdb_server.search_indexes.EntityIndex, haystack.constants.Indexable)
```

Search index for org, net, ix and fac entities.


### Methods

#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---

## NetworkIndex

```
NetworkIndex(peeringdb_server.search_indexes.MainEntity, haystack.constants.Indexable)
```

Search index for org, net, ix and fac entities.


### Methods

#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---

## OrganizationIndex

```
OrganizationIndex(peeringdb_server.search_indexes.MainEntity, haystack.constants.Indexable)
```

Search index for org, net, ix and fac entities.


### Methods

#### get_model
`def get_model(self)`

Should return the ``Model`` class (not an instance) that the rest of the
``SearchIndex`` should use.

This method is required & you must override it to return the correct class.

---
