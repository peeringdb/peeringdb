"""
Autocomplete views.

Handle most autocomplete functionality found in peeringdb.

Note: Quick search behavior is specified in search.py
"""

import json
from itertools import chain
from operator import attrgetter

from dal import autocomplete
from django import http
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import IntegerField, Q, Value
from django.utils import html
from grappelli.views.related import AutocompleteLookup as GrappelliAutocomplete
from reversion.models import Version

from peeringdb_server.admin_commandline_tools import TOOL_MAP
from peeringdb_server.models import (
    REFTAG_MAP,
    CommandLineTool,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLan,
    Network,
    NetworkFacility,
    Organization,
)


class GrappelliHandlerefAutocomplete(GrappelliAutocomplete):
    """
    Make sure that the auto-complete fields managed
    by grappelli in django admin exclude soft-deleted
    objects.
    """

    def get_queryset(self):
        qs = super().get_queryset()

        if hasattr(self.model, "HandleRef"):
            qs = qs.exclude(status="deleted")

        return qs


class AutocompleteHTMLResponse(autocomplete.Select2QuerySetView):

    # Issue #469
    # Add IXP to AS record / dropdown limited
    paginate_by = 0

    def has_add_permissions(self, request):
        return False

    def render_to_response(self, context):
        self.request.GET.get("q", None)
        return http.HttpResponse(
            "".join([i.get("text") for i in self.get_results(context)]),
            content_type="text/html",
        )


class ExchangeAutocompleteJSON(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = InternetExchange.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        qs = qs.order_by("name")
        return qs


class ExchangeAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = InternetExchange.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        qs = qs.order_by("name")
        return qs

    def get_result_label(self, item):
        return '<span data-value="%d"><div class="main">%s</div></span>' % (
            item.pk,
            html.escape(item.name),
        )


class FacilityAutocompleteJSON(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Facility.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        qs = qs.order_by("name")
        return qs


class FacilityAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = Facility.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(Q(name__icontains=self.q) | Q(address1__icontains=self.q))
        qs = qs.order_by("name")
        return qs

    def get_result_label(self, item):
        return (
            '<span data-value="%d"><div class="main">%s</div> <div class="sub">%s</div></span>'
            % (item.pk, html.escape(item.name), html.escape(item.address1))
        )


class NetworkAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = Network.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(
                Q(name__icontains=self.q)
                | Q(aka__icontains=self.q)
                | Q(asn__iexact=self.q)
            )
        qs = qs.order_by("name")
        return qs

    def get_result_label(self, item):
        return '<span data-value="{}"><div class="main">{}</div> <div class="sub">AS{}</div></span>'.format(
            item.pk, html.escape(item.name), html.escape(item.asn)
        )


class FacilityAutocompleteForNetwork(FacilityAutocomplete):
    def get_queryset(self):
        qs = super().get_queryset()
        net_id = self.request.resolver_match.kwargs.get("net_id")
        fac_ids = [
            nf.facility_id
            for nf in NetworkFacility.objects.filter(status="ok", network_id=net_id)
        ]
        qs = qs.exclude(id__in=fac_ids)
        return qs


class FacilityAutocompleteForExchange(FacilityAutocomplete):
    def get_queryset(self):
        qs = super().get_queryset()
        ix_id = self.request.resolver_match.kwargs.get("ix_id")
        fac_ids = [
            nf.facility_id
            for nf in InternetExchangeFacility.objects.filter(status="ok", ix_id=ix_id)
        ]
        qs = qs.exclude(id__in=fac_ids)
        return qs


class OrganizationAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = Organization.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        qs = qs.order_by("name")
        return qs

    def get_result_label(self, item):
        return '<span data-value="%d"><div class="main">%s</div></span>' % (
            item.pk,
            html.escape(item.name),
        )


class IXLanAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):

        qs = IXLan.objects.filter(status="ok").select_related("ix")

        if self.q:

            exact_qs = (
                qs.filter(Q(ix__name__iexact=self.q))
                .only(
                    "pk",
                    "ix__name",
                    "ix__country",
                    "ix__name_long",
                )
                .annotate(filter_style=Value(1, IntegerField()))
            )

            startswith_qs = (
                qs.filter(Q(ix__name__istartswith=self.q))
                .only(
                    "pk",
                    "ix__name",
                    "ix__country",
                    "ix__name_long",
                )
                .annotate(filter_style=Value(2, IntegerField()))
                .exclude(id__in=exact_qs)
                .order_by("ix__name")
            )

            contains_qs = (
                qs.filter(Q(ix__name__icontains=self.q))
                .only(
                    "pk",
                    "ix__name",
                    "ix__country",
                    "ix__name_long",
                )
                .annotate(filter_style=Value(3, IntegerField()))
                .exclude(id__in=startswith_qs)
                .exclude(id__in=exact_qs)
                .order_by("ix__name")
            )

            # Django UNION unfortunately doesn't work here
            # but we can manually combine and sort
            result_list = sorted(
                chain(exact_qs, startswith_qs, contains_qs),
                key=attrgetter("filter_style"),
                reverse=False,
            )
            return result_list

        return qs

    def get_result_label(self, item):
        return '<span data-value="%d">\
                    <div class="main">%s \
                        <div class="tiny suffix">%s</div>\
                    </div> \
                    <div class="sub">%s</div>\
                </span>' % (
            item.id,
            html.escape(item.ix.name),
            html.escape(item.ix.country.code),
            html.escape(item.ix.name_long),
        )


class DeletedVersionAutocomplete(autocomplete.Select2QuerySetView):
    """
    Autocomplete that will show reversion versions where an object
    was set to deleted.
    """

    def get_queryset(self):
        # Only staff needs to be able to see these
        if not self.request.user.is_staff:
            return []

        # no query supplied, return empty result
        if not self.q:
            return []

        try:
            # query is expected to be of format "<reftag> <id>"
            # return empty result on parsing failure
            reftag, _id = tuple(self.q.split(" "))
        except ValueError:
            return []

        try:
            # make sure target object exists, return
            # empty result if not
            obj = REFTAG_MAP[reftag].objects.get(id=_id)
        except (KeyError, ObjectDoesNotExist):
            return []

        versions = (
            Version.objects.get_for_object(obj)
            .order_by("revision_id")
            .select_related("revision")
        )
        rv = []
        previous = {}

        # cycle through all versions of the object and collect the ones where
        # status was changed from 'ok' to 'deleted'
        #
        # order them by most recent first
        for version in versions:
            data = json.loads(version.serialized_data)[0].get("fields")

            if previous.get("status", "ok") == "ok" and data.get("status") == "deleted":
                rv.insert(0, version)

            previous = data

        return rv

    def get_result_label(self, item):
        # label should be obj representation as well as date of deletion
        # we split the date string to remove the ms and tz parts
        return "{} - {}".format(item, str(item.revision.date_created).split(".")[0])


class CommandLineToolHistoryAutocomplete(autocomplete.Select2QuerySetView):
    """
    Autocomplete for command line tools that were run via the admin ui.
    """

    tool = ""

    def get_queryset(self):
        # Only staff needs to be able to see these
        if not self.request.user.is_staff:
            return []
        qs = CommandLineTool.objects.filter(tool=self.tool).order_by("-created")
        if self.q:
            qs = qs.filter(description__icontains=self.q)
        return qs

    def get_result_label(self, item):
        return item.description or self.tool


clt_history = {}
# class for each command line tool wrapper that we will map to an auto-complete
# url in urls.py
for tool_id, tool in list(TOOL_MAP.items()):

    class ToolHistory(CommandLineToolHistoryAutocomplete):
        tool = tool_id

    ToolHistory.__name__ = f"CLT_{tool_id}_Autocomplete"
    clt_history[tool_id] = ToolHistory
