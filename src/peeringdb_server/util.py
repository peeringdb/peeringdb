"""
Assorted utility functions for peeringdb site templates.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import django_peeringdb.const as const
from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.shortcuts import render as django_render
from django.template import loader
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import cache_control
from django_grainy.util import Permissions, check_permissions, get_permissions  # noqa
from simplekml import OverlayXY, ScreenXY, Units

from peeringdb_server.permissions import APIPermissionsApplicator  # noqa

if TYPE_CHECKING:
    from django.db.models import Model
    from django.http import HttpRequest, HttpResponse
    from simplekml import Kml

# Session-bearing anonymous auth views must never be cached by shared
# proxies, since their responses carry `Set-Cookie` / CSRF state (#2032).
# Lives here rather than in `views` so `mainsite.urls` can import it
# without pulling in the heavy views module.
no_store_private: Callable[
    [Callable[..., HttpResponse]], Callable[..., HttpResponse]
] = cache_control(private=True, no_store=True)


def disable_auto_now_and_save(
    entity: Model, update_fields: Sequence[str] | None = None
) -> None:
    updated_field = entity._meta.get_field("updated")
    updated_field.auto_now = False
    try:
        if update_fields is not None:
            entity.save(update_fields=update_fields)
        else:
            entity.save()
    finally:
        updated_field.auto_now = True


def round_decimal(value: Decimal | None, places: int) -> Decimal | None:
    if value is not None:
        return value.quantize(Decimal(10) ** -places)
    return value


def coerce_ipaddr(value: str) -> str:
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


def v2_social_media_services() -> list[tuple[str, str]]:
    """
    Until v3 website is still set through the main `website` property
    of the object, we need to skip it here so it is not rendered to
    the UX as a pickable choice in the social media dropdown
    """
    return [x for x in const.SOCIAL_MEDIA_SERVICES if x[0] != "website"]


def generate_social_media_render_data(
    data: dict[str, Any],
    social_media: list[dict[str, Any]],
    insert_index: int,
    dismiss: str,
) -> dict[str, Any]:
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
        cast("list[dict[str, Any]]", data.get("fields")).insert(idx, soc_data)

    soc_data = {"last_soc_field": True}
    cast("list[dict[str, Any]]", data.get("fields")).insert(idx + 1, soc_data)
    return data


def objfac_tupple(objfac_qset: Iterable[Model], obj: str) -> dict[Model, list[Model]]:
    data: dict[Model, list[Model]] = {}
    for objfac in objfac_qset:
        if not data.get(getattr(objfac, obj)):
            data[getattr(objfac, obj)] = [objfac.facility]
        else:
            data[getattr(objfac, obj)].append(objfac.facility)
    return data


def objfac_tupple_ui_next(
    objfac_qset: Iterable[Model], obj: str, output: str
) -> dict[Model, list[Model]]:
    data: dict[Model, list[Model]] = {}
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


def generate_balloonstyle_text(keys: Iterable[str]) -> str:
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


def add_kmz_overlay_watermark(kml: Kml) -> None:
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


def resolve_template(request: HttpRequest, template_name: str) -> str:
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


def render(
    request: HttpRequest,
    template_name: str,
    context: dict[str, Any] | None = None,
    *args: Any,
    **kwargs: Any,
) -> HttpResponse:
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


# return is Any: loader.get_template returns a backend-specific template wrapper
# (django.template.backends.*.Template) with no clean shared public type.
def get_template(request: HttpRequest, template_name: str) -> Any:
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
