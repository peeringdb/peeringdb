import json
import base64

from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth import authenticate

from django_namespace_perms.util import has_perms
from ratelimit.decorators import ratelimit, is_ratelimited

from peeringdb_server import ixf
from peeringdb_server.models import (
    IXLan,
    Network,
    NetworkIXLan,
)

RATELIMITS = settings.RATELIMITS


def enable_basic_auth(fn):
    """
    a simple decorator to enable basic auth for a specific view
    """

    def wrapped(request, *args, **kwargs):
        if "HTTP_AUTHORIZATION" in request.META:
            auth = request.META["HTTP_AUTHORIZATION"].split()
            if len(auth) == 2:
                if auth[0].lower() == "basic":
                    username, password = base64.b64decode(auth[1]).split(":", 1)
                    request.user = authenticate(username=username, password=password)
                    if not request.user:
                        return JsonResponse(
                            {"non_field_errors": ["Invalid credentials"]}, status=401
                        )
        return fn(request, *args, **kwargs)

    return wrapped


def pretty_response(data):
    return HttpResponse(json.dumps(data, indent=2), content_type="application/json")


def error_response(msg, status=400):
    return JsonResponse({"non_field_errors": [msg]}, status=status)


@ratelimit(
    key="ip", rate=RATELIMITS["view_import_ixlan_ixf_preview"], group="ixf_preview"
)
@enable_basic_auth
def view_import_ixlan_ixf_preview(request, ixlan_id):

    # check if request was blocked by rate limiting
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return error_response(
            _("Please wait a bit before requesting " "another ixf import preview."),
            status=400,
        )

    try:
        ixlan = IXLan.objects.get(id=ixlan_id)
    except IXLan.DoesNotExist:
        return error_response(_("Ixlan not found"), status=404)

    if not has_perms(request.user, ixlan, "update"):
        return error_response(_("Permission denied"), status=403)

    importer = ixf.Importer()
    importer.update(ixlan, save=False)

    return pretty_response(importer.log)


@ratelimit(
    key="ip", rate=RATELIMITS["view_import_net_ixf_postmortem"], group="ixf_postmortem"
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

    if not has_perms(request.user, net, "update"):
        return error_response(_("Permission denied"), status=403)

    # make sure limit is within bounds and a valid number

    try:
        limit = int(request.GET.get("limit", 25))
    except:
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
    key="ip", rate=RATELIMITS["view_import_ixlan_ixf_preview"], group="ixf_preview"
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

    if not has_perms(request.user, net, "update"):
        return error_response(_("Permission denied"), status=403)

    total_log = {"data": [], "errors": []}

    for ixlan in net.ixlan_set_ixf_enabled:
        importer = ixf.Importer()
        importer.cache_only = True
        success = importer.update(
            ixlan, asn=net.asn, save=False
        )

        # strip suggestions
        log_data = [i for i in importer.log["data"] if not "suggest-" in i["action"]]

        total_log["data"].extend(log_data)
        total_log["errors"].extend(
            ["{}({}): {}".format(ixlan.ix.name, ixlan.id, err) for err in importer.log["errors"]]
        )

    return pretty_response(total_log)
