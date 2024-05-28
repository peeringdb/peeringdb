import json
import os

from django.conf import settings

# import html escape
from django.utils.html import escape
from simplekml import Kml, Style

from peeringdb_server.util import add_kmz_overlay_watermark, generate_balloonstyle_text


def collect_exchanges(path=None):
    """
    This function collects all the exchanges and relates them to facilities.
    """

    if not path:
        path = settings.API_CACHE_ROOT

    cached_ix_path = f"{path}/ix-1.json"
    # relate ix to facilities
    mapping = {}
    with open(cached_ix_path) as file:
        data = json.load(file)
        for ix in data.get("data"):
            for fac_id in ix["fac_set"]:
                mapping.setdefault(fac_id, [])
                mapping[fac_id].append(escape(ix["name"]))

    return mapping


def collect_networks(path=None):
    """
    This function collects all the networks and relates them to facilities.
    """

    if not path:
        path = settings.API_CACHE_ROOT

    cached_net_path = f"{path}/net-2.json"
    # relate net to facilities
    mapping = {}
    with open(cached_net_path) as file:
        data = json.load(file)
        for net in data.get("data"):
            for netfac in net["netfac_set"]:
                fac_id = netfac["fac_id"]
                mapping.setdefault(fac_id, [])
                mapping[fac_id].append(escape(f"{net['name']} AS{net['asn']}"))

    return mapping


def collect_carriers(path=None):
    """
    This function collects all the carriers and relates them to facilities.
    """
    if not path:
        path = settings.API_CACHE_ROOT

    cached_carrier_path = f"{path}/carrier-2.json"

    # relate carrier to facilities
    mapping = {}
    with open(cached_carrier_path) as file:
        data = json.load(file)
        for carrier in data.get("data"):
            for carrierfac in carrier["carrierfac_set"]:
                fac_id = carrierfac["fac_id"]
                mapping.setdefault(fac_id, [])
                mapping[fac_id].append(escape(carrier["name"]))

    return mapping


def fac_export_kmz(limit=None, path=None, output_dir=None):
    """
    This function exports facility data to a KMZ file.
    It reads the facility data from a JSON file, creates a KML object, and adds points to a folder in the KML.
    Each point represents a facility with its name, notes, and coordinates.
    The KML is then saved as a KMZ file.

    If `output_dir` is not passed, it uses `path`
    """

    if not path:
        path = settings.API_CACHE_ROOT
    if not output_dir:
        output_dir = path

    cached_fac_path = f"{path}/fac-0.json"

    ix_fac = collect_exchanges(path=path)
    net_fac = collect_networks(path=path)
    carrier_fac = collect_carriers(path=path)

    with open(cached_fac_path) as file:
        data = json.load(file)

    kml = Kml()
    fac_folder = kml.newfolder(name="Facilities")
    style = Style()
    add_kmz_overlay_watermark(kml)
    include_keys = [
        "org_name",
        "peeringDB",
        "website",
        "net_count",
        "ix_count",
        "address1",
        "city",
        "country",
        "state",
        "zipcode",
        "latitude",
        "longitude",
    ]
    rename_key = {
        "net_count": "Networks",
        "ix_count": "Exchanges",
        "address1": "Address",
        "org_name": "name",
    }

    filtered_keys = []
    for fac in data.get("data")[:limit]:
        if fac.get("latitude") and fac.get("longitude"):
            fac.update(
                {
                    "peeringDB": f"https://peeringdb.com/fac/{fac.get('id')}",
                }
            )
            # Add a new point to the "Facilities" folder
            point = fac_folder.newpoint(
                name=fac.get("org_name"),
                description=fac.get("notes"),
                coords=[(fac.get("longitude"), fac.get("latitude"))],
            )

            for key in include_keys:
                value = fac.get(key, "")
                if not isinstance(value, (int, str, float)):
                    continue

                key_name = rename_key.get(key, key)

                if key_name not in filtered_keys:
                    filtered_keys.append(key_name)
                point.extendeddata.newdata(
                    name=key_name, value=escape(value), displayname=key_name.title()
                )

            point.style = style
    style.balloonstyle.text = generate_balloonstyle_text(filtered_keys)
    fac_folder.balloonstyle = None

    kml.savekmz(f"{output_dir}/peeringdb.kmz")
