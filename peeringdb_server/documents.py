import re
from datetime import timedelta
from types import GeneratorType

import elasticsearch.helpers.errors as errors
from django.utils import timezone
from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer

from peeringdb_server.context import incremental_period
from peeringdb_server.models import (
    Campus,
    Carrier,
    Facility,
    InternetExchange,
    Network,
    NetworkIXLan,
    Organization,
)


def is_valid_latitude(lat):
    """Validates a latitude."""
    return re.match(r"^[-]?((([0-8]?[0-9])\.(\d+))|(90(\.0+)?))$", str(lat)) is not None


def is_valid_longitude(long):
    """Validates a longitude."""
    return (
        re.match(
            r"^[-]?((((1[0-7][0-9])|([0-9]?[0-9]))\.(\d+))|180(\.0+)?)$", str(long)
        )
        is not None
    )


name_analyzer = analyzer(
    "name_analyzer",
    tokenizer="keyword",
    filter=["lowercase"],
)


class MultipleChoiceKeywordField(fields.KeywordField):
    def get_value_from_instance(self, instance, field_value_to_ignore=None):
        # Retrieve the value of the MultipleChoiceField from the instance
        value = super().get_value_from_instance(instance, field_value_to_ignore)

        # If the value is a list or a set, convert it to a list of strings
        if isinstance(value, (list, set)):
            return list(map(str, value))

        # If the value is a string, assume it's a comma-separated list and split it
        if isinstance(value, str):
            return value.split(",")

        # If the value is None or another type, return it as-is
        return value


class StatusMixin:
    """
    Ensures only objects with status=ok are indexed
    and deleted from the index if status is no longer ok
    """

    def get_queryset(self):
        with incremental_period() as max_age:
            if max_age is None or max_age < 0:
                return super().get_queryset().filter(status="ok")
            else:
                max_age_dt = timezone.now() - timedelta(seconds=max_age)
                return (
                    super().get_queryset().filter(status="ok", updated__gte=max_age_dt)
                )

    def should_index_object(self, obj):
        return obj.status == "ok"

    def update(self, thing, **kwargs):
        """
        Updates the document with the given kwargs.
        """

        # if is iterable then we are bulk indexing and can just proceed normally
        if isinstance(thing, GeneratorType):
            return super().update(thing, **kwargs)

        attempt_delete = False

        # otherwise we are updating a single object
        if thing.status != "ok":
            kwargs["action"] = "delete"
            attempt_delete = True
        try:
            return super().update(thing, **kwargs)
        except errors.BulkIndexError as e:
            if attempt_delete:
                pass
            else:
                raise e


class IpAddressMixin:
    def cached_netixlan(self, instance):
        netixlan_set = NetworkIXLan.objects.none()

        if instance.HandleRef.tag in ["net", "ix"]:
            if instance.HandleRef.tag == "net":
                netixlan_set = instance.netixlan_set.filter(status="ok")
            elif instance.HandleRef.tag == "ix":
                ixlan_set = instance.ixlan_set.filter(status="ok")
                netixlan_set = NetworkIXLan.objects.none()
                for ixlan in ixlan_set:
                    netixlan_set = netixlan_set.union(
                        ixlan.netixlan_set.filter(status="ok")
                    )

        return netixlan_set.distinct()

    def prepare_ip_addresses(self, instance, field_name):
        netixlan_set = self.cached_netixlan(instance)
        if netixlan_set.exists():
            ip_addresses = [
                str(getattr(netixlan, field_name)) for netixlan in netixlan_set
            ]
            return list(set(ip_addresses))
        return None

    def prepare_ipaddr4(self, instance):
        return self.prepare_ip_addresses(instance, "ipaddr4")

    def prepare_ipaddr6(self, instance):
        return self.prepare_ip_addresses(instance, "ipaddr6")


class GeocodeMixin(StatusMixin):
    """
    Cleans up invalid lat/lng values beforee passing
    them to the geo code field
    """

    def cached_facilities(self, instance):
        """
        Caches all facilties for network or internet exchange relations.
        This is to speed up processing of those documents as they will
        need to collect all facilities associated with the object to determine
        geo coordinates and country and state
        """

        if instance.HandleRef.tag not in ["net", "ix", "carrier"]:
            return None

        if instance.HandleRef.tag == "net":
            qset = instance.netfac_set.filter(status="ok").select_related("facility")
            return [netfac.facility for netfac in qset]
        elif instance.HandleRef.tag == "ix":
            qset = instance.ixfac_set.filter(status="ok").select_related("facility")
            return [ixfac.facility for ixfac in qset]
        elif instance.HandleRef.tag == "carrier":
            qset = instance.carrierfac_set_active.select_related("facility")
            return [carrierfac.facility for carrierfac in qset]

        return None

    def prepare_geocode_coordinates(self, instance):
        """
        Prepares geo coordinates for the geocode_coordinates field

        For Facility and organization this will read lat/lng from the object itself

        For Network and internet exchange this will return lists of coordinates
        for all facilities associated with the object
        """

        facilities = self.cached_facilities(instance)

        if facilities is not None:
            coordinates = []
            for facility in facilities:
                if is_valid_latitude(facility.latitude) and is_valid_longitude(
                    facility.longitude
                ):
                    coordinates.append(
                        {"lat": facility.latitude, "lon": facility.longitude}
                    )
            return coordinates

        if instance.latitude and instance.longitude:
            if not is_valid_latitude(instance.latitude):
                return None
            if not is_valid_longitude(instance.longitude):
                return None
            return {"lat": instance.latitude, "lon": instance.longitude}
        return None

    def prepare_country(self, instance):
        """
        Prepares country for the country field

        For Facility and organization this will read country from the object itself

        For Network and internet exchange this will return a list of country codes
        for all facilities associated with the object
        """

        facilities = self.cached_facilities(instance)
        if facilities is not None:
            countries = [facility.country.code for facility in facilities]
            return list(set(countries))

        return instance.country.code if instance.country else None

    def prepare_state(self, instance):
        """
        Prepares state for the state field

        For Facility and organization this will read state from the object itself

        For Network and internet exchange this will return a list of states
        for all facilities associated with the object
        """

        facilities = self.cached_facilities(instance)
        if facilities is not None:
            states = [facility.state for facility in facilities]
            return list(set(states))

        return instance.state


@registry.register_document
class OrganizationDocument(GeocodeMixin, Document):
    name = fields.TextField(
        analyzer=name_analyzer,
        fields={
            "raw": {
                "type": "keyword",
            }
        },
    )
    city = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    latitude = fields.FloatField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    longitude = fields.FloatField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    geocode_coordinates = fields.GeoPointField()
    country = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    state = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )

    class Index:
        name = "org"
        settings = {"number_of_shards": 1, "number_of_replicas": 0}

    class Django:
        model = Organization
        fields = [
            # 'partnerships',
            # 'merged_to',
            # 'merged_from',
            # 'campus_set',
            # 'fac_set',
            # 'ix_set',
            # 'net_set',
            # 'carrier_set',
            # 'oauth_applications',
            # 'id',
            "status",
            # 'created',
            # 'updated',
            # "version",
            "address1",
            "address2",
            # "name",
            "aka",
            "name_long",
            # "notes",
            # "geocode_status",
            # "geocode_date",
            # "logo",
            # "restrict_user_emails",
            # "email_domains",
            # "periodic_reauth",
            # "periodic_reauth_period",
            # "flagged",
            # "flagged_date",
        ]


@registry.register_document
class FacilityDocument(GeocodeMixin, Document):
    name = fields.TextField(
        analyzer=name_analyzer,
        fields={
            "raw": {
                "type": "keyword",
            }
        },
    )
    org = fields.NestedField(
        properties={
            "id": fields.IntegerField(),
            "name": fields.TextField(),
        }
    )

    latitude = fields.FloatField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    longitude = fields.FloatField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    geocode_coordinates = fields.GeoPointField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )

    country = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    state = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )

    class Index:
        name = "fac"
        settings = {"number_of_shards": 1, "number_of_replicas": 0}

    class Django:
        model = Facility
        fields = [
            # 'ixfac_set',
            # 'netfac_set',
            # 'carrierfac_set',
            "status",
            # "version",
            "address1",
            "address2",
            "city",
            # "state",
            "zipcode",
            # 'country',
            # 'suite',
            # 'floor',
            # 'latitude',
            # 'longitude',
            # "name",
            # 'social_media',
            "aka",
            "name_long",
            # "clli",
            # "rencode",
            # "npanxx",
            # "tech_email",
            # "tech_phone",
            # "sales_email",
            # "sales_phone",
            # "property",
            # "diverse_serving_substations",
            # 'available_voltage_services',
            # "notes",
            # "region_continent",
            # "geocode_status",
            # "geocode_date",
            # 'org',
            # 'campus',
            # "website",
        ]


@registry.register_document
class InternetExchangeDocument(GeocodeMixin, IpAddressMixin, Document):
    name = fields.TextField(
        analyzer=name_analyzer,
        fields={
            "raw": {
                "type": "keyword",
            }
        },
    )
    org = fields.NestedField(
        properties={
            "id": fields.IntegerField(),
            "name": fields.TextField(),
        }
    )

    geocode_coordinates = fields.GeoPointField(multi=True)

    country = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        },
        multi=True,
    )

    state = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        },
        multi=True,
    )

    ipaddr4 = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        },
        multi=True,
    )

    ipaddr6 = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        },
        multi=True,
    )

    class Index:
        name = "ix"
        settings = {"number_of_shards": 1, "number_of_replicas": 0}

    class Django:
        model = InternetExchange
        fields = [
            # 'ixfac_set',
            # 'ixlan_set',
            # 'ix_email_set',
            "status",
            # "version",
            # "name",
            "aka",
            "name_long",
            "city",
            # 'country',
            # "notes",
            "region_continent",
            "proto_unicast",
            "proto_multicast",
            "proto_ipv6",
            # 'website',
            # 'social_media',
            # 'url_stats',
            # "tech_email",
            # "tech_phone",
            # "policy_email",
            # "policy_phone",
            # "sales_email",
            # "sales_phone",
            # "ixf_net_count",
            # "ixf_last_import",
            # "service_level",
            # "terms"
            # 'org',
        ]


@registry.register_document
class NetworkDocument(GeocodeMixin, IpAddressMixin, Document):
    name = fields.TextField(
        analyzer=name_analyzer,
        fields={
            "raw": {
                "type": "keyword",
            }
        },
    )
    asn = fields.LongField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    # social_media = fields.TextField()
    # website = fields.TextField()
    # asn = fields.IntegerField()
    org = fields.NestedField(
        properties={
            "id": fields.IntegerField(),
            "name": fields.TextField(),
        }
    )

    geocode_coordinates = fields.GeoPointField(multi=True)

    country = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        },
        multi=True,
    )

    state = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        },
        multi=True,
    )

    ipaddr4 = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        },
        multi=True,
    )

    ipaddr6 = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        },
        multi=True,
    )

    info_types = MultipleChoiceKeywordField(attr="info_types")

    class Index:
        name = "net"
        settings = {"number_of_shards": 1, "number_of_replicas": 0}

    class Django:
        model = Network
        fields = [
            # 'netfac_set',
            # 'netixlan_set',
            # 'network_email_set',
            # 'id',
            "status",
            # 'created',
            # 'updated',
            "version",
            # 'asn',
            # 'name',
            "aka",
            "name_long",
            # "irr_as_set",
            # 'website',
            # 'social_media',
            # 'looking_glass',
            # 'route_server',
            # "notes",
            # "notes_private",
            "info_traffic",
            "info_ratio",
            "info_scope",
            "info_prefixes4",
            "info_prefixes6",
            "info_unicast",
            "info_multicast",
            "info_ipv6",
            "info_never_via_route_servers",
            # 'policy_url',
            "policy_general",
            "policy_locations",
            "policy_ratio",
            "policy_contracts",
            "rir_status",
            # "rir_status_updated",
            # "allow_ixp_update",
            # "netixlan_updated",
            # "netfac_updated",
            # "poc_updated",
            # "ix_count",
            # "fac_count",
        ]


@registry.register_document
class CampusDocument(GeocodeMixin, Document):
    name = fields.TextField(
        analyzer=name_analyzer,
        fields={
            "raw": {
                "type": "keyword",
            }
        },
    )
    org = fields.NestedField(
        properties={
            "id": fields.IntegerField(),
            "name": fields.TextField(),
        }
    )
    city = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    latitude = fields.FloatField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    longitude = fields.FloatField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    geocode_coordinates = fields.GeoPointField()
    country = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )
    state = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )

    class Index:
        name = "campus"
        settings = {"number_of_shards": 1, "number_of_replicas": 0}

    class Django:
        model = Campus
        fields = [
            # "id",
            # "org_id",
            # "org_name",
            # "org",
            "status",
            # "created",
            # "updated",
            # "name",
            "name_long",
            "notes",
            "aka",
            # "country",
            # "city",
            # "zipcode",
            # "state",
        ]


@registry.register_document
class CarrierDocument(GeocodeMixin, Document):
    name = fields.TextField(
        analyzer=name_analyzer,
        fields={
            "raw": {
                "type": "keyword",
            }
        },
    )
    org = fields.NestedField(
        properties={
            "id": fields.IntegerField(),
            "name": fields.TextField(),
        }
    )
    geocode_coordinates = fields.GeoPointField()
    country = fields.TextField(
        fields={
            "raw": {
                "type": "keyword",
            }
        }
    )

    class Index:
        name = "carrier"
        settings = {"number_of_shards": 1, "number_of_replicas": 0}

    class Django:
        model = Carrier
        fields = [
            # "id",
            # "org_id",
            # "org_name",
            # "org",
            # "name",
            "aka",
            "name_long",
            # "social_media",
            "status",
            "notes",
            # "carrierfac_set",
        ]
