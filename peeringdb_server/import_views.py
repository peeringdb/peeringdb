import json

from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils.translation import ugettext_lazy as _

from django_namespace_perms.util import has_perms
from ratelimit.decorators import ratelimit, is_ratelimited

from peeringdb_server import ixf
from peeringdb_server.models import IXLan

RATELIMITS = settings.RATELIMITS


@ratelimit(key="ip", rate=RATELIMITS["view_import_ixlan_ixf_preview"])
def view_import_ixlan_ixf_preview(request, ixlan_id):

    # check if request was blocked by rate limiting
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return JsonResponse({
            "non_field_errors": [
                _("Please wait a bit before requesting " \
                  "another ixf import preview.")
            ]
        }, status=400)

    try:
        ixlan = IXLan.objects.get(id=ixlan_id)
    except IXLan.DoesNotExist:
        return JsonResponse({
            "non_field_errors": [_("Ixlan not found")]
        }, status=404)

    if not has_perms(request.user, ixlan, "update"):
        return JsonResponse({
            "non_field_errors": [_("Permission denied")]
        }, status=403)

    importer = ixf.Importer()
    importer.update(ixlan, save=False)

    return HttpResponse(
        json.dumps(importer.log, indent=2), content_type="application/json")
