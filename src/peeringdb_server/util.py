"""
Assorted utility functions for peeringdb site templates.
"""

import ipaddress
from decimal import Decimal

import django_peeringdb.const as const
from django.contrib.staticfiles.finders import find
from django.utils.translation import gettext_lazy as _
from django_grainy.util import Permissions, check_permissions, get_permissions  # noqa
from simplekml import Kml, OverlayXY, ScreenXY, Style, Units

from peeringdb_server.models import (
    CarrierFacility,
    InternetExchangeFacility,
    NetworkFacility,
)
from peeringdb_server.permissions import APIPermissionsApplicator  # noqa


def disable_auto_now_and_save(entity):
    updated_field = entity._meta.get_field("updated")
    updated_field.auto_now = False
    try:
        entity.save()
    finally:
        updated_field.auto_now = True


def round_decimal(value, places):
    if value is not None:
        return value.quantize(Decimal(10) ** -places)
    return value


def coerce_ipaddr(value):
    """
    ipaddresses can have multiple formats that are equivalent.
    This function will standardize a ipaddress string.

    Note: this function is not a validator. If it errors
    It will return the original string.
    """
    try:
        value = str(ipaddress.ip_address(value))
    except ValueError:
        pass
    return value


def v2_social_media_services():
    """
    Until v3 website is still set through the main `website` property
    of the object, we need to skip it here so it is not rendered to
    the UX as a pickable choice in the social media dropdown
    """
    return [x for x in const.SOCIAL_MEDIA_SERVICES if x[0] != "website"]


def generate_social_media_render_data(data, social_media, insert_index, dismiss):
    """
    Generate the data for rendering the social media in view.html.
    This function will insert the generated social media data to `data`.
    """
    idx = insert_index
    social_media = social_media
    for i, soc in enumerate(social_media):
        # until v3 website is still set through the main `website`
        # field of the object, we need to skip it here so it
        # is not rendered to the UX twice

        if soc["service"] == "website":
            continue

        service = soc.get("service", dismiss)

        idx = idx + 1
        soc_data = {
            "name": f"sc_value_{i}",
            "value": soc.get("identifier", dismiss),
            "label": _(service.capitalize()),
            "editable_label": True,
            "type": "soc",
            "label_type": "list",
            "label_name": f"sc_field_{i}",
            "label_data": "enum/social_media_services",
            "label_value": service,
        }
        # if i == len(social_media) - 1:
        data.get("fields").insert(idx, soc_data)

    soc_data = {"last_soc_field": True}
    data.get("fields").insert(idx + 1, soc_data)
    return data


def objfac_tupple(objfac_qset, obj):
    data = {}
    for objfac in objfac_qset:
        if not data.get(getattr(objfac, obj)):
            data[getattr(objfac, obj)] = [objfac.facility]
        else:
            data[getattr(objfac, obj)].append(objfac.facility)
    return data


def generate_balloonstyle_text(keys):
    table_data = ""
    for key in keys:
        table_data += f"""
        <tr>
        <td>$[{key}/displayName]</td>
        <td>$[{key}]</td>
        </tr>
        """
    ballon_text = f"""
    <h3>$[name]</h3>
    $[description]
    </br>
    </br>
    <table border="1">
        <tbody>
            {table_data}
        </tbody>
    </table>
    """
    return ballon_text


def add_kmz_overlay_watermark(kml):
    """
    add overlay watermark in kmz

    Args:
        kml: Kml
    Returns:
       None
    """
    watermark_logo = find("pdb-logo-kmz.png")
    screen = kml.newscreenoverlay(name="https://peeringdb.com")
    logo_path = kml.addfile(watermark_logo)
    screen.icon.href = logo_path
    screen.overlayxy = OverlayXY(
        x=0.9, y=0.1, xunits=Units.fraction, yunits=Units.fraction
    )
    screen.screenxy = ScreenXY(
        x=0.98, y=0.05, xunits=Units.fraction, yunits=Units.fraction
    )
