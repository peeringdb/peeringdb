"""
Define IX-F import preview, review and post-mortem views.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.translation import gettext_lazy as _
from django_ratelimit.decorators import ratelimit

from peeringdb_server import ixf
from peeringdb_server.auth import enable_api_key_auth, enable_basic_auth
from peeringdb_server.models import IXLan, Network
from peeringdb_server.util import check_permissions

if TYPE_CHECKING:
    from django.utils.functional import Promise

RATELIMITS: dict[str, str] = settings.RATELIMITS


def pretty_response(data: dict[str, Any]) -> HttpResponse:
    # Any value: importer log is an arbitrary JSON-serializable payload
    return HttpResponse(json.dumps(data, indent=2), content_type="application/json")


def error_response(msg: str | Promise, status: int = 400) -> JsonResponse:
    # msg is usually a lazy gettext proxy (Promise), sometimes a plain str.
    return JsonResponse({"non_field_errors": [msg]}, status=status)


@ratelimit(
    key="ip",
    rate=RATELIMITS["view_import_ixlan_ixf_preview"],
    group="ixf_preview",
    block=False,
)
@enable_api_key_auth
@enable_basic_auth
def view_import_ixlan_ixf_preview(request: HttpRequest, ixlan_id: str) -> HttpResponse:
    # Check if request was blocked by rate limiting
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return error_response(
            _("Please wait a bit before requesting another ixf import preview."),
            status=400,
        )

    try:
        ixlan = IXLan.objects.get(id=ixlan_id)
    except IXLan.DoesNotExist:
        return error_response(_("Ixlan not found"), status=404)

    if hasattr(request, "org"):
        if request.org != ixlan.ix.org:
            return error_response(_("Permission denied"), status=403)
    elif not check_permissions(request.user, ixlan, "u"):
        return error_response(_("Permission denied"), status=403)

    # the preview never fetches the URL itself: it shows the data the last
    # import or requested refresh fetched (see request_ixf_import)
    importer = ixf.Importer()
    importer.cache_only = True
    importer.update(ixlan, save=False)

    entry = ixlan.ixf_cached_entry
    request_status, _display = ixlan.ix.ixf_import_request_recent_status

    if not entry and ixlan.ixf_ixp_member_list_url:
        importer.log["errors"] = [
            str(
                _(
                    "No IX-F data has been fetched for this LAN yet. Request an import to fetch it."
                )
            )
        ]

    # failed fetches are not cached, so the last error is shown from the LAN
    if ixlan.ixf_ixp_import_error:
        importer.log["errors"].insert(
            0,
            str(_("Last IX-F fetch or import failed: {}")).format(
                ixlan.ixf_ixp_import_error
            ),
        )

    return pretty_response(
        {
            **importer.log,
            "ix_id": ixlan.ix_id,
            "fetched": entry.get("fetched") if entry else None,
            "request_status": request_status,
        }
    )


@ratelimit(
    key="ip",
    rate=RATELIMITS["view_import_net_ixf_postmortem"],
    group="ixf_postmortem",
    block=False,
)
@enable_basic_auth
def view_import_net_ixf_postmortem(request: HttpRequest, net_id: str) -> HttpResponse:
    # check if request was blocked by rate limiting

    was_limited = getattr(request, "limited", False)
    if was_limited:
        return error_response(
            _("Please wait a bit before requesting another IX-F import postmortem."),
            status=400,
        )

    # load net

    try:
        net = Network.objects.get(id=net_id, status="ok")
    except Network.DoesNotExist:
        return error_response(_("Network not found"), status=404)

    if not check_permissions(request.user, net, "u"):
        return error_response(_("Permission denied"), status=403)

    # make sure limit is within bounds and a valid number

    try:
        limit = int(request.GET.get("limit", 25))
    except Exception:
        limit = 25

    errors: list[str] = []

    if limit < 1:
        limit = 1

    elif limit > settings.IXF_POSTMORTEM_LIMIT:
        errors.append(
            _("Postmortem length cannot exceed {} entries").format(
                settings.IXF_POSTMORTEM_LIMIT
            )
        )

    post_mortem = ixf.PostMortem()
    log = post_mortem.generate(net.asn, limit=limit)

    return pretty_response({"data": log, "non_field_errors": errors})


@ratelimit(
    key="ip",
    rate=RATELIMITS["view_import_ixlan_ixf_preview"],
    group="ixf_preview",
    block=False,
)
@enable_basic_auth
def view_import_net_ixf_preview(request: HttpRequest, net_id: str) -> HttpResponse:
    # check if request was blocked by rate limiting
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return error_response(
            _("Please wait a bit before requesting another ixf import preview."),
            status=400,
        )

    try:
        net = Network.objects.get(id=net_id, status="ok")
    except Network.DoesNotExist:
        return error_response(_("Network not found"), status=404)

    if not check_permissions(request.user, net, "u"):
        return error_response(_("Permission denied"), status=403)

    # list[Any]: "data" holds importer log-entry dicts, "errors" holds strings.
    total_log: dict[str, list[Any]] = {"data": [], "errors": []}

    for ixlan in net.ixlan_set_ixf_enabled:
        importer = ixf.Importer()
        importer.cache_only = True
        importer.update(ixlan, asn=net.asn, save=False)

        # strip suggestions
        log_data = [i for i in importer.log["data"] if "suggest-" not in i["action"]]

        total_log["data"].extend(log_data)
        total_log["errors"].extend(
            [f"{ixlan.ix.name}({ixlan.id}): {err}" for err in importer.log["errors"]]
        )

    return pretty_response(total_log)
