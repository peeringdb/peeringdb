import json

from django.conf import settings

# import html escape
from django.utils.html import escape
from simplekml import Kml


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


def fac_export_kmz(limit=None, path=None):
    """
    This function exports facility data to a KMZ file.
    It reads the facility data from a JSON file, creates a KML object, and adds points to a folder in the KML.
    Each point represents a facility with its name, notes, and coordinates.
    The KML is then saved as a KMZ file.
    """

    if not path:
        path = settings.API_CACHE_ROOT

    cached_fac_path = f"{path}/fac-0.json"

    ix_fac = collect_exchanges(path=path)
    net_fac = collect_networks(path=path)
    carrier_fac = collect_carriers(path=path)

    with open(cached_fac_path) as file:
        data = json.load(file)

    kml = Kml()
    fac_folder = kml.newfolder(name="Facilities")

    exclude_keys = ["_grainy"]

    for fac in data.get("data")[:limit]:
        if fac.get("latitude") and fac.get("longitude"):
            # Add a new point to the "Facilities" folder
            point = fac_folder.newpoint(
                name=fac.get("name"),
                description=fac.get("notes"),
                coords=[(fac.get("longitude"), fac.get("latitude"))],
            )

            for key, value in fac.items():
                if key in exclude_keys:
                    continue

                if not isinstance(value, (int, str, float)):
                    continue

                # Add all the facility data as extended data to the point
                point.extendeddata.newdata(
                    name=key, value=escape(value), displayname=key.title()
                )

            # Include exchanges, networks, and carriers

            point.extendeddata.newdata(
                name="exchanges",
                value="\n".join(ix_fac.get(fac.get("id"), [])),
                displayname="Exchanges",
            )

            point.extendeddata.newdata(
                name="networks",
                value="\n".join(net_fac.get(fac.get("id"), [])),
                displayname="Networks",
            )

            point.extendeddata.newdata(
                name="carriers",
                value="\n".join(carrier_fac.get(fac.get("id"), [])),
                displayname="Carriers",
            )

    kml.savekmz(f"{path}/peeringdb.kmz")
