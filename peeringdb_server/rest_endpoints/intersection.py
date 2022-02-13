from rest_framework import status, viewsets
from rest_framework.response import Response

from peeringdb_server.rest_endpoints.mixins import ReadOnlyMixin
from peeringdb_server.models import (
    Facility,
    InternetExchange,
    NetworkIXLan,
    NetworkFacility,
)

class IXIntersectionViewSet(ReadOnlyMixin, viewsets.ModelViewSet):
    """
    IX intersection endpoint.

    List all IX that all asn in asn_list are present.
    """

    lookup_field = "asn_list"
    http_method_names = ["get"]
    queryset = NetworkIXLan.objects.none()
    model = InternetExchange


    def list(self, request):

        if 'asn_list' not in request.GET:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": "missing asn_list parameter"}
            )
        asn_list = request.GET['asn_list']       
        asn_list = asn_list.split(',')

        output = []
        ixlans = {}
        for asn in asn_list:
            netixlans = NetworkIXLan.objects.filter(asn=int(asn))
            ixlans[asn] = set()
            for netixlan in netixlans:
                ixlans[asn].add(netixlan.ix_id)
        
        setlist = [ ixlans[asn] for asn in ixlans]
        common_ix = set.intersection(*setlist)
        
        geo_filters = ["city", "country", "region_continent",]
        
        for ix_id in common_ix:
            try:
                query_params = { param: request.GET[param] for param in geo_filters if param in request.GET}
                query_params['id'] = ix_id
                ix_object = InternetExchange.objects.get(**query_params)
                attributes = [
                    "id",
                    "org_id",
                    "name",
                    "aka",
                    "name_long",
                    "city",
                    "country",
                    "region_continent",
                    "media",
                    "notes",
                    "proto_unicast",
                    "proto_multicast",
                    "proto_ipv6",
                    "website",
                    "url_stats",
                    "tech_email",
                    "tech_phone",
                    "policy_email",
                    "policy_phone",
                    "sales_phone",
                    "sales_email",
                    "fac_set",
                    "prefix",
                    "net_count",
                    "fac_count",
                    "ixf_net_count",
                    "ixf_last_import",
                    "ixf_import_request",
                    "ixf_import_request_status",
                    "service_level",
                    "terms",
                    ]
                ix_data = {}

                for attr in attributes:
                    if hasattr(ix_object, attr):
                        ix_data[attr] = getattr(ix_object, attr)
                output.append(ix_data)

            except self.model.DoesNotExist:
                pass       
                
        return Response(output)

class FacIntersectionViewSet(ReadOnlyMixin, viewsets.ModelViewSet):
    """
    Facility intersection endpoint.

    List all Facilities that all asn in asn_list are present.
    """

    lookup_field = "asn_list"
    http_method_names = ["get"]
    queryset = NetworkFacility.objects.none()
    model = Facility


    def list(self, request):

        if 'asn_list' not in request.GET:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"detail": "missing asn_list parameter"}
            )
        asn_list = request.GET['asn_list']       
        asn_list = asn_list.split(',')

        output = []
        fac_sets = {}
        for asn in asn_list:
            netfacs = NetworkFacility.objects.filter(local_asn=int(asn))
            fac_sets[asn] = set()
            for netfac in netfacs:
                fac_sets[asn].add(netfac.facility_id)
        
        setlist = [ fac_sets[asn] for asn in fac_sets]
        common_fac = set.intersection(*setlist)

        geo_filters = ["city", "country", "region_continent",]

        for fac_id in common_fac:
            try:
                query_params = { param: request.GET[param] for param in geo_filters if param in request.GET}
                query_params['id'] = fac_id
                fac_object = Facility.objects.get(**query_params)
                attributes = [
                            "org_name",
                            "name",
                            "aka",
                            "name_long",
                            "website",
                            "clli",
                            "rencode",
                            "npanxx",
                            "notes",
                            "net_count",
                            "ix_count",
                            "suggest",
                            "sales_email",
                            "sales_phone",
                            "tech_email",
                            "tech_phone",
                            "available_voltage_services",
                            "diverse_serving_substations",
                            "property",
                            "region_continent",
                        ]
                fac_data = {}
                for attr in attributes:
                    if hasattr(fac_object, attr):
                        fac_data[attr] = getattr(fac_object, attr)

                output.append(fac_data)

            except self.model.DoesNotExist:
                pass

        return Response(output)
