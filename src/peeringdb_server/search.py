"""
Search implementation used for the peeringdb top search bar, name
searches through the api `name_search` filter, as well as advanced
search functionality.

Search logic is handled by django-haystack and whoosh.

Refer to search_indexes.py for search index definition.
"""

# import time
import re

import unidecode
from django.conf import settings
from django.db.models import Q
from haystack.inputs import Exact
from haystack.query import SearchQuerySet

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkIXLan,
    Organization,
)

# models considered during autocomplete (quick-search)

autocomplete_models = [
    Organization,
    Network,
    InternetExchange,
    Facility,
]

# models considered during standard search

searchable_models = [
    Organization,
    Network,
    Facility,
    InternetExchange,
    NetworkIXLan,
    IXLanPrefix,
    #    InternetExchangeFacility,
    #    NetworkFacility,
    #    NetworkContact,
    #    IXLan,
]


ONLY_DIGITS = re.compile(r"^[0-9]+$")
# These are not exact, but should be good enough
PARTIAL_IPV4_ADDRESS = re.compile(r"^([0-9]{1,3}\.){1,3}([0-9]{1,3})?$")
PARTIAL_IPV6_ADDRESS = re.compile(r"^([0-9A-Fa-f]{1,4}|:):[0-9A-Fa-f:]*$")


def unaccent(v):
    return unidecode.unidecode(v).lower().strip()


def valid_partial_ipv4_address(ip):
    return all(int(s) >= 0 and int(s) <= 255 for s in ip.split(".") if len(s) > 0)


def make_asn_query(term):
    return Network.objects.filter(asn__exact=term, status="ok")


def make_ipv4_query(term):
    return NetworkIXLan.objects.filter(ipaddr4__startswith=term, status="ok")


def make_ipv6_query(term):
    return NetworkIXLan.objects.filter(ipaddr6__startswith=term, status="ok")


def prepare_term(term):
    try:
        if len(term) == 1:
            int(term)
            term = f"AS{term}"
    except ValueError:
        pass

    return unaccent(term)


def make_search_query(term):
    if not term:
        return SearchQuerySet().none()

    term = unaccent(term)

    if ONLY_DIGITS.match(term):
        return make_asn_query(term)

    if PARTIAL_IPV4_ADDRESS.match(term):
        if valid_partial_ipv4_address(term):
            return make_ipv4_query(term)

    if PARTIAL_IPV6_ADDRESS.match(term):
        return make_ipv6_query(term)

    term_filters = Q(content=term) | Q(content__startswith=term)

    return (
        SearchQuerySet()
        .filter(term_filters, status=Exact("ok"))
        .models(*searchable_models)
    )


def make_name_search_query(term):
    if not term:
        return SearchQuerySet().none()

    term = prepare_term(term)

    term_filters = Q(name=term) | Q(name__startswith=term)

    return SearchQuerySet().filter(term_filters, status=Exact("ok"))


def make_autocomplete_query(term):
    if not term:
        return SearchQuerySet().none()

    term = prepare_term(term)
    return SearchQuerySet().autocomplete(auto=term).filter(status=Exact("ok"))


def search(term, autocomplete=False):
    """
    Search searchable objects (ixp, network, facility ...) by term.

    Returns result dict.
    """

    # t0 = time.time()

    if autocomplete:
        search_query = make_autocomplete_query(term).models(*autocomplete_models)
        limit = settings.SEARCH_RESULTS_AUTOCOMPLETE_LIMIT
    else:
        search_query = make_search_query(term)
        limit = settings.SEARCH_RESULTS_LIMIT

    categories = ("fac", "ix", "net", "org")
    result = {tag: [] for tag in categories}
    pk_map = {tag: {} for tag in categories}

    # add entries to the result by order of scoring with the
    # highest scored on top (beginning of list)

    for sq in search_query[:limit]:
        if hasattr(sq, "model"):
            model = sq.model
            model.HandleRef.tag
            categorize(sq, result, pk_map)
        else:
            if sq.HandleRef.tag == "netixlan":
                add_secondary_entries(sq, result, pk_map)
            else:
                append_result(
                    sq.HandleRef.tag,
                    sq.pk,
                    getattr(sq, "search_result_name", None),
                    sq.org_id,
                    None,
                    result,
                    pk_map,
                )

    # print("done", time.time() - t0)

    return result


def get_lat_long_from_search_result(search_result):
    if search_result is None:
        return None

    latitude = search_result.get("latitude")
    longitude = search_result.get("longitude")

    if latitude is not None and longitude is not None:
        return latitude, longitude
    else:
        return None


def categorize(sq, result, pk_map):
    if getattr(sq, "result_name", None):
        # main entity
        tag = sq.model.HandleRef.tag
        if tag == "org":
            org_id = int(sq.pk)
        else:
            org_id = sq.org_id
        append_result(tag, int(sq.pk), sq.result_name, org_id, None, result, pk_map)
    else:
        add_secondary_entries(sq, result, pk_map)


def add_secondary_entries(sq, result, pk_map):
    for tag in result.keys():
        if not getattr(sq, f"{tag}_result_name", None):
            continue

        org_id = int(getattr(sq, f"{tag}_org_id", 0))
        name = getattr(sq, f"{tag}_result_name")
        pk = int(getattr(sq, f"{tag}_id", 0))
        sub_name = getattr(sq, f"{tag}_sub_result_name")
        append_result(tag, pk, name, org_id, sub_name, result, pk_map)


def append_result(tag, pk, name, org_id, sub_name, result, pk_map, extra={}):
    if pk in pk_map[tag]:
        return

    pk_map[tag][pk] = True

    result[tag].append(
        {
            "id": pk,
            "name": name,
            "org_id": int(org_id),
            "sub_name": sub_name,
            "extra": extra,
        }
    )


def format_search_query(query):
    if " " in query and " AND " not in query:
        query = query.replace(" ", " AND ")
    return query
