from django.db.models.signals import post_save, pre_delete
from django.db.models import Q
import peeringdb_server.rest
from peeringdb_server.models import (
    UTC,
    InternetExchange,
    Network,
    Facility,
    Organization,
)
import re
import time
import datetime
import unidecode


def unaccent(v):
    return unidecode.unidecode(v).lower()


# SEARCH INDEX BE STORED HERE

SEARCH_CACHE = {"search_index": {}, "time": 0}

# We want to hook searchable objects into save and delete signals
# so we can update the search index as the data changes without having
# to reload the entire thing all the time


def hook_save(sender, **kwargs):
    obj = kwargs.get("instance")
    tag = obj._handleref.tag
    idx = SEARCH_CACHE.get("search_index")
    if obj.status == "ok":
        if tag not in idx:
            idx[tag] = {}
        idx.get(tag)[obj.id] = obj
    #        print "%d %s refreshed in search index" % (obj.id, tag)
    else:
        try:
            del idx[tag][obj.id]
        except KeyError:
            pass


#        print "%d %s delete from search index" % (obj.id, tag)


def hook_delete(sender, **kwargs):
    obj = kwargs.get("instance")
    tag = obj._handleref.tag
    try:
        del SEARCH_CACHE.get["search_index"][tag][obj.id]
    except TypeError:
        pass
    except KeyError:
        pass


#    print "%d %s deleted from search index " % (obj.id, tag)

searchable_models = [InternetExchange, Network, Facility, Organization]

for model in searchable_models:
    post_save.connect(hook_save, sender=model)
    pre_delete.connect(hook_delete, sender=model)


def search(term):
    """
    Search searchable objects (ixp, network, facility ...) by term

    Returns result dict
    """

    search_tags = ("fac", "ix", "net", "org")
    ref_dict = peeringdb_server.rest.ref_dict()
    t = time.time()

    if not SEARCH_CACHE.get("search_index"):

        # whole db takes 5ish seconds, too slow to cache inline here
        search_index = {
            tag: {obj.id: obj for obj in model.objects.filter(status__in=["ok"])}
            for tag, model in list(ref_dict.items())
            if tag in search_tags
        }

        for typ, stor in list(search_index.items()):
            print("CACHED: %d items in %s" % (len(stor), typ))

        tag_id_re = re.compile(r"(" + r"|".join(search_tags) + r"|asn|as)(\d+)")

        # FIXME: for now lets force a flush every 120 seconds, might want to look
        # at an event based update solution instead
        SEARCH_CACHE.update(
            search_index=search_index, time=t, update_t=t, tag_id_re=tag_id_re
        )
    else:
        search_index = SEARCH_CACHE.get("search_index")
        tag_id_re = SEARCH_CACHE.get("tag_id_re")

    # while we are using signals to make sure that the search index gets updated whenever
    # a model is saved, right now we still have updates from external sources
    # to which those signals cannot be easily connected (importer, fac_merge command etc.)
    #
    # in order to reflect search index changes made by external sources
    # we need to find new / updated object regularily and update the
    # search index from that
    #
    # FIXME: this can be taken out when we turn the importer off - or just leave it
    # in as a fail-safe as it is fairly unobtrusive
    ut = SEARCH_CACHE.get("update_t", 0)
    if t - ut > 600:
        dut = datetime.datetime.fromtimestamp(ut).replace(tzinfo=UTC())
        print("Updating search index with newly created/updates objects")
        search_index_update = {
            tag: {
                obj.id: obj
                for obj in model.objects.filter(
                    Q(created__gte=dut) | Q(updated__gte=dut)
                ).filter(status="ok")
            }
            for tag, model in list(ref_dict.items())
            if tag in search_tags
        }
        for tag, objects in list(search_index_update.items()):
            if tag not in SEARCH_CACHE["search_index"]:
                SEARCH_CACHE["search_index"][tag] = {
                    obj.id: obj for obj in ref_dict[tag].objects.filter(status="ok")
                }
            SEARCH_CACHE["search_index"][tag].update(objects)

        SEARCH_CACHE["update_t"] = t

    # FIXME: for some reason this gets unset sometimes - need to figure out
    # why - for now just recreate when its missing
    if not tag_id_re:
        tag_id_re = re.compile(r"(" + r"|".join(search_tags) + r"|asn|as)(\d+)")
        SEARCH_CACHE["tag_id_re"] = tag_id_re

    print("Search index retrieval took %.5f seconds" % (time.time() - t))

    result = {tag: [] for tag, model in list(ref_dict.items())}

    term = unaccent(term)

    # try to convert to int for numeric search matching
    typed_q = {}
    try:
        typed_q["int"] = int(term)
    except ValueError:
        pass

    # check for ref tags
    try:
        match = tag_id_re.match(term)
        if match:
            typed_q[match.group(1)] = match.group(2)

    except ValueError:
        pass

    # FIXME  model should have a search_fields attr on it
    # this whole thing should be replaced with something more modular to get
    # rid of all the ifs
    for tag, index in list(search_index.items()):
        for id, data in list(index.items()):

            if tag == "org":
                data.org_id = data.id

            if unaccent(data.name).find(term) > -1:
                result[tag].append(
                    {"id": id, "name": data.search_result_name, "org_id": data.org_id}
                )
                continue

            if hasattr(data, "name_long") and unaccent(data.name_long).find(term) > -1:
                result[tag].append(
                    {"id": id, "name": data.search_result_name, "org_id": data.org_id}
                )
                continue

            if hasattr(data, "aka") and unaccent(data.aka).find(term) > -1:
                result[tag].append(
                    {"id": id, "name": data.search_result_name, "org_id": data.org_id}
                )
                continue

            if typed_q:
                if tag in typed_q:
                    if str(data.id).startswith(typed_q[tag]):
                        result[tag].append(
                            {
                                "id": id,
                                "name": data.search_result_name,
                                "org_id": data.org_id,
                            }
                        )
                        continue

                # search asn on everyting? probably just if asn in search
                # fields
                if hasattr(data, "asn"):
                    asn = typed_q.get(
                        "as", typed_q.get("asn", str(typed_q.get("int", "")))
                    )
                    if asn and str(data.asn).startswith(asn):
                        result[tag].append(
                            {
                                "id": id,
                                "name": data.search_result_name,
                                "org_id": data.org_id,
                            }
                        )

    for k, items in list(result.items()):
        result[k] = sorted(items, key=lambda row: row.get("name"))

    return result
