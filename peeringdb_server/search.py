from django.db.models import Q

from peeringdb_server.models import (
    UTC,
    InternetExchange,
    Network,
    Facility,
    Organization,
    REFTAG_MAP,
)
import re
import time
import datetime
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


def make_search_query(term):
    if not term:
        return SearchQuerySet().none()

    try:
        if len(term) == 1:
            int(term)
            term = f"AS{term}"
    except ValueError:
        pass

    if len(term) < 2:
        return SearchQuerySet().none()

    term_str = unaccent(term)

    term_filters = (
        Q(content=term_str)
        | Q(content__startswith=term_str)
        # performance hit
        # | Q(content__endswith=term_str)
    )

    return SearchQuerySet().filter(term_filters, status=Exact("ok"))


def search(term):
    """
    Search searchable objects (ixp, network, facility ...) by term

    Returns result dict
    """

    search_query = make_search_query(term).models(*searchable_models)
    search_tags = ("fac", "ix", "net", "org")
    result = dict([(tag, []) for tag in search_tags])

    for sq in search_query.load_all():
        model = sq.model
        inst = sq.object
        if inst.status != "ok":
            continue
        tag = model.HandleRef.tag

        if tag == "org":
            org_id = inst.id
        else:
            org_id = inst.org_id
        result[tag].append(
            {
                "id": inst.id,
                "name": inst.search_result_name,
                "org_id": org_id,
                "score": sq.score,
            }
        )

    for k, items in list(result.items()):
        # TODO: sort by score (wait until v2 search results)
        result[k] = sorted(items, key=lambda row: row.get("name"))

    return result
