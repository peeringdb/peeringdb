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
from django.utils.encoding import smart_str
from grappelli.views.related import AutocompleteLookup as GrappelliAutocomplete
from grappelli.views.related import get_autocomplete_search_fields, get_label
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


class PDBAdminGrappelliAutocomplete(GrappelliAutocomplete):
    def get_data(self):
        # limit qs to 250 items
        return [
            {"value": self.get_return_value(f, f.pk), "label": get_label(f)}
            for f in self.get_queryset()[:250]
        ]


class GrappelliHandlerefAutocomplete(PDBAdminGrappelliAutocomplete):
    """
    Make sure that the auto-complete fields managed
    by grappelli in django admin exclude soft-deleted
    objects.
    """

    def adjust_search_field_for_anchors(self, search_field, anchor_start, anchor_end):
        if not anchor_start and not anchor_end:
            return search_field

        name, filt = search_field.split("__")

        if filt != "icontains":
            return search_field

        if anchor_start and anchor_end:
            return f"{name}"
        elif anchor_start:
            return f"{name}__istartswith"
        return f"{name}__iendswith"

    def get_searched_queryset(self, qs):
        model = self.model
        term = self.GET["term"]

        try:
            term = model.autocomplete_term_adjust(term)
        except AttributeError:
            pass

        search_fields = get_autocomplete_search_fields(self.model)

        anchor_start = term and term[0] == "^"
        anchor_end = term and term[-1] == "$"

        # by default multiple searches can be done at once by delimiting
        # search times via a space (grappelli default behaviour)
        #
        # this makes little sense when doing an exact search while
        # providing both ^ and $ anchors, so change the delimiter in that
        # case
        #
        # TODO: just use a ; for a delimiter no matter what ?

        if anchor_start and anchor_end:
            delimiter = ";"
        else:
            delimiter = " "

        term = term.strip("^$")

        if search_fields:
            search = Q()
            for word in term.split(delimiter):
                term_query = Q()
                for search_field in search_fields:
                    search_field = self.adjust_search_field_for_anchors(
                        search_field, anchor_start, anchor_end
                    )
                    print("SEARCH_FIELD", search_field, smart_str(search_field), term)
                    term_query |= Q(**{smart_str(search_field): smart_str(word)})
                search &= term_query
            qs = qs.filter(search)
        else:
            qs = model.objects.none()
        return qs

    def get_queryset(self):
        qs = super().get_queryset()

        # Add support for ^ and $ regex anchors and add it to the top qs results
        query = self.GET["term"]
        if len(query) < 2:
            return []

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
        return f'<span data-value="{item.pk}"><div class="main">{html.escape(item.name)}</div> <div class="sub">AS{html.escape(item.asn)}</div></span>'


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


class FacilityAutocompleteForOrganization(FacilityAutocomplete):
    """
    List of facilities under same organization ownership
    """

    def get_queryset(self):
        qs = super().get_queryset()
        org_id = self.request.resolver_match.kwargs.get("org_id")
        fac_ids = [
            fac.id for fac in Facility.objects.filter(status="ok", org_id=org_id)
        ]
        qs = qs.filter(id__in=fac_ids)
        return qs


class OrganizationAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = Organization.objects.filter(status="ok")
        if self.q:
            anchor_start = self.q[0] == "^"
            anchor_end = self.q[-1] == "$"
            self.q = self.q.strip("^$")

            if anchor_start and anchor_end:
                qs = qs.filter(name__iexact=self.q)
            elif anchor_start:
                qs = qs.filter(name__istartswith=self.q)
            elif anchor_end:
                qs = qs.filter(name__iendswith=self.q)
            else:
                qs = qs.filter(name__icontains=self.q)

        qs = qs.order_by("name")

        return qs

    def get_result_label(self, item):
        return '<span data-value="%d"><div class="main">%s</div></span>' % (
            item.pk,
            html.escape(item.name),
        )


class BaseFacilityAutocompleteForPort(AutocompleteHTMLResponse):
    """
    Base class for facility autocomplete for ports.

    Provides the base queryset and result label logic for filtering
    facilities based on a search query (name or address1) and ordering
    by the facility's name. This class is intended to be extended by
    more specific facility-related autocomplete classes.
    """

    def get_queryset(self):
        qs = Facility.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(Q(name__icontains=self.q) | Q(address1__icontains=self.q))
        qs = qs.order_by("name")
        return qs

    def get_result_label(self, item):
        return f'<span data-value="{item.facility.pk}"><div class="main">{html.escape(item.facility.name)}</div></span>'


class NetworkFacilityAutocomplete(BaseFacilityAutocompleteForPort):
    """
    Autocomplete class for facilities within a specific network.

    Extends the base class to filter facilities associated with a
    specific network. Excludes facilities not linked to the network.
    """

    def get_queryset(self):
        net_id = self.request.resolver_match.kwargs.get("net_id")
        qs = NetworkFacility.objects.filter(status="ok", network_id=net_id)
        if self.q:
            qs = qs.filter(Q(facility__name__icontains=self.q))
        return qs.order_by("facility__name")


class InternetExchangeFacilityAutoComplete(BaseFacilityAutocompleteForPort):
    """
    Autocomplete class for facilities within a specific Internet Exchange (IX).

    Extends the base class to filter facilities associated with a specific
    Internet Exchange. The `ix_id` parameter is used to filter the related
    facilities.
    """

    def get_queryset(self):
        ix_id = self.request.resolver_match.kwargs.get("ix_id")
        ix = InternetExchange.objects.get(pk=ix_id)
        qs = ix.ixfac_set.filter(status="ok")
        if self.q:
            qs = qs.filter(Q(facility__name__icontains=self.q))
        return qs.order_by("facility__name")


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
        return (
            '<span data-value="%d">\
                    <div class="main">%s \
                        <div class="tiny suffix">%s</div>\
                    </div> \
                    <div class="sub">%s</div>\
                </span>'
            % (
                item.id,
                html.escape(item.ix.name),
                html.escape(item.ix.country.code),
                html.escape(item.ix.name_long),
            )
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
