"""
Assorted utility functions for peeringdb site templates.
"""

import ipaddress
from decimal import Decimal

import django_peeringdb.const as const
from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.shortcuts import render as django_render
from django.template import loader
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


def objfac_tupple_ui_next(objfac_qset, obj, output):
    data = {}
    for objfac in objfac_qset:
        if output == "mixed":
            if not data.get(getattr(objfac, obj)):
                data[getattr(objfac, obj)] = [objfac.facility]
            else:
                data[getattr(objfac, obj)].append(objfac.facility)
        elif output == "grouped":
            if objfac.facility not in data:
                data[objfac.facility] = [getattr(objfac, obj)]
            else:
                data[objfac.facility].append(getattr(objfac, obj))
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


def resolve_template(request, template_name):
    """
    Resolves the template path based on user preferences for the UI version.

    This function checks whether the request should use the 'next' version
    of the UI templates (e.g., 'site_next/' or 'two_factor_next/') based on:
      - User flags (opt_flags with UI_NEXT and UI_NEXT_REJECTED),
      - or a global setting for unauthenticated users.

    Parameters:
        request (HttpRequest): The HTTP request object.
        template_name (str): The original template path.

    Returns:
        str: The resolved template path (may be modified to '..._next/').
    """
    UI_NEXT = getattr(settings, "USER_OPT_FLAG_UI_NEXT", 2)
    UI_NEXT_REJECTED = getattr(settings, "USER_OPT_FLAG_UI_NEXT_REJECTED", 4)
    DEFAULT_UI_NEXT_ENABLED = getattr(settings, "DEFAULT_UI_NEXT_ENABLED", False)

    user = getattr(request, "user", None)
    flags = getattr(user, "opt_flags", 0) if user and user.is_authenticated else 0

    use_ui_next = (
        (flags & UI_NEXT and not (flags & UI_NEXT_REJECTED))
        if user and user.is_authenticated
        else DEFAULT_UI_NEXT_ENABLED
    )

    if use_ui_next:
        if template_name.startswith("site/"):
            return template_name.replace("site/", "site_next/", 1)
        elif template_name.startswith("two_factor/"):
            return template_name.replace("two_factor/", "two_factor_next/", 1)

    return template_name


def render(request, template_name, context=None, *args, **kwargs):
    """
    Renders a template using UI version resolution based on request.

    This is a wrapper around Django's default render function that uses
    `resolve_template` to determine the correct template path.

    Parameters:
        request (HttpRequest): The HTTP request object.
        template_name (str): The original template path.
        context (dict, optional): The context data passed to the template.

    Returns:
        HttpResponse: The rendered template response.
    """
    return django_render(
        request, resolve_template(request, template_name), context, *args, **kwargs
    )


def get_template(request, template_name):
    """
    Loads a template using UI version resolution based on request.

    This is a wrapper around Django's template loader to resolve
    and load the correct template version (default or *_next).

    Parameters:
        request (HttpRequest): The HTTP request object.
        template_name (str): The original template path.

    Returns:
        Template: The Django template object.
    """
    return loader.get_template(resolve_template(request, template_name))
