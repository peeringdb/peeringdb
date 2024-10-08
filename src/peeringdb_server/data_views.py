"""
This holds JSON views for various data sets.

These are needed for filling form-selects for editable
mode in UX.
"""

import django_countries
import django_peeringdb.const as const
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from peeringdb_server.models import Network, Organization, Sponsorship

from . import models

# def _(x):
#    return x

# until django-peeringdb is updated we want to remove
# the 100+ Gbps choice since it's redundant
const.TRAFFIC = [(k, i) for k, i in const.TRAFFIC if k != "100+ Gbps"]

# create enums without duplicate "Not Disclosed" choices
const.RATIOS_TRUNC = const.RATIOS[1:]
const.SCOPES_TRUNC = const.SCOPES[1:]
const.NET_TYPES_TRUNC = const.NET_TYPES[1:]
const.SERVICE_LEVEL_TYPES_TRUNC = const.SERVICE_LEVEL_TYPES[1:]
const.TERMS_TYPES_TRUNC = const.TERMS_TYPES[1:]

# create enums without duplicate "Not Disclosed" choices
# but with the one Not Disclosed choice combining both
# values in a comma separated fashion - user for
# advanced search
const.RATIOS_ADVS = list(const.RATIOS[1:])
const.RATIOS_ADVS[0] = (",%s" % const.RATIOS_ADVS[0][0], const.RATIOS_ADVS[0][1])
const.SCOPES_ADVS = list(const.SCOPES[1:])
const.SCOPES_ADVS[0] = (",%s" % const.SCOPES_ADVS[0][0], const.SCOPES_ADVS[0][1])
const.NET_TYPES_ADVS = list(const.NET_TYPES[1:])
const.NET_TYPES_ADVS[0] = (
    ",%s" % const.NET_TYPES_ADVS[0][0],
    const.NET_TYPES_ADVS[0][1],
)
const.SERVICE_LEVEL_TYPES_ADVS = list(const.SERVICE_LEVEL_TYPES[1:])
const.SERVICE_LEVEL_TYPES_ADVS[0] = (
    f",{const.SERVICE_LEVEL_TYPES_ADVS[0][0]}",
    const.SERVICE_LEVEL_TYPES_ADVS[0][1],
)
const.TERMS_TYPES_ADVS = list(const.TERMS_TYPES[1:])
const.TERMS_TYPES_ADVS[0] = (
    f",{const.TERMS_TYPES_ADVS[0][0]}",
    const.TERMS_TYPES_ADVS[0][1],
)


const.ORG_GROUPS = (("member", "member"), ("admin", "admin"))

const.POC_ROLES = sorted(const.POC_ROLES, key=lambda x: x[1])
const.POC_VISIBILITY = [r for r in const.VISIBILITY if r[0] != "Private"]

BOOL_CHOICE = ((False, _("No")), (True, _("Yes")))
const.BOOL_CHOICE_STR = (("False", _("No")), ("True", _("Yes")))

BOOL_CHOICE_WITH_OPT_OUT = (
    (None, _("Not Disclosed")),
    (False, _("No")),
    (True, _("Yes")),
)
const.BOOL_CHOICE_WITH_OPT_OUT_STR = (
    ("", _("Not Disclosed")),
    ("False", _("No")),
    ("True", _("Yes")),
)

const.REAUTH_PERIODS = models.REAUTH_PERIODS


def countries_w_blank(request):
    """
    Return all valid countries and their country codes with a blank field.
    """

    return JsonResponse(
        {
            "countries_b": [{"id": "", "name": ""}]
            + [
                {"id": str(code), "name": str(name)}
                for code, name in list(django_countries.countries)
            ]
        }
    )


def countries(request):
    """
    Return all valid countries and their country codes.
    """

    return JsonResponse(
        {
            "countries": [
                {"id": str(code), "name": str(name)}
                for code, name in list(django_countries.countries)
            ]
        }
    )


def sponsorships(request):
    """
    Return all sponsorships.
    """

    sponsors = {}
    for org, sponsorship in Sponsorship.active_by_org():
        sponsors[org.id] = {
            "id": org.id,
            "name": sponsorship.label.lower(),
            "css": sponsorship.css,
        }

    return JsonResponse(
        {
            "sponsors": sponsors,
        }
    )


@login_required
def facilities(request):
    """
    Return all valid facilities with id and name.
    """

    return JsonResponse(
        {
            "facilities": [
                {"id": fac.id, "name": str(fac.name)}
                for fac in models.Facility.handleref.all().undeleted().order_by("name")
            ]
        }
    )


def enum(request, name):
    if name.upper() not in [
        "RATIOS",
        "RATIOS_TRUNC",
        "RATIOS_ADVS",
        "TRAFFIC",
        "SCOPES",
        "SCOPES_TRUNC",
        "SCOPES_ADVS",
        "NET_TYPES",
        "NET_TYPES_MULTI_CHOICE",
        "NET_TYPES_TRUNC",
        "NET_TYPES_ADVS",
        "POLICY_GENERAL",
        "POLICY_LOCATIONS",
        "POLICY_CONTRACTS",
        "REGIONS",
        "POC_ROLES",
        "MEDIA",
        "PROTOCOLS",
        "ORG_GROUPS",
        "BOOL_CHOICE_STR",
        "BOOL_CHOICE_WITH_OPT_OUT_STR",
        "VISIBILITY",
        "POC_VISIBILITY",
        "SERVICE_LEVEL_TYPES_TRUNC",
        "TERMS_TYPES_TRUNC",
        "SERVICE_LEVEL_TYPES_ADVS",
        "TERMS_TYPES_ADVS",
        "PROPERTY",
        "AVAILABLE_VOLTAGE",
        "REAUTH_PERIODS",
        "MTUS",
        "SOCIAL_MEDIA_SERVICES",
    ]:
        raise Exception("Unknown enum")

    return JsonResponse(
        {
            "enum/%s" % name: [
                {
                    "id": id,
                    # as of django-peeringdb 1.0.0 already comes in
                    # translated
                    "name": n,
                }
                for id, n in getattr(const, name.upper())
            ]
        }
    )


def asns(request):
    """
    Return a JSON response with a list of asns that the user's
    organizations own to use for selecting asn in netixlan
    creation.
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


def my_organizations(request):
    """
    Return a JSON response with a list of organization names and ids
    that the requesting user is a member of.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"my_organizations": []})

    return JsonResponse(
        {
            "my_organizations": [
                {"id": o.id, "name": o.name} for o in request.user.organizations
            ]
        }
    )


def organizations(request):
    """
    Return a JSON response with a list of organization names and ids.
    This is currently only used by the org-merge-tool which is only
    available to site administrators.
    """

    if not request.user.is_superuser:
        return JsonResponse({}, status=403)

    return JsonResponse(
        {
            "organizations": [
                {"id": o.id, "name": o.name}
                for o in Organization.objects.filter(status="ok").order_by("name")
            ]
        }
    )


def languages(request):
    from django.conf import settings

    locales = []
    for id, name in settings.LANGUAGES:
        li = translation.get_language_info(id)
        locales.append(
            {"id": id, "name": f"{li['name_translated']} ({li['name_local']})"}
        )

    return JsonResponse({"locales": locales})


def campus_facilities(request):
    """
    Returns a JSON response with a dict of facilities that are part
    of a campus
    """

    return JsonResponse(
        {
            "campus_facilities": {
                fac.id: {"campus_id": fac.campus_id, "name": str(fac.name)}
                for fac in models.Facility.handleref.all()
                .undeleted()
                .exclude(campus__isnull=True)
                .order_by("name")
            }
        }
    )
