"""
Search v2 implementation used for the PeeringDB top search bar.

This module constructs and executes advanced Elasticsearch queries with
support for geo-based filtering, keyword logic (AND/OR), and partial
IPv6 matching. It includes functionality to prioritize exact and "OR"
term matches and organizes results alphabetically.
"""

import copy
import math
import re
from typing import Union

from django.conf import settings
from elasticsearch import Elasticsearch

from mainsite.settings import ELASTIC_PASSWORD, ELASTICSEARCH_URL
from peeringdb_server.search import PARTIAL_IPV6_ADDRESS, append_result


def new_elasticsearch() -> Elasticsearch:
    """
    Initialize and return a new Elasticsearch instance.

    Returns:
        Elasticsearch: An Elasticsearch instance connected to the configured URL.
    """
    es_kwargs = dict(
        http_auth=("elastic", ELASTIC_PASSWORD),
        verify_certs=False,
    )

    es = Elasticsearch(ELASTICSEARCH_URL, **es_kwargs)
    return es


def elasticsearch_proximity_entity(name) -> Union[dict, None]:
    """
    Perform an Elasticsearch search for a proximity
    entity based on the provided name.

    Args:
        name (str): The name of the entity to search for.

    Returns:
        dict or None: Returns the first match from Elasticsearch
        or None if no matches are found.
    """
    es = new_elasticsearch()

    body = {
        "query": {
            "bool": {
                "must": [
                    {"match_phrase_prefix": {"name": name}},
                    {"exists": {"field": "geocode_coordinates"}},
                ]
            }
        },
        "size": 1,  # Return only the first match
    }

    index = ["fac", "org"]  # Search for proximity objects of these types
    search_result = es.search(index=index, body=body)

    # Check if there are any matches and return the first one if available
    if search_result["hits"]["total"]["value"] > 0:
        item = search_result["hits"]["hits"][0]
        item["_source"]["ref_tag"] = item["_index"]
        item["_source"]["id"] = item["_id"]
        return item["_source"]
    else:
        return None


def escape_query_string(query_string: str) -> str:
    """
    Escape special characters in a query string to make it safe for Elasticsearch queries.

    Args:
    query_string (str): The query string to be escaped.

    Returns:
    str: Escaped query string.
    """
    special_characters = [
        '"',
        ":",
        "*",
        "?",
        "+",
        "-",
        "=",
        "&&",
        "||",
        ">",
        "<",
        "!",
        "(",
        ")",
        "{",
        "}",
        "[",
        "]",
        "^",
        "~",
        "/",
    ]
    # Escape special characters
    escaped_string = ""
    for char in query_string:
        if char in special_characters:
            escaped_string += "\\" + char
        elif char == "\\":
            # Escape backslash with an extra backslash
            escaped_string += "\\\\"
        else:
            escaped_string += char

    return escaped_string


def add_and_between_keywords(keywords: list[str]) -> list[str]:
    """
    Add 'AND' between keywords in the list that are neither 'AND' nor 'OR'.

    This function iterates through a list of keywords and appends 'AND'
    between any consecutive keywords that are not 'AND' or 'OR'.

    Args:
        keywords (list of str): A list of keywords to process.

    Returns:
        list of str: A new list with 'AND' inserted between applicable keywords.
    """

    result = []

    for i, keyword in enumerate(keywords):
        result.append(keyword)

        # Check if the current keyword is not the last one
        if i < len(keywords) - 1:
            # If the next keyword is neither 'AND' nor 'OR', append 'OR'
            if keyword not in ["AND", "OR"] and keywords[i + 1] not in ["AND", "OR"]:
                result.append("AND")

    return result


def is_valid_latitude(lat: str) -> bool:
    """Validates a latitude."""
    return re.match(r"^[-]?((([0-8]?[0-9])\.(\d+))|(90(\.0+)?))$", str(lat)) is not None


def is_valid_longitude(long: str) -> bool:
    """Validates a longitude."""
    return (
        re.match(
            r"^[-]?((((1[0-7][0-9])|([0-9]?[0-9]))\.(\d+))|180(\.0+)?)$", str(long)
        )
        is not None
    )


def order_results_alphabetically(
    result: dict[str, list[dict[str, Union[str, int]]]],
    search_terms: list[str],
    original_query: str = "",
) -> dict[str, list[dict[str, Union[str, int]]]]:
    """
    Order the search results alphabetically and put the exact case-insensitive matches in front with special handling for OR queries.

    Args:
    - result: A dictionary containing categories and their search results
    - search_terms: A list of search terms
    - original_query: The original search query string (e.g. "Equinix OR FR5")

    Returns:
    - result: A dictionary containing the search results in alphabetical order.
    """
    # Check if this is an OR query
    if " OR " in original_query:
        # Get the term after OR
        or_term = original_query.split(" OR ")[1].strip().lower()

    # Make sure the search terms are lower case
    search_terms_lower = [term.lower() for term in search_terms]

    # Add the search as a single string to the list of search terms
    search_terms_lower.append(" ".join(search_terms_lower))

    for category in result:
        result[category] = sorted(
            result[category],
            key=lambda x: (-x.get("extra", {}).get("_score", 0), x["name"].lower()),
        )

        if " OR " in original_query:
            # Find items matching the OR term
            or_matches = []
            non_or_matches = []

            for item in result[category]:
                if or_term in item["name"].lower():
                    or_matches.append(item)
                else:
                    non_or_matches.append(item)

            # Reorder the list with OR matches first
            result[category] = or_matches + non_or_matches
        else:
            exact_match_index = -1

            for index, item in enumerate(result[category]):
                if item["name"].lower() in search_terms_lower:
                    exact_match_index = index
                    break

            if exact_match_index != -1:
                exact_match = result[category].pop(exact_match_index)
                result[category].insert(0, exact_match)

    return result


def construct_asn_query(term: str) -> dict:
    """
    Constructs Elasticsearch query for ASN searches.

    Args:
        term (str): The ASN number as string
    Returns:
        dict: Elasticsearch query body for ASN search
    """
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "bool": {
                            "should": [
                                {
                                    "term": {
                                        "asn": {
                                            "value": int(term),
                                            "boost": settings.ES_MATCH_PHRASE_BOOST,
                                        }
                                    }
                                },
                                {
                                    "prefix": {
                                        "asn.raw": {
                                            "value": int(term),
                                            "boost": settings.ES_MATCH_PHRASE_PREFIX_BOOST,
                                        }
                                    }
                                },
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                ]
            }
        },
        "explain": True,
        "_source": True,
        "sort": ["_score"],
    }


def construct_ipv6_query(term: str) -> dict:
    """
    Constructs Elasticsearch query specifically for IPv6 addresses.

    Args:
        term (str): The IPv6 address or partial address
    Returns:
        dict: Elasticsearch query body for IPv6 search
    """
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "bool": {
                            "should": [
                                {
                                    "match_phrase": {
                                        "ipaddr6": {
                                            "query": term,
                                            "boost": settings.ES_MATCH_PHRASE_BOOST,
                                        }
                                    }
                                },
                                {
                                    "prefix": {
                                        "ipaddr6.raw": {
                                            "value": term,
                                            "boost": settings.ES_MATCH_PHRASE_PREFIX_BOOST,
                                        }
                                    }
                                },
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                ]
            }
        },
        "explain": True,
        "_source": True,
        "sort": ["_score"],
    }


def construct_name_query(clean_term: str, term: str) -> dict:
    """
    Constructs Elasticsearch query for name-based searches.

    Args:
        term (str): The search term
    Returns:
        dict: Elasticsearch query body for name search
    """
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "bool": {
                            "should": [
                                {
                                    "match_phrase": {
                                        "name": {
                                            "query": clean_term,
                                            "boost": settings.ES_MATCH_PHRASE_BOOST,
                                        }
                                    }
                                },
                                {
                                    "match_phrase_prefix": {
                                        "name": {
                                            "query": clean_term,
                                            "boost": settings.ES_MATCH_PHRASE_PREFIX_BOOST,
                                        }
                                    }
                                },
                                {
                                    "query_string": {
                                        "query": term,
                                        "fields": ["name"],
                                        "boost": settings.ES_QUERY_STRING_BOOST,
                                    }
                                },
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                ]
            }
        },
        "explain": True,
        "_source": True,
        "sort": ["_score"],
    }


def construct_query_body(
    term: str,
    geo: dict[str, Union[str, float]],
    indexes: list[str],
    ipv6_construct: bool,
) -> dict:
    """
    Constructs the Elasticsearch query body based on the search term and geo filter.

    Args:
        term (str): The search query string.
        geo (dict): Optional geo filter (latitude, longitude, and distance).
        indexes (list): List of index names to target in the search.

    Returns:
        A dictionary representing the Elasticsearch query body.
    """
    clean_term = term.replace("*", "").replace("AND", "").strip()
    if clean_term.isdigit():
        body = construct_asn_query(clean_term)
    elif ipv6_construct:
        body = construct_ipv6_query(clean_term)
    else:
        body = construct_name_query(clean_term, term)

    if geo:
        filters = []
        geo_filter = build_geo_filter(geo)
        if geo_filter:
            filters.append(geo_filter)

        if geo.get("country"):
            country_filter = {"term": {"country.raw": geo["country"]}}
            filters.append(country_filter)

        if geo.get("state"):
            state_filter = {"term": {"state.raw": geo["state"]}}
            filters.append(state_filter)

        if filters:
            body["query"]["bool"]["filter"] = (
                filters if len(filters) > 1 else filters[0]
            )

        try:
            # when the geo is not empty, check the object index from query
            # for the example: search input "fac in las vegas, us"
            # before {'query': {'bool': {'must': [{'bool': {'should': [{'match_phrase': {fac}}, {'match_phrase_prefix': {fac}}, {'query_string': {'query': '*fac*', 'fields': ['name'], 'boost': 2.0}}], 'minimum_should_match': 1}}], 'filter': {'geo_distance': {'distance': '42km', 'geocode_coordinates': {'lat': 36.171563, 'lon': -115.1391009}}}}}}
            # after {"query": {"bool": {"must": {"term": {"_index": "fac"}}, "filter": {"geo_distance": {"distance": "42km", "geocode_coordinates": {"lat": 36.171563, "lon": -115.1391009}}}}}}
            first_must = body["query"]["bool"]["must"][0]
            first_should = first_must["bool"]["should"]

            query_string_clause = next(
                (clause for clause in first_should if "query_string" in clause), None
            )

            if query_string_clause:
                base_query = query_string_clause["query_string"]["query"]
                base_queries = base_query.strip().split(" ")
                # get the object index from query e.g net, ix, etc..
                index = base_queries[0].replace("*", "")
                if index in indexes:
                    # if found the object index then the search will adjust the elasticsearch index to that object index
                    body["query"]["bool"]["must"] = {"term": {"_index": index}}
                    # remove the index name from the query
                    base_query = base_query.replace(f"*{index}*", "")
                    body["query"]["bool"]["must"]["query_string"]["query"] = base_query
                    if not base_query.strip():
                        # if body["query"]["bool"]["must"]["query_string"]["query"] is empty, to avoid empty search result
                        del body["query"]["bool"]["must"]["query_string"]
                elif not base_query.strip():
                    body["query"]["bool"]["must"] = {"terms": {"_index": indexes}}
        except Exception:
            pass

    return body


def build_geo_filter(
    geo: dict[str, Union[str, float]],
) -> dict[str, dict[str, Union[str, float]]] | None:
    """
    Build geo filter for Elasticsearch query if geo parameters are valid.

    Args:
        geo: Dictionary containing geo parameters (latitude, longitude, distance).

    Returns:
        A dictionary representing the geo filter or None if geo is invalid.
    """
    if is_valid_latitude(geo.get("lat", "")) and is_valid_longitude(
        geo.get("long", "")
    ):
        return {
            "geo_distance": {
                "distance": geo["dist"],
                "geocode_coordinates": {
                    "lat": float(geo["lat"]),
                    "lon": float(geo["long"]),
                },
            }
        }
    return None


def process_search_results(
    search_query: dict,
    geo: dict[str, Union[str, float]],
    categories: list[str],
    limit: int,
) -> dict:
    """
    Process the search results and filter by geo constraints if provided.

    Args:
        search_query: The raw search result from Elasticsearch.
        geo: Dictionary containing geo filters (latitude, longitude, distance).
        categories: List of categories to filter results by.
        limit: Maximum number of results to return.

    Returns:
        A dictionary with processed and categorized results.
    """
    result = {tag: [] for tag in categories}
    pk_map = {tag: {} for tag in categories}

    for sq in search_query["hits"]["hits"][:limit]:
        if geo:
            if not is_matching_geo(sq, geo):
                continue

        if sq["_source"]["status"] == "ok":
            sq["_source"]["_score"] = sq["_score"]
            sq["_source"]["_score_explanation"] = sq.get("_explanation", {})
            append_result_to_category(sq, result, pk_map)

    return result


def is_matching_geo(sq: dict, geo: dict[str, Union[str, float]]) -> bool:
    """
    Check if the search result matches the given geo constraints.

    Args:
        sq: The current search result item.
        geo: Dictionary containing geo filters (latitude, longitude, distance).

    Returns:
        True if the result matches the geo constraints, False otherwise.
    """
    if geo.get("country") and geo["country"] not in sq["_source"].get("country", ""):
        return False
    if geo.get("state") and geo["state"] not in sq["_source"].get("state", ""):
        return False
    return True


def append_result_to_category(sq: dict, result: dict, pk_map: dict):
    """
    Append a search result item to the appropriate category.

    Args:
        sq: The current search result item.
        result: The dictionary where results are stored by category.
        pk_map: A map for storing primary keys.
    """
    if sq["_index"] == "net":
        extra = {"asn": sq["_source"]["asn"]}
        if "_score" in sq["_source"]:
            extra["_score"] = sq["_source"]["_score"]
            extra["_score_explanation"] = sq["_source"].get("_score_explanation")

        append_result(
            sq["_index"],
            sq["_id"],
            f"{sq['_source']['name']}",
            sq["_source"]["org"]["id"],
            None,
            result,
            pk_map,
            extra,
        )
    elif sq["_index"] == "org":
        extra = {}
        if "_score" in sq["_source"]:
            extra["_score"] = sq["_source"]["_score"]
            extra["_score_explanation"] = sq["_source"].get("_score_explanation")

        append_result(
            sq["_index"],
            sq["_id"],
            sq["_source"]["name"],
            sq["_id"],
            None,
            result,
            pk_map,
            extra,
        )
    else:
        extra = {}
        if "_score" in sq["_source"]:
            extra["_score"] = sq["_source"]["_score"]
            extra["_score_explanation"] = sq["_source"].get("_score_explanation")

        append_result(
            sq["_index"],
            sq["_id"],
            sq["_source"]["name"],
            sq["_source"]["org"]["id"],
            None,
            result,
            pk_map,
            extra,
        )


def search_v2(
    term: list[Union[str, int]],
    geo: dict[str, Union[str, float]] = {},
) -> dict[str, list[dict[str, Union[str, int]]]]:
    """
    Search searchable objects (ixp, network, facility ...) by term on elasticsearch engine.

    This function constructs a search query based on the provided term, escaping special
    characters to ensure safety in Elasticsearch. It processes the term into keywords,
    adds 'AND' between them as necessary, and formats the query for the search.

    Args:
        term: List of search terms.
        geo: Optional dictionary containing geo parameters (latitude, longitude, distance).

    Returns:
        A dictionary containing the search results by category.
    """
    es = new_elasticsearch()
    # Convert the term to a string and join with space
    qs = " ".join([str(elem) for elem in term])

    # Escape special characters for Elasticsearch
    safe_qs = escape_query_string(qs)
    look_for_exact_matches = []
    ipv6_construct = False

    if PARTIAL_IPV6_ADDRESS.match(" ".join(qs.split())):
        ipv6 = "\\:".join(qs.split(":"))
        term = f"*{ipv6}*"
        ipv6_construct = True
    else:
        keywords = safe_qs.split()
        keywords = add_and_between_keywords(keywords)

        # will track the exact matches to put them on top of the results
        term = ""
        for keyword in keywords:
            if keyword == "OR" or keyword == "AND":
                term += f" {keyword}"
            else:
                look_for_exact_matches.append(keyword)
                term += f" *{keyword}*"

    indexes = ["fac", "ix", "net", "org", "campus", "carrier"]

    body = construct_query_body(term, geo, indexes, ipv6_construct)

    total_limit = settings.SEARCH_RESULTS_LIMIT
    if geo and not term.strip():
        # get counts for each index
        index_counts = {}
        for index in indexes:
            index_body = copy.deepcopy(body)
            if "query" in index_body and "bool" in index_body["query"]:
                count_search = es.search(
                    index=index,
                    body=index_body,
                    size=0,
                    request_timeout=settings.ES_REQUEST_TIMEOUT,
                )
                count = count_search["hits"]["total"]["value"]
                if count > 0:
                    index_counts[index] = count

        # Sort indexes by count
        sorted_indexes = sorted(index_counts.items(), key=lambda x: x[1])

        results = []
        remaining_slots = total_limit

        # Process indexes from smallest to largest
        for index, count in sorted_indexes:
            index_body = copy.deepcopy(body)

            # If this index's count is less than remaining_slots/remaining_indexes,
            # take all its results. Otherwise, take a fair share.
            remaining_indexes = len([i for i, c in sorted_indexes if c >= count])
            fair_share = math.ceil(remaining_slots / remaining_indexes)

            size_to_take = min(count, fair_share)
            if size_to_take > 0:
                index_search = es.search(
                    index=index,
                    body=index_body,
                    size=size_to_take,
                    request_timeout=settings.ES_REQUEST_TIMEOUT,
                )
                results.extend(index_search["hits"]["hits"])
                remaining_slots -= size_to_take

        search_query = {"hits": {"hits": results, "total": {"value": len(results)}}}
    else:
        # Perform the search query
        search_query = es.search(
            index=indexes,
            body=body,
            size=total_limit,
            request_timeout=settings.ES_REQUEST_TIMEOUT,
        )

    # Process and filter the search results
    search_results = process_search_results(
        search_query, geo, indexes, settings.SEARCH_RESULTS_LIMIT
    )

    # Order results alphabetically with exact matches prioritized
    result = order_results_alphabetically(search_results, look_for_exact_matches, qs)

    return result
