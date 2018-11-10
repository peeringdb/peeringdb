from django.db.models import Q
from django import http
from django.utils import html
from dal import autocomplete
from peeringdb_server.models import (InternetExchange, Facility,
                                     NetworkFacility, InternetExchangeFacility,
                                     Organization, IXLan, CommandLineTool)

from peeringdb_server.admin_commandline_tools import TOOL_MAP


class AutocompleteHTMLResponse(autocomplete.Select2QuerySetView):
    def has_add_permissions(self, request):
        return False

    def render_to_response(self, context):
        q = self.request.GET.get('q', None)
        return http.HttpResponse("".join(
            [i.get("text") for i in self.get_results(context)]),
                                 content_type="text/html")


class ExchangeAutocompleteJSON(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = InternetExchange.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        qs = qs.order_by('name')
        return qs


class ExchangeAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = InternetExchange.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        qs = qs.order_by('name')
        return qs

    def get_result_label(self, item):
        return u'<span data-value="%d"><div class="main">%s</div></span>' % (
            item.pk, html.escape(item.name))


class FacilityAutocompleteJSON(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Facility.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        qs = qs.order_by('name')
        return qs


class FacilityAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = Facility.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(
                Q(name__icontains=self.q) | Q(address1__icontains=self.q))
        qs = qs.order_by('name')
        return qs

    def get_result_label(self, item):
        return u'<span data-value="%d"><div class="main">%s</div> <div class="sub">%s</div></span>' % (
            item.pk, html.escape(item.name), html.escape(item.address1))


class FacilityAutocompleteForNetwork(FacilityAutocomplete):
    def get_queryset(self):
        qs = super(FacilityAutocompleteForNetwork, self).get_queryset()
        net_id = self.request.resolver_match.kwargs.get("net_id")
        fac_ids = [
            nf.facility_id
            for nf in NetworkFacility.objects.filter(status="ok",
                                                     network_id=net_id)
        ]
        qs = qs.exclude(id__in=fac_ids)
        return qs


class FacilityAutocompleteForExchange(FacilityAutocomplete):
    def get_queryset(self):
        qs = super(FacilityAutocompleteForExchange, self).get_queryset()
        ix_id = self.request.resolver_match.kwargs.get("ix_id")
        fac_ids = [
            nf.facility_id
            for nf in InternetExchangeFacility.objects.filter(
                status="ok", ix_id=ix_id)
        ]
        qs = qs.exclude(id__in=fac_ids)
        return qs


class OrganizationAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = Organization.objects.filter(status="ok")
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        qs = qs.order_by('name')
        return qs

    def get_result_label(self, item):
        return u'<span data-value="%d"><div class="main">%s</div></span>' % (
            item.pk, html.escape(item.name))


class IXLanAutocomplete(AutocompleteHTMLResponse):
    def get_queryset(self):
        qs = IXLan.objects.filter(status="ok").select_related("ix")
        if self.q:
            qs = qs.filter(
                Q(ix__name__icontains=self.q)
                | Q(ix__name_long__icontains=self.q))
        qs = qs.order_by('ix__name')
        return qs

    def get_result_label(self, item):
        return u'<span data-value="%d"><div class="main">%s <div class="tiny suffix">%s</div></div> <div class="sub">%s</div> <div class="sub">%s</div></span>' % (
            item.pk, html.escape(item.ix.name),
            html.escape(item.ix.country.code), html.escape(item.ix.name_long),
            html.escape(item.name))


class CommandLineToolHistoryAutocomplete(autocomplete.Select2QuerySetView):
    """
    Autocomplete for command line tools that were ran via the admin ui
    """
    tool = ""

    def get_queryset(self):
        # Only staff needs to be able to see these
        if not self.request.user.is_staff:
            return []
        qs = CommandLineTool.objects.filter(
            tool=self.tool).order_by("-created")
        if self.q:
            qs = qs.filter(description__icontains=self.q)
        return qs

    def get_result_label(self, item):
        return (item.description or self.tool)


clt_history = {}
# class for each command line tool wrapper that we will map to an auto-complete
# url in urls.py
for tool_id, tool in TOOL_MAP.items():

    class ToolHistory(CommandLineToolHistoryAutocomplete):
        tool = tool_id

    ToolHistory.__name__ = "CLT_{}_Autocomplete".format(tool_id)
    clt_history[tool_id] = ToolHistory
