import peeringdb_server.rest
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

searchable_models = [
    Organization,
    Network,
    InternetExchange,
    Facility,
]


def unaccent(v):
    return unidecode.unidecode(v).lower()


def search(term):
    """
    Search searchable objects (ixp, network, facility ...) by term

    Returns result dict
    """

    if not term or len(term) < 3:
        return {}

    search_tags = ("fac", "ix", "net", "org")
    ref_dict = peeringdb_server.rest.ref_dict()
    t = time.time()
    result = dict([(tag, []) for tag in search_tags])
    search_query = SearchQuerySet().filter_and(content=unaccent(term), status="ok")

    search_query = search_query.models(*searchable_models)

    for sq in search_query.load_all():
        model = sq.model
        inst = sq.object
        tag = model.HandleRef.tag

        if tag == "org":
            org_id = inst.id
        else:
            org_id = inst.org_id
        result[tag].append(
            {"id": inst.id, "name": inst.search_result_name, "org_id": org_id}
        )

    for k, items in list(result.items()):
        result[k] = sorted(items, key=lambda row: row.get("name"))

    return result
