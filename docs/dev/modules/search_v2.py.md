Generated from search_v2.py on 2025-02-11 10:26:48.481231

# peeringdb_server.search_v2

Search v2 implementation used for the PeeringDB top search bar.

This module constructs and executes advanced Elasticsearch queries with
support for geo-based filtering, keyword logic (AND/OR), and partial
IPv6 matching. It includes functionality to prioritize exact and "OR"
term matches and organizes results alphabetically.

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
## append_result_to_category
`def append_result_to_category(sq, result, pk_map)`

Append a search result item to the appropriate category.

Args:
    sq: The current search result item.
    result: The dictionary where results are stored by category.
    pk_map: A map for storing primary keys.

---
## build_geo_filter
`def build_geo_filter(geo)`

Build geo filter for Elasticsearch query if geo parameters are valid.

Args:
    geo: Dictionary containing geo parameters (latitude, longitude, distance).

Returns:
    A dictionary representing the geo filter or None if geo is invalid.

---
## construct_asn_query
`def construct_asn_query(term)`

Constructs Elasticsearch query for ASN searches.

Args:
    term (str): The ASN number as string
Returns:
    dict: Elasticsearch query body for ASN search

---
## construct_ipv6_query
`def construct_ipv6_query(term)`

Constructs Elasticsearch query specifically for IPv6 addresses.

Args:
    term (str): The IPv6 address or partial address
Returns:
    dict: Elasticsearch query body for IPv6 search

---
## construct_name_query
`def construct_name_query(clean_term, term)`

Constructs Elasticsearch query for name-based searches.

Args:
    term (str): The search term
Returns:
    dict: Elasticsearch query body for name search

---
## construct_query_body
`def construct_query_body(term, geo, indexes, ipv6_construct)`

Constructs the Elasticsearch query body based on the search term and geo filter.

Args:
    term (str): The search query string.
    geo (dict): Optional geo filter (latitude, longitude, and distance).
    indexes (list): List of index names to target in the search.

Returns:
    A dictionary representing the Elasticsearch query body.

---
## elasticsearch_proximity_entity
`def elasticsearch_proximity_entity(name)`

Perform an Elasticsearch search for a proximity
entity based on the provided name.

Args:
    name (str): The name of the entity to search for.

Returns:
    dict or None: Returns the first match from Elasticsearch
    or None if no matches are found.

---
## escape_query_string
`def escape_query_string(query_string)`

Escape special characters in a query string to make it safe for Elasticsearch queries.

Args:
query_string (str): The query string to be escaped.

Returns:
str: Escaped query string.

---
## is_matching_geo
`def is_matching_geo(sq, geo)`

Check if the search result matches the given geo constraints.

Args:
    sq: The current search result item.
    geo: Dictionary containing geo filters (latitude, longitude, distance).

Returns:
    True if the result matches the geo constraints, False otherwise.

---
## is_valid_latitude
`def is_valid_latitude(lat)`

Validates a latitude.

---
## is_valid_longitude
`def is_valid_longitude(long)`

Validates a longitude.

---
## new_elasticsearch
`def new_elasticsearch()`

Initialize and return a new Elasticsearch instance.

Returns:
    Elasticsearch: An Elasticsearch instance connected to the configured URL.

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
## process_search_results
`def process_search_results(search_query, geo, categories, limit)`

Process the search results and filter by geo constraints if provided.

Args:
    search_query: The raw search result from Elasticsearch.
    geo: Dictionary containing geo filters (latitude, longitude, distance).
    categories: List of categories to filter results by.
    limit: Maximum number of results to return.

Returns:
    A dictionary with processed and categorized results.

---
## search_v2
`def search_v2(term, geo={})`

Search searchable objects (ixp, network, facility ...) by term on elasticsearch engine.

This function constructs a search query based on the provided term, escaping special
characters to ensure safety in Elasticsearch. It processes the term into keywords,
adds 'AND' between them as necessary, and formats the query for the search.

Args:
    term: List of search terms.
    geo: Optional dictionary containing geo parameters (latitude, longitude, distance).

Returns:
    A dictionary containing the search results by category.

---
