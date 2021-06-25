"""
Defines django-haystack search indexes
"""

from haystack import indexes

from django.db.models import Q


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


class OrganizationIndex(EntityIndex, indexes.Indexable):
    def get_model(self):
        return Organization


class InternetExchangeIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["org"]

    def get_model(self):
        return InternetExchange


class NetworkIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["org"]

    def get_model(self):
        return Network


class FacilityIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["org"]

    def get_model(self):
        return Facility


class NetworkFacilityIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["network", "facility", "network__org", "facility__org"]

    def get_model(self):
        return NetworkFacility


class NetworkIXLanIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["network", "ixlan__ix", "network__org", "ixlan__ix__org"]

    def get_model(self):
        return NetworkIXLan


class NetworkContactIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["network", "network__org"]

    def get_model(self):
        return NetworkContact


class InternetExchangeFacilityIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["ix", "ix__org", "facility", "facility__org"]

    def get_model(self):
        return InternetExchangeFacility


class IXLanIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["ix", "ix__org"]

    def get_model(self):
        return IXLan


class IXLanPrefixIndex(EntityIndex, indexes.Indexable):
    class Meta:
        relations = ["ixlan__ix", "ixlan__ix__org"]

    def get_model(self):
        return IXLanPrefix
