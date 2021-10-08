Generated from search.py on 2021-10-06 18:04:54.501582

# peeringdb_server.search

Search implementation used for the peeringdb top search bar, as well as name searches through
the api `name_search` filter, as well as advanced search name field searches.

Search logic is handled by django-haystack and whoosh.

Refer to search_indexes.py for search index definition.

# Functions
---

## search
`def search(term, autocomplete=False)`

Search searchable objects (ixp, network, facility ...) by term

Returns result dict

---