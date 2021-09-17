## Methods of search

PeeringDB has 3 (2) areas where searches are processed

### 1. The quick search

This is the search that happens throught the top search bar on the PeeringDB website.

This search is backed by [django-haystack](https://django-haystack.readthedocs.io/en/master/) using the [whoosh](https://whoosh.readthedocs.io/en/latest/intro.html) backend.

Search-indexes and logic for this can be found in `peeringdb_server/search_indexes.py` and `peeringdb_server/search.py`

### 2. REST API filtering

REST API filtering happens when filter parameters are past to REST API list retrievals.

This is almost a straight pass through to django query set filters (after some sanitizing of course)

Most querying logic for this is defined in `rest.py` 

Note that there is some extra effort involved for more intricate query filters, such as relationship queries or customized queries like the `whereis` filter for `ixpfx`

These more complex querying behaviours should be implemented in `serializers.py` through the `prepare_query` method on the serializer.

#### `name_search` filter

The `name_search` filter will make use of [django-haystack](https://django-haystack.readthedocs.io/en/master/)

### 3. Advanced Search

The advanced-search UI is wired directly to the REST API, so whatever the REST api is capable of the advanced-search UI can make use of.

New form elements should be added as necessary.
