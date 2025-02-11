"""
Define IX-F import preview, review and post-mortem views.
"""

import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.translation import gettext_lazy as _
from django_ratelimit.decorators import ratelimit

from peeringdb_server import ixf
from peeringdb_server.auth import enable_api_key_auth, enable_basic_auth
from peeringdb_server.models import IXLan, Network
from peeringdb_server.util import check_permissions

RATELIMITS = settings.RATELIMITS


def pretty_response(data):
    return HttpResponse(json.dumps(data, indent=2), content_type="application/json")


def error_response(msg, status=400):
    return JsonResponse({"non_field_errors": [msg]}, status=status)


@ratelimit(
    key="ip",
    rate=RATELIMITS["view_import_ixlan_ixf_preview"],
    group="ixf_preview",
    block=False,
)
@enable_api_key_auth
@enable_basic_auth
def view_import_ixlan_ixf_preview(request, ixlan_id):
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

    importer = ixf.Importer()
    importer.update(ixlan, save=False, timeout=settings.IXF_FETCH_TIMEOUT)

    return pretty_response(importer.log)


@ratelimit(
    key="ip",
    rate=RATELIMITS["view_import_net_ixf_postmortem"],
    group="ixf_postmortem",
    block=False,
)
@enable_basic_auth
def view_import_net_ixf_postmortem(request, net_id):
    # check if request was blocked by rate limiting

    was_limited = getattr(request, "limited", False)
    if was_limited:
        return error_response(
            _("Please wait a bit before requesting " "another IX-F import postmortem."),
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

    errors = []

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
def view_import_net_ixf_preview(request, net_id):
    # check if request was blocked by rate limiting
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return error_response(
            _("Please wait a bit before requesting " "another ixf import preview."),
            status=400,
        )

    try:
        net = Network.objects.get(id=net_id, status="ok")
    except Network.DoesNotExist:
        return error_response(_("Network not found"), status=404)

    if not check_permissions(request.user, net, "u"):
        return error_response(_("Permission denied"), status=403)

    total_log = {"data": [], "errors": []}

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
