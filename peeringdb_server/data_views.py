"""
This holds JSON views for various data sets,

Mostly these are needed for filling form-selects for editable
mode
"""
import datetime

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import django_countries
import models
import django_peeringdb.const as const
from django.utils import translation
from django.utils.translation import ugettext_lazy as _

from peeringdb_server.models import (
    Organization, Network, Sponsorship)

#def _(x):
#    return x

# until django-peeringdb is updated we want to remove
# the 100+ Gbps choice since it's redundant
const.TRAFFIC = [(k, i) for k, i in const.TRAFFIC if k != "100+ Gbps"]

# create enums without duplicate "Not Disclosed" choices
const.RATIOS_TRUNC = const.RATIOS[1:]
const.SCOPES_TRUNC = const.SCOPES[1:]
const.NET_TYPES_TRUNC = const.NET_TYPES[1:]

# create enums without duplicate "Not Disclosed" choices
# but with the one Not Disclosed choice combining both
# values in a comma separated fashion - user for
# advanced search
const.RATIOS_ADVS = list(const.RATIOS[1:])
const.RATIOS_ADVS[0] = (",%s" % const.RATIOS_ADVS[0][0],
                        const.RATIOS_ADVS[0][1])
const.SCOPES_ADVS = list(const.SCOPES[1:])
const.SCOPES_ADVS[0] = (",%s" % const.SCOPES_ADVS[0][0],
                        const.SCOPES_ADVS[0][1])
const.NET_TYPES_ADVS = list(const.NET_TYPES[1:])
const.NET_TYPES_ADVS[0] = (",%s" % const.NET_TYPES_ADVS[0][0],
                           const.NET_TYPES_ADVS[0][1])

const.ORG_GROUPS = (("member", "member"), ("admin", "admin"))

const.POC_ROLES = sorted(const.POC_ROLES, key=lambda x: x[1])

BOOL_CHOICE = ((False, _("No")), (True, _("Yes")))
const.BOOL_CHOICE_STR = (("False", _("No")), ("True", _("Yes")))


def countries_w_blank(request):
    """
    Returns all valid countries and their country codes with a blank field
    """

    return JsonResponse({
        "countries_b": [{
            "id": "",
            "name": ""
        }] + [{
            "id": unicode(code),
            "name": unicode(name)
        } for code, name in list(django_countries.countries)]
    })


def countries(request):
    """
    Returns all valid countries and their country codes
    """

    return JsonResponse({
        "countries": [{
            "id": unicode(code),
            "name": unicode(name)
        } for code, name in list(django_countries.countries)]
    })

def sponsorships(request):
    """
    Returns all sponsorships
    """

    now = datetime.datetime.now().replace(tzinfo=models.UTC())
    qset = Sponsorship.objects.filter(start_date__lte=now,
                                      end_date__gte=now)

    return JsonResponse({
        "sponsors": dict([(sponsor.org_id, {
            "id": sponsor.org_id,
            "name": sponsor.label.lower()
        }) for sponsor in qset])
    })

@login_required
def facilities(request):
    """
    Returns all valid facilities with id and name
    """

    return JsonResponse({
        "facilities": [{
            "id": fac.id,
            "name": unicode(fac.name)
        } for fac in models.Facility.handleref.all().undeleted()
                       .order_by("name")]
    })


def enum(request, name):

    if name.upper() not in [
            "RATIOS", "RATIOS_TRUNC", "RATIOS_ADVS", "TRAFFIC", "SCOPES",
            "SCOPES_TRUNC", "SCOPES_ADVS", "NET_TYPES", "NET_TYPES_TRUNC",
            "NET_TYPES_ADVS", "POLICY_GENERAL", "POLICY_LOCATIONS",
            "POLICY_CONTRACTS", "REGIONS", "POC_ROLES", "MEDIA", "PROTOCOLS",
            "ORG_GROUPS", "BOOL_CHOICE_STR", "VISIBILITY"
    ]:
        raise Exception("Unknown enum")

    return JsonResponse({
        "enum/%s" % name: [{
            "id": id,
            "name": _(n)
        } for id, n in getattr(const, name.upper())]
    })


def asns(request):
    """
    Returns a JSON response with a list of asns that the user's
    organizations own, to use for selecting asn in netixlan
    creation
    """
    rv = []
    try:
        net = Network.objects.get(id=request.GET.get("id"))
        org = net.org
    except Network.DoesNotExist:
        return JsonResponse({"asns": []})

    for net in org.net_set_active.order_by("asn"):
        rv.append({"id": net.asn, "name": net.asn})
    return JsonResponse({"asns": rv})


def organizations(request):
    """
    Returns a JSON response with a list of organization names and ids
    This is currently only used by the org-merge-tool which is only
    available to site administrators.
    """

    if not request.user.is_superuser:
        return JsonResponse({}, status=403)

    return JsonResponse({
        "organizations": [{
            "id": o.id,
            "name": o.name
        } for o in Organization.objects.filter(status="ok").order_by("name")]
    })


def languages(request):
    from django.conf import settings
    cur_language = translation.get_language()
    return JsonResponse({
        "locales": [{
            "id": id,
            "name": _(name)
        } for (id, name) in settings.LANGUAGES]
    })
