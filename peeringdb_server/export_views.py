"""
Define export views used for IX-F export and advanced search file download.
"""

import collections
import csv
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

from django.http import HttpResponse, JsonResponse
from django.utils.translation import ugettext_lazy as _
from django.views import View
from rest_framework.test import APIRequestFactory

from peeringdb_server.models import IXLan
from peeringdb_server.renderers import JSONEncoder
from peeringdb_server.rest import REFTAG_MAP as RestViewSets


def export_ixf_ix_members(ixlans, pretty=False):
    member_list = []
    ixp_list = []

    for ixlan in ixlans:
        if ixlan.ix not in ixp_list:
            ixp_list.append(ixlan.ix)

    rv = {
        "version": "0.6",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "member_list": member_list,
        "ixp_list": [{"ixp_id": ixp.id, "shortname": ixp.name} for ixp in ixp_list],
    }

    for ixlan in ixlans:
        asns = []
        for netixlan in ixlan.netixlan_set_active.all():
            if netixlan.asn in asns:
                continue
            connection_list = []
            member = {
                "asnum": netixlan.asn,
                "member_type": "peering",
                "name": netixlan.network.name,
                "url": netixlan.network.website,
                "contact_email": [
                    poc.email
                    for poc in netixlan.network.poc_set_active.filter(visible="Public")
                ],
                "contact_phone": [
                    poc.phone
                    for poc in netixlan.network.poc_set_active.filter(visible="Public")
                ],
                "peering_policy": netixlan.network.policy_general.lower(),
                "peering_policy_url": netixlan.network.policy_url,
                "connection_list": connection_list,
            }
            member_list.append(member)
            asns.append(netixlan.asn)
            for _netixlan in ixlan.netixlan_set_active.filter(asn=netixlan.asn):
                vlan_list = [{}]
                connection = {
                    "ixp_id": _netixlan.ixlan.ix_id,
                    "state": "active",
                    "if_list": [{"if_speed": _netixlan.speed}],
                    "vlan_list": vlan_list,
                }
                connection_list.append(connection)

                if _netixlan.ipaddr4:
                    vlan_list[0]["ipv4"] = {
                        "address": f"{_netixlan.ipaddr4}",
                        "routeserver": _netixlan.is_rs_peer,
                        "max_prefix": _netixlan.network.info_prefixes4,
                        "as_macro": _netixlan.network.irr_as_set,
                    }
                if _netixlan.ipaddr6:
                    vlan_list[0]["ipv6"] = {
                        "address": f"{_netixlan.ipaddr6}",
                        "routeserver": _netixlan.is_rs_peer,
                        "max_prefix": _netixlan.network.info_prefixes6,
                        "as_macro": _netixlan.network.irr_as_set,
                    }

    if pretty:
        return json.dumps(rv, indent=2)
    else:
        return json.dumps(rv)


def view_export_ixf_ix_members(request, ix_id):
    return HttpResponse(
        export_ixf_ix_members(
            IXLan.objects.filter(ix_id=ix_id, status="ok"),
            pretty="pretty" in request.GET,
        ),
        content_type="application/json",
    )


def view_export_ixf_ixlan_members(request, ixlan_id):
    return HttpResponse(
        export_ixf_ix_members(
            IXLan.objects.filter(id=ixlan_id, status="ok"),
            pretty="pretty" in request.GET,
        ),
        content_type="application/json",
    )


class ExportView(View):
    """
    Base class for more complex data exports.
    """

    # supported export fortmats
    formats = ["json", "json_pretty", "csv"]

    # when exporting json data, if this is it not None
    # json data will be wrapped in one additional dict
    # and referenced at a key with the specified name
    json_root_key = "data"

    # exporting data should send file attachment headers
    download = True

    # if download=True this value will be used to specify
    # the filename of the downloaded file
    download_name = "export.{extension}"

    # format to file extension translation table
    extensions = {"csv": "csv", "json": "json", "json_pretty": "json"}

    def get(self, request, fmt):
        fmt = fmt.replace("-", "_")
        if fmt not in self.formats:
            raise ValueError(_("Invalid export format"))

        response_handler = getattr(self, f"response_{fmt}")
        response = response_handler(self.generate(request))

        if self.download is True:
            # send attachment header, triggering download on the client side
            filename = self.download_name.format(extension=self.extensions.get(fmt))
            response["Content-Disposition"] = 'attachment; filename="{}"'.format(
                filename
            )
        return response

    def generate(self, request):
        """
        Function that generates export data from request.

        Override this.
        """
        return {}

    def response_json(self, data):
        """
        Return Response object for normal json response.

        Arguments:
            - data <list|dict>: serializable data, if list is passed you will need
                to specify a value in self.json_root_key

        Returns:
            - JsonResponse
        """
        if self.json_root_key:
            data = {self.json_root_key: data}
        return JsonResponse(data, encoder=JSONEncoder)

    def response_json_pretty(self, data):
        """
        Return Response object for pretty (indented) json response.

        Arguments:
            - data <list|dict>: serializable data, if list is passed tou will need
                to specify a value in self.json_root_key

        Returns:
            - HttpResponse: http response with appropriate json headers, cannot use
                JsonResponse here because we need to specify indent level
        """

        if self.json_root_key:
            data = {self.json_root_key: data}
        return HttpResponse(
            json.dumps(data, indent=2, cls=JSONEncoder), content_type="application/json"
        )

    def response_csv(self, data):
        """
        Return Response object for CSV response.

        Arguments:
            - data <list>

        Returns:
            - HttpResponse
        """
        if not data:
            return ""

        response = HttpResponse(content_type="text/csv")
        csv_writer = csv.DictWriter(response, fieldnames=list(data[0].keys()))

        csv_writer.writeheader()

        for row in data:
            for k, v in list(row.items()):
                if isinstance(v, str):
                    row[k] = f"{v}"
            csv_writer.writerow(row)

        return response


class AdvancedSearchExportView(ExportView):
    """
    Allow exporting of advanced search result data.
    """

    tag = None
    json_root_key = "results"
    download_name = "advanced_search_export.{extension}"

    def fetch(self, request):
        """
        Fetch data from API according to GET parameters.

        Note that `limit` and `depth` will be overwritten, other API
        parameters will be passed along as-is.

        Returns:
            - dict: un-rendered dataset returned by API
        """
        params = request.GET.dict()
        params["limit"] = 250
        params["depth"] = 1

        # prepare api request
        request_factory = APIRequestFactory()
        viewset = RestViewSets[self.tag].as_view({"get": "list"})

        api_request = request_factory.get(
            f"/api/{self.tag}/?{urllib.parse.urlencode(params)}"
        )
        api_request.session = request.session

        # we want to use the same user as the original request
        # so permissions are applied correctly
        api_request.user = request.user

        response = viewset(api_request)

        if response.data and "results" in response.data:
            return response.data.get("results")

        return response.data

    def get(self, request, tag, fmt):  # lgtm[py/inheritance/signature-mismatch]
        """
        Handle export.

        LGTM Notes: signature-mismatch: order of arguments are defined by the
        url routing set up for this view. (e.g., /<tag>/<fmt>)

        The `get` method will never be called in a different
        context where a mismatching signature would matter so
        the lgtm warning can be ignored in this case.
        """
        self.tag = tag
        return super().get(request, fmt)

    def generate(self, request):
        """
        Generate data for the reftag specified in self.tag

        This function will call generate_<tag> and return the result.

        Arguments:
            - request <Request>

        Returns:
            - list: list containing rendered data rows ready for export
        """
        if self.tag not in ["net", "ix", "fac", "org", "campus"]:
            raise ValueError(_("Invalid tag"))
        data_function = getattr(self, f"generate_{self.tag}")
        return data_function(request)

    def generate_net(self, request):
        """
        Fetch network data from the API according to request and then render
        it ready for export.

        Arguments:
            - request <Request>

        Returns:
            - list: list containing rendered data ready for export
        """

        data = self.fetch(request)
        download_data = []
        for row in data:
            download_data.append(
                collections.OrderedDict(
                    [
                        ("Name", row["name"]),
                        ("Also known as", row["aka"]),
                        ("ASN", row["asn"]),
                        ("General Policy", row["policy_general"]),
                        ("Network Type", row["info_type"]),
                        ("Network Scope", row["info_scope"]),
                        ("Traffic Levels", row["info_traffic"]),
                        ("Traffic Ratio", row["info_ratio"]),
                        ("Exchanges", len(row["netixlan_set"])),
                        ("Facilities", len(row["netfac_set"])),
                    ]
                )
            )
        return download_data

    def generate_fac(self, request):
        """
        Fetch facility data from the API according to request and then render
        it ready for export.

        Arguments:
            - request <Request>

        Returns:
            - list: list containing rendered data ready for export
        """

        data = self.fetch(request)
        download_data = []
        for row in data:
            download_data.append(
                collections.OrderedDict(
                    [
                        ("Name", row["name"]),
                        ("Management", row["org_name"]),
                        ("CLLI", row["clli"]),
                        ("NPA-NXX", row["npanxx"]),
                        ("City", row["city"]),
                        ("Country", row["country"]),
                        ("State", row["state"]),
                        ("Postal Code", row["zipcode"]),
                        ("Networks", row["net_count"]),
                    ]
                )
            )
        return download_data

    def generate_ix(self, request):
        """
        Fetch exchange data from the API according to request and then render
        it ready for export.

        Arguments:
            - request <Request>

        Returns:
            - list: list containing rendered data ready for export
        """

        data = self.fetch(request)
        download_data = []
        for row in data:
            download_data.append(
                collections.OrderedDict(
                    [
                        ("Name", row["name"]),
                        ("Media Type", row["media"]),
                        ("Country", row["country"]),
                        ("City", row["city"]),
                        ("Networks", row["net_count"]),
                    ]
                )
            )
        return download_data

    def generate_org(self, request):
        """
        Fetch organization data from the API according to request and then render
        it ready for export.

        Arguments:
            - request <Request>

        Returns:
            - list: list containing rendered data ready for export
        """

        data = self.fetch(request)
        download_data = []
        for row in data:
            download_data.append(
                collections.OrderedDict(
                    [
                        ("Name", row["name"]),
                        ("Country", row["country"]),
                        ("City", row["city"]),
                    ]
                )
            )
        return download_data

    def generate_campus(self, request):
        """
        Fetch campus data from the API according to request and then render
        it ready for export.

        Arguments:
            - request <Request>

        Returns:
            - list: list containing rendered data ready for export
        """

        data = self.fetch(request)
        download_data = []
        for row in data:
            download_data.append(
                collections.OrderedDict(
                    [
                        ("Name", row["name"]),
                        ("Name Long", row["name_long"]),
                        ("Website", row["website"]),
                        ("Fac_set", row["fac_set"]),
                    ]
                )
            )
        return download_data
