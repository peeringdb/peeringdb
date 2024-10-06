import datetime
import random

import bleach
import markdown
import tld
from allauth.account.models import EmailAddress
from django import template
from django.conf import settings as dj_settings
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django_countries import countries
from django_grainy.helpers import int_flags

from peeringdb_server.inet import RdapException
from peeringdb_server.models import (
    PARTNERSHIP_LEVELS,
    EnvironmentSetting,
    Facility,
    InternetExchange,
    Network,
    Organization,
    format_speed,
)
from peeringdb_server.org_admin_views import permission_ids
from peeringdb_server.views import DoNotRender

countries_dict = dict(countries)

register = template.Library()


@register.filter
def editable_list_join(value):
    if not value:
        return ""
    return ",".join(value)


@register.filter
def editable_list_value(row):
    if row.get("multiple"):
        if row.get("value"):
            return ", ".join(row.get("value"))
        return ""

    if row.get("value") or row.get("value_label"):
        return _(row.get("value_label", row.get("value")))
    elif row.get("blank") and row.get("value") == "":
        return row.get("blank")
    return ""


@register.filter
def shuffle(val):
    rmp = [r for r in val]
    random.shuffle(rmp)
    return rmp


@register.filter
def blank_sub(val, row):
    if val == "" and row.get("blank"):
        return row.get("blank")
    return val


@register.filter
def org_permission_id_xl(org, id):
    return permission_ids(org).get(id)


@register.filter
def check_perms(v, op):
    flg = int_flags(op)
    return v & flg == flg


@register.filter
def user_org_group(org, user):
    if org.admin_usergroup.user_set.filter(id=user.id).exists():
        return "admin"
    elif org.usergroup.user_set.filter(id=user.id).exists():
        return "member"
    return ""


@register.filter
def ownership_warning(org, user):
    email_domain = user.email.split("@")[1]
    b = False
    for url in [tld.get_tld(u) for u in org.urls]:
        if email_domain == url:
            b = True
            break
    if not b:
        for rdap in list(org.rdap_collect.values()):
            try:
                if user.validate_rdap_relationship(rdap):
                    b = True
                    break
            except RdapException:
                # we don't need to do anything with the rdap exception here, as it will
                # be raised apropriately when the request is sent off
                pass

    if not b:
        return mark_safe(
            '<span class="attention">{}</span>'.format(
                _(
                    "Your email address does not match the domain information we have on file for this organization."
                )
            )
        )
    return ""


@register.filter
def long_country_name(v):
    if isinstance(v, str):
        return countries_dict.get(v, v)
    else:
        return v.name


@register.filter
def as_bool(v):
    if not v or v == "0":
        return False
    return True


@register.filter
def fallback(a, b):
    if not a:
        return b
    return a


@register.filter
def is_dict(value):
    return isinstance(value, dict)


@register.filter
def is_bool(value):
    return isinstance(value, bool)


@register.filter
def is_none(value):
    return type(value) is None


@register.filter
def none_blank(value):
    if value is None:
        return ""
    return value


@register.filter
def dont_render(value):
    return type(value) is DoNotRender


@register.filter
def age(dt):
    seconds = (datetime.datetime.now().replace(tzinfo=dt.tzinfo) - dt).total_seconds()
    if seconds < 60:
        return "%d %s" % (seconds, _("seconds ago"))
    elif seconds < 3600:
        return "%d %s" % (seconds / 60, _("minutes ago"))
    elif seconds < 86400:
        return "%d %s" % (seconds / 3600, _("hours ago"))
    else:
        return "%d %s" % (seconds / 86400, _("days ago"))


@register.filter
def ref_tag(value):
    if hasattr(value, "_handleref"):
        return value._handleref.tag
    elif value == "InternetExchange":
        return InternetExchange.handleref.tag
    elif value == "Network":
        return Network.handleref.tag
    elif value == "Facility":
        return Facility.handleref.tag
    elif value == "Organization":
        return Organization.handleref.tag
    return "unknown"


@register.filter
def autocomplete_preload_net(value):
    """
    Prefill autocomplete-network field value for
    multi-select field
    """

    if not value:
        return ""

    qset = Network.objects.filter(status="ok", id__in=value.split(","))

    return ",".join([f"{net.id};{net.name}" for net in qset])


@register.filter
def autocomplete_preload_org_single(value):
    """
    Prefill autocomplete-organization field value for
    single-select field
    """

    if not value:
        return ""

    try:
        org = Organization.objects.get(status="ok", id=value)
        return org.name
    except ValueError:
        return value
    except Organization.DoesNotExist:
        return ""


@register.filter
def pretty_speed(value):
    if not value:
        return ""
    try:
        return format_speed(value)
    except ValueError:
        return value


@register.filter
def partnership_label(level):
    return dict(PARTNERSHIP_LEVELS).get(level, "Unknown")


@register.filter
def render_markdown(value):
    markdown_tags = [
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "b",
        "i",
        "strong",
        "em",
        "tt",
        "p",
        "br",
        "span",
        "div",
        "blockquote",
        "code",
        "hr",
        "ul",
        "ol",
        "li",
        "dd",
        "dt",
        "a",
    ]
    return bleach.clean(
        markdown.markdown(value), tags=markdown_tags, protocols=["http", "https"]
    )


@register.filter
def org_emails(org, user):
    return org.user_meets_email_requirements(user)


@register.filter
def org_restricted_emails(org, user):
    user_org_emails = org.user_meets_email_requirements(user)
    return user_org_emails[0]


@register.filter
def email_confirmed(email):
    return EmailAddress.objects.filter(email=email, verified=True).exists()


@register.filter
def make_page_title(entity):
    """
    Returns a page title based on an entity instance
    such as a network or organization
    """

    if entity and hasattr(entity, "HandleRef"):
        if entity.HandleRef.tag == "net":
            return f"AS{entity.asn} - {entity.name} - PeeringDB"
        elif hasattr(entity, "name"):
            return f"{entity.name} - PeeringDB"


@register.filter
def make_page_title_for_search_result(request):
    """
    Returns a page title to use on the quick search results page
    """

    if request.GET.get("q"):
        return f"{request.GET.get('q')} - PeeringDB search"


@register.filter
def make_page_title_for_advanced_search_result(request):
    """
    Returns a page title to use on the advances search results page
    """

    if request.META.get("QUERY_STRING"):
        return f"{request.META['QUERY_STRING']} - PeeringDB search"


@register.filter
def social_media_link(identifier, service):
    """
    Takes a sociail media identifier (service user name or url) and
    renders the service url

    For `website` it will just render a html link with the url as is, for services

    For the services facebook, x, instagram, linkedIn and tiktok
    it will render a html link to the url to the service.

    Arguments:
    - identifier (str): The identifier to render (url or username relevant to the service)
    - service (str): The service to render the identifier for
    """

    if service == "website":
        return mark_safe(f'<a href="{identifier}" target="_blank">{identifier}</a>')
    if service == "facebook":
        return mark_safe(
            f'<a href="https://www.facebook.com/{identifier}" target="_blank">{identifier}</a>'
        )
    if service == "x":
        return mark_safe(
            f'<a href="https://x.com/{identifier}" target="_blank">{identifier}</a>'
        )
    if service == "instagram":
        return mark_safe(
            f'<a href="https://www.instagram.com/{identifier}" target="_blank">{identifier}</a>'
        )
    if service == "linkedin":
        return mark_safe(
            f'<a href="https://www.linkedin.com/company/{identifier}" target="_blank">{identifier}</a>'
        )
    if service == "tiktok":
        return mark_safe(
            f'<a href="https://www.tiktok.com/@{identifier}" target="_blank" >{identifier}</a>'
        )

    return identifier


@register.filter
def ix_routeservers(ix):
    return ix.ixlan.netixlan_set_active.filter(is_rs_peer=True).count()


@register.filter
def prefix(ix):
    prefixes = ix.ixlan.ixpfx_set_active
    return prefixes


@register.filter
def obj_type(ref_tag):
    obj_types = {
        "org": "Organization",
        "net": "Network",
        "ix": "Internet Exchange",
        "fac": "Facility",
        "carrier": "Carrier",
        "campus": "Campus",
    }
    return obj_types[ref_tag]


@register.simple_tag(takes_context=True)
def server_email(context):
    return dj_settings.SERVER_EMAIL


@register.filter
def flag_bad_data_needs_auth(authenticated):
    if dj_settings.FLAG_BAD_DATA_NEEDS_AUTH:
        if authenticated:
            return True
        else:
            return False
    else:
        return True


@register.simple_tag(name="last_database_sync")
def last_database_sync():
    last_db_sync = dj_settings.DATABASE_LAST_SYNC
    if not last_db_sync:
        value_db = EnvironmentSetting.objects.filter(
            setting="DATABASE_LAST_SYNC"
        ).first()
        if value_db:
            last_db_sync = value_db.value
    formatted_date = None
    if last_db_sync:
        formatted_date = datetime.datetime.strptime(last_db_sync, "%Y-%m-%dT%H:%M:%S")
    return formatted_date


@register.filter
def objfac_tupple_fac_length(ixfac, exchanges_values):
    related_fac = sum(sublist.count(ixfac) for sublist in exchanges_values)
    return related_fac


@register.filter
def objfac_value_length(values):
    total = []
    for x in values:
        total = total + x
    return len(total)


@register.filter
def get_user_initial(username):
    return username[0].upper()
