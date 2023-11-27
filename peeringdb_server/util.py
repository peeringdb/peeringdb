"""
Assorted utility functions for peeringdb site templates.
"""
import ipaddress
from decimal import Decimal

import django_peeringdb.const as const
from django.utils.translation import gettext_lazy as _
from django_grainy.util import Permissions, check_permissions, get_permissions  # noqa

from peeringdb_server.permissions import APIPermissionsApplicator  # noqa
from peeringdb_server.models import CarrierFacility, NetworkFacility, InternetExchangeFacility


def disable_auto_now_and_save(entity):
    updated_field = entity._meta.get_field("updated")
    updated_field.auto_now = False
    entity.save()
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

        idx = idx + 1
        soc_data = {
            "name": f"sc_value_{i}",
            "value": soc.get("identifier", dismiss),
            "label": _(f'{soc.get("service", dismiss)}'.capitalize()),
            "editable_label": True,
            "type": "soc",
            "label_type": "list",
            "label_name": f"sc_field_{i}",
            "label_data": "enum/social_media_services",
            "label_value": soc.get("service", dismiss),
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
