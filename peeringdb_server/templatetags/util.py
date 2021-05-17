from django import template
from django.utils.translation import ugettext_lazy as _
from django.utils.safestring import mark_safe
import datetime
from peeringdb_server.models import (
    InternetExchange,
    Network,
    Facility,
    Organization,
    PARTNERSHIP_LEVELS,
    format_speed,
)

from peeringdb_server.views import DoNotRender
from peeringdb_server.org_admin_views import permission_ids
from peeringdb_server.inet import RdapException
from django_countries import countries
from django_namespace_perms.util import get_permission_flag
import tld
import random
import markdown
import bleach

countries_dict = dict(countries)

register = template.Library()


@register.filter
def editable_list_value(row):
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
    flg = get_permission_flag(op)
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
            except RdapException as exc:
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
    if type(v) == str:
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
    return type(value) == dict


@register.filter
def is_bool(value):
    return type(value) == bool


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
    if not value:
        return ""

    qset = Network.objects.filter(status="ok", id__in=value.split(","))

    return ",".join([
        f"{net.id};{net.name}" for net in qset
    ])



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
