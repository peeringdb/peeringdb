Generated from search.py on 2022-02-07 09:42:46.681191

# peeringdb_server.search

Search implementation used for the peeringdb top search bar, name
searches through the api `name_search` filter, as well as advanced
search functionality.

Search logic is handled by django-haystack and whoosh.

Refer to search_indexes.py for search index definition.

# Functions
---

## search
`def search(term, autocomplete=False)`

Search searchable objects (ixp, network, facility ...) by term.

Returns result dict.

---