from django.db.models import Q
from django.conf import settings

from peeringdb_server.models import (
    InternetExchange,
    Network,
    Facility,
    Organization,
)

# import time
import unidecode

from haystack.query import SearchQuerySet
from haystack.inputs import Exact

searchable_models = [
    Organization,
    Network,
    InternetExchange,
    Facility,
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
        search_query = make_autocomplete_query(term)
        limit = settings.SEARCH_RESULTS_AUTOCOMPLETE_LIMIT
    else:
        search_query = make_search_query(term)
        limit = settings.SEARCH_RESULTS_LIMIT

    search_tags = ("fac", "ix", "net", "org")
    result = dict([(tag, []) for tag in search_tags])

    for sq in search_query.models(*searchable_models)[:limit]:
        model = sq.model
        tag = model.HandleRef.tag

        if tag == "org":
            org_id = sq.pk
        else:
            org_id = sq.org_id
        result[tag].append(
            {
                "id": sq.pk,
                "name": sq.result_name,
                "org_id": org_id,
                "score": sq.score,
            }
        )

    for k, items in list(result.items()):
        # TODO: sort by score (wait until v2 search results)
        result[k] = sorted(items, key=lambda row: row.get("name"))

    # print("done", time.time() - t0)

    return result
