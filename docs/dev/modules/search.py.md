Generated from search.py on 2024-11-12 18:19:35.039193

# peeringdb_server.search

Search implementation used for the peeringdb top search bar, name
searches through the api `name_search` filter, as well as advanced
search functionality.

Search logic is handled by django-haystack and whoosh.

Refer to search_indexes.py for search index definition.

# Functions
---

## add_and_between_keywords
`def add_and_between_keywords(keywords)`

Add 'AND' between keywords in the list that are neither 'AND' nor 'OR'.

This function iterates through a list of keywords and appends 'AND'
between any consecutive keywords that are not 'AND' or 'OR'.

Args:
    keywords (list of str): A list of keywords to process.

Returns:
    list of str: A new list with 'AND' inserted between applicable keywords.

---
## escape_query_string
`def escape_query_string(query_string)`

Escape special characters in a query string to make it safe for Elasticsearch queries.

Args:
query_string (str): The query string to be escaped.

Returns:
str: Escaped query string.

---
## is_valid_latitude
`def is_valid_latitude(lat)`

Validates a latitude.

---
## is_valid_longitude
`def is_valid_longitude(long)`

Validates a longitude.

---
## order_results_alphabetically
`def order_results_alphabetically(result, search_terms, original_query=)`

Order the search results alphabetically and put the exact case-insensitive matches in front with special handling for OR queries.

Args:
- result: A dictionary containing categories and their search results
- search_terms: A list of search terms
- original_query: The original search query string (e.g. "Equinix OR FR5")

Returns:
- result: A dictionary containing the search results in alphabetical order.

---
## search
`def search(term, autocomplete=False)`

Search searchable objects (ixp, network, facility ...) by term.

Returns result dict.

---
## search_v2
`def search_v2(term, geo={})`

Search searchable objects (ixp, network, facility ...) by term on elasticsearch engine.

This function constructs a search query based on the provided term, escaping special
characters to ensure safety in Elasticsearch. It processes the term into keywords,
adds 'AND' between them as necessary, and formats the query for the search.

Returns result dict.

---
