"""
Defines django-haystack search indexes
"""

from haystack import indexes

from django.db.models import Q
from django.conf import settings


from peeringdb_server.search import unaccent

from peeringdb_server.models import (
    Organization,
    Network,
    NetworkIXLan,
    NetworkFacility,
    NetworkContact,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLan,
    IXLanPrefix,
)


class EntityIndex(indexes.SearchIndex):

    """
    Search index for org, net, ix and fac entities
    """

    text = indexes.CharField(document=True, use_template=True)
    status = indexes.CharField(model_attr="status")

    class Meta:
        relations = []

    def get_model(self):
        pass

    def _append_filter(self, filters, filter):
        if filters:
            filters |= filter
        else:
            filters = filter
        return filters

    def build_queryset(self, using=None, start_date=None, end_date=None):

        relations = self.Meta.relations
        qset = self.index_queryset()

        if not start_date and not end_date:
            qset = qset.filter(status="ok")

        if relations:
            qset = qset.select_related(*relations)

        if not relations or (not start_date and not end_date):
            return qset

        filters = None

        filter_map = [
            (start_date, "updated__gte"),
            (end_date, "updated__lte"),
        ]

        for date, filter in filter_map:
            if not date:
                continue

            # filter by object's updated times

            filters = self._append_filter(filters, Q(**{filter: date}))

            # filter by object's relevant relationship updated times

            for relation in relations:
                _filter = Q(
                    **{
                        f"{relation}__{filter}": date,
                    }
                )
                filters = self._append_filter(filters, _filter)

        if filters:
            qset = qset.filter(filters)

        return qset

    def get_updated_field(self):
        """
        What field to use for determining object age, this
        is required for the --age parameter to function
        in the update_index command
        """
        return "updated"

    def prepare(self, obj):
        self.prepared_data = super().prepare(obj)
        self.prepared_data["text"] = unaccent(self.prepared_data["text"])
        return self.prepared_data


class MainEntity(EntityIndex):
    name = indexes.CharField()
    auto = indexes.EdgeNgramField()
    result_name = indexes.CharField(model_attr="search_result_name", indexed=False)

    def prepare_auto(self, obj):
        return self.prepare_name(obj)

    def prepare_name(self, obj):
        return unaccent(f"{obj.name} {obj.aka} {obj.name_long}")

    def prepare(self, obj):
        data = super().prepare(obj)
        data["boost"] = settings.SEARCH_MAIN_ENTITY_BOOST
        return data


class OrganizationIndex(MainEntity, indexes.Indexable):
    def get_model(self):
        return Organization


class InternetExchangeIndex(MainEntity, indexes.Indexable):
    org_id = indexes.IntegerField(indexed=False, model_attr="org_id")

    class Meta:
        relations = ["org"]

    def get_model(self):
        return InternetExchange


class NetworkIndex(MainEntity, indexes.Indexable):
    org_id = indexes.IntegerField(indexed=False, model_attr="org_id")

    class Meta:
        relations = ["org"]

    def get_model(self):
        return Network

    def prepare_auto(self, obj):
        asn = obj.asn
        return f"{self.prepare_name(obj)} AS{asn} AS-{asn} {asn}"


class FacilityIndex(MainEntity, indexes.Indexable):
    org_id = indexes.IntegerField(indexed=False, model_attr="org_id")

    class Meta:
        relations = ["org"]

    def get_model(self):
        return Facility


class NetworkIXLanIndex(EntityIndex, indexes.Indexable):

    ix_id = indexes.IntegerField(indexed=False, model_attr="ixlan__ix__id")
    ix_org_id = indexes.IntegerField(indexed=False, model_attr="ixlan__ix__org_id")
    ix_result_name = indexes.CharField(indexed=False)

    net_id = indexes.IntegerField(indexed=False, model_attr="network_id")
    net_org_id = indexes.IntegerField(indexed=False, model_attr="network__org_id")
    net_result_name = indexes.CharField(indexed=False)

    net_sub_result_name = indexes.CharField(indexed=False)
    ix_sub_result_name = indexes.CharField(indexed=False)

    class Meta:
        relations = ["network", "ixlan__ix", "network__org", "ixlan__ix__org"]

    def get_model(self):
        return NetworkIXLan

    def prepare_ix_result_name(self, obj):
        return obj.ixlan.ix.search_result_name

    def prepare_net_result_name(self, obj):
        return obj.network.search_result_name

    def prepare_ix_sub_result_name(self, obj):
        if obj.ipaddr4 and obj.ipaddr6:
            return f"{obj.ipaddr4} {obj.ipaddr6}"
        elif obj.ipaddr4:
            return f"{obj.ipaddr4}"
        elif obj.ipaddr6:
            return f"{obj.ipaddr6}"

    def prepare_net_sub_result_name(self, obj):
        ips = self.prepare_ix_sub_result_name(obj)
        return f"{obj.ixlan.ix.search_result_name} {ips}"


class IXLanPrefixIndex(EntityIndex, indexes.Indexable):

    ix_id = indexes.IntegerField(indexed=False, model_attr="ixlan__ix__id")
    ix_org_id = indexes.IntegerField(indexed=False, model_attr="ixlan__ix__org_id")
    ix_result_name = indexes.CharField(indexed=False)

    class Meta:
        relations = ["ixlan__ix", "ixlan__ix__org"]

    def get_model(self):
        return IXLanPrefix

    def prepare_ix_result_name(self, obj):
        return obj.ixlan.ix.search_result_name

    def prepare_ix_sub_result_name(self, obj):
        return obj.prefix


# The following models are currently not indexed
"""
class NetworkFacilityIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["network", "facility", "network__org", "facility__org"]

    def get_model(self):
        return NetworkFacility


class InternetExchangeFacilityIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["ix", "ix__org", "facility", "facility__org"]

    def get_model(self):
        return InternetExchangeFacility



class NetworkContactIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["network", "network__org"]

    def get_model(self):
        return NetworkContact


class IXLanIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["ix", "ix__org"]

    def get_model(self):
"""
