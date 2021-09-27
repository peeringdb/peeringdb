"""
Search implementation used for the peeringdb top search bar, as well as, name searches through
the api `name_search` filter, as well as, advances search name field searches.

Search logic is handled by django-haystack and whoosh.

Refer to search_indexes.py for search index definition.
"""

# import time
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


def unaccent(v):
    return unidecode.unidecode(v).lower()


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

    term = prepare_term(term)

    term_filters = Q(content=term) | Q(content__startswith=term)

    return SearchQuerySet().filter(term_filters, status=Exact("ok"))


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
    Search searchable objects (ixp, network, facility ...) by term

    Returns result dict
    """

    # t0 = time.time()

    if autocomplete:
        search_query = make_autocomplete_query(term).models(*autocomplete_models)
        limit = settings.SEARCH_RESULTS_AUTOCOMPLETE_LIMIT
    else:
        search_query = make_search_query(term).models(*searchable_models)
        limit = settings.SEARCH_RESULTS_LIMIT

    categories = ("fac", "ix", "net", "org")
    result = {tag: [] for tag in categories}
    pk_map = {tag: {} for tag in categories}

    for sq in search_query[:limit]:
        model = sq.model
        model.HandleRef.tag

        categorize(sq, result, pk_map)

    # print("done", time.time() - t0)

    return result


def categorize(sq, result, pk_map):

    if getattr(sq, "result_name", None):
        # main entity
        tag = sq.model.HandleRef.tag
        if tag == "org":
            org_id = int(sq.pk)
        else:
            org_id = sq.org_id
        append_result(tag, int(sq.pk), sq.result_name, org_id, None, result, pk_map)
        return

    # secondary entities

    for tag in result.keys():
        if not getattr(sq, f"{tag}_result_name", None):
            continue

        org_id = int(getattr(sq, f"{tag}_org_id", 0))
        name = getattr(sq, f"{tag}_result_name")
        pk = int(getattr(sq, f"{tag}_id", 0))
        sub_name = getattr(sq, f"{tag}_sub_result_name")
        append_result(tag, pk, name, org_id, sub_name, result, pk_map)


def append_result(tag, pk, name, org_id, sub_name, result, pk_map):

    if pk in pk_map[tag]:
        return

    pk_map[tag][pk] = True

    result[tag].append(
        {"id": pk, "name": name, "org_id": int(org_id), "sub_name": sub_name}
    )
