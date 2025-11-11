"""
Define export views used for IX-F export and advanced search file download.
"""

import collections
import csv
import datetime
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _
from django.views import View
from rest_framework.test import APIRequestFactory
from simplekml import Kml, Style

from peeringdb_server.models import (
    Campus,
    Facility,
    InternetExchange,
    IXLan,
    Network,
    NetworkFacility,
    NetworkIXLan,
)
from peeringdb_server.renderers import JSONEncoder
from peeringdb_server.rest import REFTAG_MAP as RestViewSets
from peeringdb_server.util import add_kmz_overlay_watermark, generate_balloonstyle_text


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


def delete_key(data, keys):
    for d in data:
        for key in keys:
            if key in d:
                d.pop(key, "")


class ExportView(View):
    """
    Base class for more complex data exports.
    """

    # supported export fortmats
    formats = ["json", "json_pretty", "csv", "kmz"]

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
    extensions = {"csv": "csv", "json": "json", "json_pretty": "json", "kmz": "kmz"}

    def get(self, request, fmt):
        fmt = fmt.replace("-", "_")
        if fmt not in self.formats:
            raise ValueError(_("Invalid export format"))

        response_handler = getattr(self, f"response_{fmt}")
        response = response_handler(self.generate(request, fmt))

        if self.download is True:
            # send attachment header, triggering download on the client side
            filename = self.download_name.format(extension=self.extensions.get(fmt))
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
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
            delete_key(data, ["Latitude", "Longitude", "Notes"])
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
            delete_key(data, ["Latitude", "Longitude", "Notes"])
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

        delete_key(data, ["Latitude", "Longitude", "Notes"])
        response = HttpResponse(content_type="text/csv")
        csv_writer = csv.DictWriter(response, fieldnames=list(data[0].keys()))

        csv_writer.writeheader()

        for row in data:
            for k, v in list(row.items()):
                if isinstance(v, str):
                    row[k] = f"{v}"
            csv_writer.writerow(row)

        return response

    def response_kmz(self, data):
        """
        Return Response object for kmz response.

        Arguments:
            - data <list>

        Returns:
            - HttpResponse
        """
        if not data:
            return ""

        kml = Kml()
        add_kmz_overlay_watermark(kml)
        style = Style()
        keys = list(data[0].keys())
        for exclude_key in ["Latitude", "Longitude", "Notes"]:
            try:
                keys.remove(exclude_key)
            except ValueError:
                pass
        style.balloonstyle.text = generate_balloonstyle_text(keys)
        for row in data:
            lat = row.pop("Latitude", None)
            lon = row.pop("Longitude", None)
            notes = row.pop("Notes", "")

            if lat is None or lon is None:
                continue

            point = kml.newpoint(
                name=row.get("Name"),
                description=notes,
                coords=[(lon, lat)],
            )
            point.style = style
            for key, value in row.items():
                point.extendeddata.newdata(
                    name=key, value=escape(value), displayname=key.title()
                )
        with tempfile.NamedTemporaryFile(suffix=".kmz", delete=False) as kmz_temp_file:
            kml.savekmz(kmz_temp_file.name)

            kmz_temp_file.seek(0)
            file_content = kmz_temp_file.read()

        response = HttpResponse(file_content)
        response["Content-Type"] = "application/vnd.google-earth.kmz"
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
        params["depth"] = 0

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

    def generate(self, request, fmt):
        """
        Generate data for the reftag specified in self.tag

        This function will call generate_<tag> and return the result.

        Arguments:
            - request <Request>

        Returns:
            - list: list containing rendered data rows ready for export
        """
        fmt = fmt.replace("-", "_")
        if self.tag not in [
            "net",
            "ix",
            "fac",
            "org",
            "campus",
            "carrier",
            "asn_connectivity",
        ]:
            raise ValueError(_("Invalid tag"))

        if fmt == "kmz" and self.tag not in ["org", "fac", "campus", "ix", "carrier"]:
            # export kmz only for org,fac,campus,ix
            raise ValueError(_("Invalid export format"))

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
            net = Network.objects.get(id=row["id"])
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
                        ("Exchanges", net.netixlan_set.count()),
                        ("Facilities", net.netfac_set.count()),
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
                        ("Latitude", row["latitude"]),
                        ("Longitude", row["longitude"]),
                        ("Notes", row["notes"]),
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
            latitude = None
            longitude = None
            ix = InternetExchange.objects.filter(id=row["id"]).first()
            if ix:
                ixfac = ix.ixfac_set.filter(facility__city=row["city"]).first()
                if ixfac:
                    fac = ixfac.facility
                    latitude = fac.latitude
                    longitude = fac.longitude

            download_data.append(
                collections.OrderedDict(
                    [
                        ("Name", row["name"]),
                        ("Country", row["country"]),
                        ("City", row["city"]),
                        ("Networks", row["net_count"]),
                        ("Latitude", latitude),
                        ("Longitude", longitude),
                        ("Notes", row["notes"]),
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
                        ("Latitude", row["latitude"]),
                        ("Longitude", row["longitude"]),
                        ("Notes", row["notes"]),
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
            latitude = None
            longitude = None
            campus = Campus.objects.filter(id=row["id"]).first()
            if campus:
                latitude = campus.latitude
                longitude = campus.longitude
            download_data.append(
                collections.OrderedDict(
                    [
                        ("Name", row["name"]),
                        ("Name Long", row["name_long"]),
                        ("Website", row["website"]),
                        ("Fac_set", row["fac_set"]),
                        ("Latitude", latitude),
                        ("Longitude", longitude),
                        ("Notes", row["notes"]),
                    ]
                )
            )
        return download_data

    def generate_carrier(self, request):
        """
        Fetch carrier data from the API and render it for export.
        """
        data = self.fetch(request)
        download_data = []
        for row in data:
            download_data.append(
                collections.OrderedDict(
                    [
                        ("Name", row["name"]),
                        ("Long Name", row["name_long"]),
                        ("Organization", row["org_name"]),
                        ("Facilities", row["fac_count"]),
                    ]
                )
            )
        return download_data

    def _row_filters_asn_connectivity(
        self, asn_count, total_asns, match_filter, hide_unmatched
    ):
        """
        Determine if a row should be included based on filter settings.
        This matches the frontend filtering logic.

        Arguments:
            - asn_count: Number of ASNs present at this location
            - total_asns: Total number of ASNs being queried
            - match_filter: Filter type ('show-all', 'any-match', 'all-match')
            - hide_unmatched: Whether to hide rows with no matches

        Returns:
            - bool: True if row should be included
        """
        # Determine match type (matches frontend logic)
        has_any_match = asn_count >= 2 and asn_count < total_asns
        has_all_match = asn_count == total_asns
        has_no_match = not has_any_match and not has_all_match

        show_row = True

        # Apply match_filter first
        if match_filter == "any-match" and not has_any_match:
            show_row = False
        elif match_filter == "all-match" and not has_all_match:
            show_row = False

        # Apply hide_unmatched filter (independent of match_filter)
        if hide_unmatched and has_no_match:
            show_row = False

        return show_row

    def _generate_exchange_connectivity(self, asn_list, match_filter, hide_unmatched):
        """
        Generate exchange connectivity matrix for given ASN list.

        Arguments:
            - asn_list: List of ASN integers to check connectivity for
            - match_filter: Filter type ('show-all', 'any-match', 'all-match')
            - hide_unmatched: Whether to hide rows with no matches

        Returns:
            - list: Matrix rows with exchange connectivity data
        """
        # Query all netixlan for these ASNs
        netixlan_qs = NetworkIXLan.objects.filter(
            network__asn__in=asn_list, status="ok"
        )
        ix_ids = set(netixlan_qs.values_list("ixlan__ix_id", flat=True))
        ix_qs = InternetExchange.objects.filter(id__in=ix_ids, status="ok")
        ix_map = {ix.id: ix for ix in ix_qs}

        # Group netixlan by ix_id
        ix_groups = {}
        for netixlan in netixlan_qs:
            ix_id = netixlan.ixlan.ix_id
            ix_groups.setdefault(ix_id, []).append(netixlan)

        # Build matrix rows
        matrix = []
        for ix_id, netixlans in ix_groups.items():
            ix = ix_map.get(ix_id)
            if not ix:
                continue

            row = collections.OrderedDict()
            row["Exchange ID"] = ix_id
            row["Exchange Name"] = ix.name
            row["City"] = ix.city

            # Init all asn columns as False
            for asn in asn_list:
                row[f"AS{asn}"] = False

            # Mark present ASNs
            present_asns = set()
            for netixlan in netixlans:
                asn = netixlan.network.asn
                if asn in asn_list:
                    row[f"AS{asn}"] = True
                    present_asns.add(asn)

            # Apply filters
            asn_count = len(present_asns)
            total_asns = len(asn_list)

            if not self._row_filters_asn_connectivity(
                asn_count, total_asns, match_filter, hide_unmatched
            ):
                continue

            matrix.append(row)

        # Sort by exchange name
        matrix.sort(key=lambda r: r["Exchange Name"].lower())
        return matrix

    def _generate_facility_connectivity(self, asn_list, match_filter, hide_unmatched):
        """
        Generate facility connectivity matrix for given ASN list.

        Arguments:
            - asn_list: List of ASN integers to check connectivity for
            - match_filter: Filter type ('show-all', 'any-match', 'all-match')
            - hide_unmatched: Whether to hide rows with no matches

        Returns:
            - list: Matrix rows with facility connectivity data
        """
        # Query all netfac for these ASNs
        netfac_qs = NetworkFacility.objects.filter(
            network__asn__in=asn_list, status="ok"
        )
        facility_ids = set(netfac_qs.values_list("facility_id", flat=True))
        fac_qs = Facility.objects.filter(id__in=facility_ids, status="ok")
        fac_map = {fac.id: fac for fac in fac_qs}

        # Group netfac by facility_id
        facility_groups = {}
        for netfac in netfac_qs:
            facility_groups.setdefault(netfac.facility_id, []).append(netfac)

        # Build matrix rows
        matrix = []
        for facility_id, netfacs in facility_groups.items():
            fac = fac_map.get(facility_id)
            if not fac:
                continue

            row = collections.OrderedDict()
            row["Facility ID"] = facility_id
            row["Facility Name"] = fac.name
            row["City"] = fac.city
            row["Country"] = fac.country

            # Init all asn columns as False
            for asn in asn_list:
                row[f"AS{asn}"] = False

            # Mark present ASNs
            present_asns = set()
            for netfac in netfacs:
                asn = netfac.network.asn
                if asn in asn_list:
                    row[f"AS{asn}"] = True
                    present_asns.add(asn)

            # Apply filters
            asn_count = len(present_asns)
            total_asns = len(asn_list)

            if not self._row_filters_asn_connectivity(
                asn_count, total_asns, match_filter, hide_unmatched
            ):
                continue

            matrix.append(row)

        # Sort by facility name
        matrix.sort(key=lambda r: r["Facility Name"].lower())
        return matrix

    def generate_asn_connectivity(self, request):
        """
        Export ASN connectivity as a matrix: Facility/Exchange vs ASN (true/false)
        Supports filter parameters:
        - match_filter: 'show-all', 'any-match', or 'all-match'
        - hide_unmatched: '1' or 'true' to hide facilities/exchanges with no matches

        This export matches the filtered view shown in the frontend table.
        """
        # Parse and validate ASN list
        asn_list_str = request.GET.get("asn_list", "")
        asn_list = [
            asn.strip() for asn in asn_list_str.split(",") if asn.strip().isdigit()
        ]
        if not asn_list:
            return []
        asn_list = [int(asn) for asn in asn_list]

        # Get request parameters
        connectivity_type = request.GET.get("connectivity_type", "facilities")
        match_filter = request.GET.get("match_filter", "show-all")
        hide_unmatched = request.GET.get("hide_unmatched", "").lower() in ["1", "true"]

        # Generate appropriate connectivity matrix
        if connectivity_type == "exchanges":
            return self._generate_exchange_connectivity(
                asn_list, match_filter, hide_unmatched
            )
        else:
            return self._generate_facility_connectivity(
                asn_list, match_filter, hide_unmatched
            )


def kmz_download(request):
    """
    Will return a file download of the KMZ file located at
    settings.KMZ_EXPORT_FILE if it exists.

    Will also send cache headers based on the file's modification time
    """

    try:
        with open(settings.KMZ_EXPORT_FILE, "rb") as file:
            response = HttpResponse(
                file.read(), content_type="application/vnd.google-earth.kmz"
            )
            response["Content-Disposition"] = (
                f'attachment; filename="{os.path.basename(settings.KMZ_EXPORT_FILE)}"'
            )
            response["Last-Modified"] = datetime.datetime.fromtimestamp(
                os.path.getmtime(settings.KMZ_EXPORT_FILE)
            ).strftime("%a, %d %b %Y %H:%M:%S GMT")
            return response
    except OSError:
        return HttpResponse(status=404)
