"""
django-admin interface definitions

This is the interface used by peeringdb admin-com that is currently
exposed at the path `/cp`.

New admin views wrapping HandleRef models need to extend the
`SoftDeleteAdmin` class.

Admin views wrapping verification-queue enabled models need to also
add the `ModelAdminWithVQCtrl` Mixin.

Version history is implemented through django-handleref.
"""

import datetime
import ipaddress
import json
import re

import django.urls
import reversion
from django import forms as baseForms
from django.conf import settings
from django.conf.urls import url
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin.actions import delete_selected
from django.contrib.auth.admin import UserAdmin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.utils import OperationalError
from django.forms import DecimalField
from django.shortcuts import redirect
from django.template import loader
from django.template.response import TemplateResponse
from django.utils import html
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from django_grainy.admin import UserPermissionInlineAdmin
from django_handleref.admin import VersionAdmin as HandleRefVersionAdmin
from rest_framework_api_key.admin import APIKeyModelAdmin
from rest_framework_api_key.models import APIKey
from reversion.admin import VersionAdmin

import peeringdb_server.admin_commandline_tools as acltools
from peeringdb_server.inet import RdapException, RdapLookup, rdap_pretty_error_message
from peeringdb_server.mail import mail_users_entity_merge
from peeringdb_server.models import (
    COMMANDLINE_TOOLS,
    QUEUE_ENABLED,
    REFTAG_MAP,
    UTC,
    CommandLineTool,
    DeskProTicket,
    DeskProTicketCC,
    Facility,
    GeoCoordinateCache,
    InternetExchange,
    InternetExchangeFacility,
    IXFImportEmail,
    IXFMemberData,
    IXLan,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    OrganizationAPIKey,
    OrganizationMerge,
    OrganizationMergeEntity,
    Partnership,
    ProtectedAction,
    Sponsorship,
    SponsorshipOrganization,
    User,
    UserAPIKey,
    UserOrgAffiliationRequest,
    VerificationQueueItem,
)
from peeringdb_server.util import coerce_ipaddr, round_decimal
from peeringdb_server.views import HttpResponseForbidden, JsonResponse

from . import forms

delete_selected.short_description = "HARD DELETE - Proceed with caution"

# these app labels control permissions for the views
# currently exposed in admin

PERMISSION_APP_LABELS = [
    "peeringdb_server",
    "socialaccount",
    "sites",
    "auth",
    "account",
    "oauth2_provider",
]


class StatusFilter(admin.SimpleListFilter):
    """
    A listing filter that, by default, will only show entities
    with status="ok".
    """

    title = _("Status")
    parameter_name = "status"
    dflt = "all"

    def lookups(self, request, model_admin):
        return [
            ("ok", "ok"),
            ("pending", "pending"),
            ("deleted", "deleted"),
            ("all", "all"),
        ]

    def choices(self, cl):
        val = self.value()
        if val is None:
            val = "all"
        for lookup, title in self.lookup_choices:
            yield {
                "selected": val == lookup,
                "query_string": cl.get_query_string({self.parameter_name: lookup}, []),
                "display": title,
            }

    def queryset(self, request, queryset):
        if self.value() is None or self.value() == "all":
            return queryset.all()
        return queryset.filter(**{self.parameter_name: self.value()})


def fk_handleref_filter(form, field, tag=None):
    """
    This filters foreign key dropdowns that hold handleref objects
    so they only contain undeleted objects and the object the instance is currently
    set to.
    """

    if tag is None:
        tag = field
    if tag in REFTAG_MAP and form.instance:
        model = REFTAG_MAP.get(tag)
        qset = model.handleref.filter(
            Q(status="ok") | Q(id=getattr(form.instance, "%s_id" % field))
        )

        try:
            qset = qset.order_by("name")
        except Exception:
            pass

        if field in form.fields:
            form.fields[field].queryset = qset


###############################################################################


@transaction.atomic
@reversion.create_revision()
def merge_organizations(targets, target, request):
    """
    Merge organizations specified in targets into organization specified
    in target.

    Arguments:

    targets <QuerySet|list> iterable of Organization instances

    target <Organization> merge organizations with this organization
    """

    if request.user:
        reversion.set_user(request.user)

    # preare stats

    ix_moved = 0
    fac_moved = 0
    net_moved = 0
    user_moved = 0

    org_merged = 0

    for org in targets:
        if org == target:
            raise ValueError(_("Target org cannot be in selected organizations list"))

    for org in targets:

        merge = OrganizationMerge.objects.create(from_org=org, to_org=target)
        source_admins = []

        # move entities
        for ix in org.ix_set.all():
            ix.org = target
            ix.save()
            merge.log_entity(ix)
            ix_moved += 1
        for net in org.net_set.all():
            net.org = target
            net.save()
            merge.log_entity(net)
            net_moved += 1
        for fac in org.fac_set.all():
            fac.org = target
            fac.save()
            merge.log_entity(fac)
            fac_moved += 1

        # move users
        for user in org.usergroup.user_set.all():
            target.usergroup.user_set.add(user)
            org.usergroup.user_set.remove(user)
            merge.log_entity(user, note="usergroup")
            user_moved += 1
        for user in org.admin_usergroup.user_set.all():
            target.usergroup.user_set.add(user)
            org.admin_usergroup.user_set.remove(user)
            merge.log_entity(user, note="admin_usergroup")
            user_moved += 1
            source_admins.append(user)

        # mark deleted
        org.delete()
        org_merged += 1

        mail_users_entity_merge(
            source_admins, target.admin_usergroup.user_set.all(), org, target
        )

    return {
        "ix": ix_moved,
        "fac": fac_moved,
        "net": net_moved,
        "user": user_moved,
        "org": org_merged,
    }


###############################################################################


class StatusForm(baseForms.ModelForm):
    status = baseForms.ChoiceField(
        choices=[("ok", "ok"), ("pending", "pending"), ("deleted", "deleted")]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "instance" in kwargs and kwargs.get("instance"):
            inst = kwargs.get("instance")
            if inst.status == "ok":
                self.fields["status"].choices = [("ok", "ok")]
            elif inst.status == "pending":
                self.fields["status"].choices = [("ok", "ok"), ("pending", "pending")]
            elif inst.status == "deleted":
                self.fields["status"].choices = [("ok", "ok"), ("deleted", "deleted")]

    def clean(self):

        """
        Catches and raises validation errors where an object
        is to be soft-deleted but cannot be because it is currently
        protected.
        """

        if self.cleaned_data.get("DELETE"):
            if self.instance and hasattr(self.instance, "deletable"):
                if not self.instance.deletable:
                    self.cleaned_data["DELETE"] = False
                    raise ValidationError(self.instance.not_deletable_reason)


class ModelAdminWithUrlActions(admin.ModelAdmin):
    def make_redirect(self, obj, action):
        opts = obj.model._meta
        return redirect(f"admin:{opts.app_label}_{opts.model_name}_changelist")

    def actions_view(self, request, object_id, action, **kwargs):
        """
        Allows one to call any actions defined in this model admin
        to be called via an admin view placed at <model_name>/<id>/<action>/<action_name>.
        """
        if not request.user.is_superuser:
            return HttpResponseForbidden(request)

        obj = self.get_queryset(request).filter(pk=object_id)
        if obj.exists():
            redir = self.make_redirect(obj, action)
            action = self.get_action(action)
            if action:
                action[0](self, request, obj)
                return redir
                # return redirect("admin:%s_%s_changelist" % (opts.app_label, opts.model_name))
        return redirect(
            "admin:%s_%s_changelist"
            % (obj.model._meta.app_label, obj.model._meta.model_name)
        )

    def get_urls(self):
        """
        Adds the actions view as a subview of this model's admin views.
        """
        info = self.model._meta.app_label, self.model._meta.model_name

        urls = [
            url(
                r"^(\d+)/action/([\w]+)/$",
                self.admin_site.admin_view(self.actions_view),
                name="%s_%s_actions" % info,
            ),
        ] + super().get_urls()
        return urls


@transaction.atomic
@reversion.create_revision()
def rollback(modeladmin, request, queryset):
    if request.user:
        reversion.set_user(request.user)
    for row in queryset:
        row.rollback()


rollback.short_description = _("ROLLBACK")


@transaction.atomic
@reversion.create_revision()
def soft_delete(modeladmin, request, queryset):

    if request.POST.get("delete"):

        if request.user:
            reversion.set_user(request.user)

        if queryset.model.handleref.tag == "ixlan":
            messages.error(
                request,
                _(
                    "Ixlans can no longer be directly deleted as they are now synced to the parent exchange"
                ),
            )
            return

        for row in queryset:
            try:
                row.delete()
            except ProtectedAction as err:
                messages.error(request, _("Protected object '{}': {}").format(row, err))
                continue
    else:

        context = dict(
            admin.site.each_context(request),
            deletable_objects=queryset,
            action_checkbox_name=helpers.ACTION_CHECKBOX_NAME,
            title=_("Delete selected objects"),
        )

        messages.warning(request, _("Please confirm deletion of selected objects."))
        return TemplateResponse(request, "admin/soft_delete.html", context)


soft_delete.short_description = _("SOFT DELETE")


class CustomResultLengthFilter(admin.SimpleListFilter):

    """
    Filter object that enables custom result length
    in django-admin change lists.

    This should only be used in a model admin that extends
    CustomResultLengthAdmin.
    """

    title = _("Resul length")
    parameter_name = "sz"

    def lookups(self, request, model_admin):
        return (
            ("10", _("Show {} rows").format(10)),
            ("25", _("Show {} rows").format(25)),
            ("50", _("Show {} rows").format(50)),
            ("100", _("Show {} rows").format(100)),
            ("250", _("Show {} rows").format(250)),
            ("all", _("Show {} rows").format("all")),
        )

    def queryset(self, request, queryset):
        # we simply give back the queryset, since result
        # length is controlled by the changelist instance
        # and not the queryset
        return queryset

    def choices(self, changelist):
        value = self.value()
        if value is None:
            value = f"{changelist.list_per_page}"

        for lookup, title in self.lookup_choices:
            yield {
                "selected": value == str(lookup),
                "query_string": changelist.get_query_string(
                    {self.parameter_name: lookup}
                ),
                "display": title,
            }


class CustomResultLengthAdmin:
    def get_list_filter(self, request):
        list_filter = super().get_list_filter(request)
        return list_filter + (CustomResultLengthFilter,)

    def get_changelist(self, request, **kwargs):

        # handle the customizable result length filter
        # in the django-admin change list listings (#587)
        #
        # this is accomplished through the `sz` url parameter
        if "sz" in request.GET:

            try:
                sz = request.GET.get("sz")
                # all currently translates to a max of 100k entries
                # this is a conservative limit that should be fine for
                # the time being (possible performance concerns going
                # bigger than that)
                if sz == "all":
                    sz = request.list_max_show_all = 100000
                else:
                    sz = int(sz)
            except TypeError:
                # value could not be converted to integer
                # fall back to default
                sz = self.list_per_page
        else:
            sz = self.list_per_page

        request.list_per_page = sz

        return super().get_changelist(request, **kwargs)

    def get_changelist_instance(self, request):
        """
        Returns a `ChangeList` instance based on `request`. May raise
        `IncorrectLookupParameters`.

        This is copied from the original function in the dango source
        for 2.2

        This is overriden it here so one can set the list_per_page and list_max_show_all
        values on the ChangeList accordingly.
        """
        list_display = self.get_list_display(request)
        list_display_links = self.get_list_display_links(request, list_display)
        # Add the action checkboxes if any actions are available.
        if self.get_actions(request):
            list_display = ["action_checkbox", *list_display]
        sortable_by = self.get_sortable_by(request)
        ChangeList = self.get_changelist(request)

        list_per_page = getattr(request, "list_per_page", self.list_per_page)
        list_max_show_all = getattr(
            request, "list_max_show_all", self.list_max_show_all
        )

        cl = ChangeList(
            request,
            self.model,
            list_display,
            list_display_links,
            self.get_list_filter(request),
            self.date_hierarchy,
            self.get_search_fields(request),
            self.get_list_select_related(request),
            list_per_page,
            list_max_show_all,
            self.list_editable,
            self,
            sortable_by,
        )

        cl.allow_custom_result_length = True

        return cl


class SanitizedAdmin(CustomResultLengthAdmin):
    def get_readonly_fields(self, request, obj=None):
        return ("version",) + tuple(super().get_readonly_fields(request, obj=obj))


class SoftDeleteAdmin(
    SanitizedAdmin, HandleRefVersionAdmin, VersionAdmin, admin.ModelAdmin
):
    """
    Soft delete admin.
    """

    actions = [soft_delete]

    object_history_template = "handleref/grappelli/object_history.html"
    version_details_template = "handleref/grappelli/version_details.html"
    version_revert_template = "handleref/grappelli/version_revert.html"
    version_rollback_template = "handleref/grappelli/version_rollback.html"

    @transaction.atomic
    @reversion.create_revision()
    def save_formset(self, request, form, formset, change):
        if request.user:
            reversion.set_user(request.user)
        super().save_formset(request, form, formset, change)

    def grainy_namespace(self, obj):
        return obj.grainy_namespace

    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions


class ProtectedDeleteAdmin(admin.ModelAdmin):
    """
    Allow deletion of objects if the user is superuser
    """

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class ModelAdminWithVQCtrl:
    """
    Extend from this model admin if you want to add verification queue
    approve | deny controls to the top of its form.
    """

    def get_fieldsets(self, request, obj=None):
        """
        Overrides get_fieldsets so one can attach the vq controls
        to the top of the existing fieldset - whether it's manually or automatically
        defined.
        """

        fieldsets = tuple(super().get_fieldsets(request, obj=obj))

        # on automatically defined fieldsets it will insert the controls
        # somewhere towards the bottom, we don't want that - so we look for it and
        # remove it
        for k, s in fieldsets:
            if "verification_queue" in s["fields"]:
                s["fields"].remove("verification_queue")

        # attach controls to top of fieldset
        fieldsets = (
            (None, {"classes": ("wide,"), "fields": ("verification_queue",)}),
        ) + fieldsets
        return fieldsets

    def get_readonly_fields(self, request, obj=None):
        """
        Makes the modeladmin aware that "verification_queue" is a valid
        readonly field.
        """
        return ("verification_queue",) + tuple(
            super().get_readonly_fields(request, obj=obj)
        )

    def verification_queue(self, obj):
        """
        Renders the controls or a status message.
        """

        if getattr(settings, "DISABLE_VERIFICATION_QUEUE", False):
            return _("Verification Queue is currently disabled")
        if self.model not in QUEUE_ENABLED:
            return _("Verification Queue is currently disabled for this object type")

        vq = VerificationQueueItem.objects.filter(
            content_type=ContentType.objects.get_for_model(type(obj)), object_id=obj.id
        ).first()

        if vq:
            return mark_safe(
                '<a class="grp-button" href="{}">{}</a> &nbsp;  &nbsp; <a class="grp-button grp-delete-link" href="{}">{}</a>'.format(
                    vq.approve_admin_url, _("APPROVE"), vq.deny_admin_url, _("DENY")
                )
            )
        return _("APPROVED")


class IXLanPrefixForm(StatusForm):
    def clean_prefix(self):
        value = ipaddress.ip_network(self.cleaned_data["prefix"])
        self.prefix_changed = self.instance.prefix != value
        return value

    def clean(self):
        super().clean()
        if self.prefix_changed and not self.instance.deletable:
            raise ValidationError(self.instance.not_deletable_reason)


class IXLanPrefixInline(SanitizedAdmin, admin.TabularInline):
    model = IXLanPrefix
    extra = 0
    form = IXLanPrefixForm
    fields = ["status", "protocol", "prefix"]


class IXLanInline(SanitizedAdmin, admin.StackedInline):
    model = IXLan
    extra = 0
    form = StatusForm
    exclude = ["arp_sponge", "dot1q_support"]
    readonly_fields = ["ixf_import_attempt_info", "prefixes"]

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj):
        return False

    def ixf_import_attempt_info(self, obj):
        if obj.ixf_import_attempt:
            return mark_safe(f"<pre>{obj.ixf_import_attempt.info}</pre>")
        return ""

    def prefixes(self, obj):
        return ", ".join(
            [str(ixpfx.prefix) for ixpfx in obj.ixpfx_set_active_or_pending]
        )


class InternetExchangeFacilityInline(SanitizedAdmin, admin.TabularInline):
    model = InternetExchangeFacility
    extra = 0
    form = StatusForm
    raw_id_fields = ("ix", "facility")

    def __init__(self, parent_model, admin_site):
        super().__init__(parent_model, admin_site)
        if parent_model == Facility:
            self.autocomplete_lookup_fields = {"fk": ["ix"]}
        elif parent_model == InternetExchange:
            self.autocomplete_lookup_fields = {"fk": ["facility"]}


class NetworkContactInline(SanitizedAdmin, admin.TabularInline):
    model = NetworkContact
    extra = 0
    form = StatusForm


class NetworkFacilityInline(SanitizedAdmin, admin.TabularInline):
    model = NetworkFacility
    extra = 0
    form = StatusForm
    raw_id_fields = ("network", "facility")
    exclude = ("local_asn",)

    def __init__(self, parent_model, admin_site):
        super().__init__(parent_model, admin_site)
        if parent_model == Facility:
            self.autocomplete_lookup_fields = {"fk": ["network"]}
        elif parent_model == Network:
            self.autocomplete_lookup_fields = {"fk": ["facility"]}


class NetworkIXLanForm(StatusForm):
    def clean_ipaddr4(self):
        value = self.cleaned_data["ipaddr4"]
        if not value:
            return None
        return value

    def clean_ipaddr6(self):
        value = self.cleaned_data["ipaddr6"]
        if not value:
            return None
        return value


class NetworkInternetExchangeInline(SanitizedAdmin, admin.TabularInline):
    model = NetworkIXLan
    extra = 0
    raw_id_fields = ("ixlan", "network")
    form = NetworkIXLanForm


class UserOrgAffiliationRequestInlineForm(baseForms.ModelForm):
    def clean(self):
        super().clean()
        try:
            asn = self.cleaned_data.get("asn")
            if asn:
                RdapLookup().get_asn(asn).emails
        except RdapException as exc:
            raise ValidationError({"asn": rdap_pretty_error_message(exc)})


class UserOrgAffiliationRequestInline(admin.TabularInline):
    model = UserOrgAffiliationRequest
    extra = 0
    form = UserOrgAffiliationRequestInlineForm
    verbose_name_plural = _("User is looking to be affiliated to these Organizations")
    raw_id_fields = ("org",)
    autocomplete_lookup_fields = {
        "fk": ["org"],
    }


class InternetExchangeAdminForm(StatusForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fk_handleref_filter(self, "org")


class InternetExchangeAdmin(ModelAdminWithVQCtrl, SoftDeleteAdmin):
    list_display = (
        "name",
        "aka",
        "name_long",
        "city",
        "country",
        "status",
        "created",
        "updated",
    )
    ordering = ("-created",)
    list_filter = (StatusFilter,)
    search_fields = ("name",)
    readonly_fields = (
        "id",
        "grainy_namespace",
        "ixf_import_history",
        "ixf_last_import",
        "ixf_net_count",
        "proto_unicast_readonly",
        "proto_ipv6_readonly",
        "proto_multicast_readonly",
    )
    inlines = (InternetExchangeFacilityInline, IXLanInline)
    form = InternetExchangeAdminForm

    exclude = (
        "proto_unicast",
        "proto_ipv6",
        "proto_multicast",
    )

    raw_id_fields = ("org", "ixf_import_request_user")
    autocomplete_lookup_fields = {
        "fk": ["org", "ixf_import_request_user"],
    }

    def ixf_import_history(self, obj):
        return mark_safe(
            '<a href="{}?q={}">{}</a>'.format(
                django.urls.reverse(
                    "admin:peeringdb_server_ixlanixfmemberimportlog_changelist"
                ),
                obj.id,
                _("IX-F Import History"),
            )
        )

    def proto_unicast_readonly(self, obj):
        return obj.derived_proto_unicast

    def proto_ipv6_readonly(self, obj):
        return obj.derived_proto_ipv6

    def proto_multicast_readonly(self, obj):
        return obj.proto_multicast

    proto_unicast_readonly.short_description = _("Unicast IPv4")
    proto_ipv6_readonly.short_description = _("Unicast IPv6")
    proto_multicast_readonly.short_description = _("Multicast")


class IXLanAdminForm(StatusForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fk_handleref_filter(self, "ix")


class IXLanAdmin(SoftDeleteAdmin):
    actions = []
    list_display = ("ix", "name", "descr", "status")
    search_fields = ("name", "ix__name")
    exclude = ("dot1q_support",)
    list_filter = (StatusFilter,)
    readonly_fields = ("id",)
    inlines = (IXLanPrefixInline, NetworkInternetExchangeInline)
    form = IXLanAdminForm
    raw_id_fields = ("ix",)
    autocomplete_lookup_fields = {
        "fk": [
            "ix",
        ],
    }


class IXLanIXFMemberImportLogEntryInline(admin.TabularInline):

    model = IXLanIXFMemberImportLogEntry
    fields = (
        "netixlan",
        "versions",
        "ipv4",
        "ipv6",
        "asn",
        "changes",
        "rollback_status",
        "action",
        "reason",
    )
    readonly_fields = (
        "netixlan",
        "ipv4",
        "ipv6",
        "asn",
        "changes",
        "rollback_status",
        "action",
        "reason",
        "versions",
    )
    raw_id_fields = ("netixlan",)

    extra = 0

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def versions(self, obj):
        before = self.before_id(obj)
        after = self.after_id(obj)
        return f"{before} -> {after}"

    def before_id(self, obj):
        if obj.version_before:
            return obj.version_before.id
        return "-"

    def after_id(self, obj):
        if obj.version_after:
            return obj.version_after.id
        return "-"

    def ipv4(self, obj):
        v = obj.version_after
        if v:
            return v.field_dict.get("ipaddr4")
        return obj.netixlan.ipaddr4 or ""

    def ipv6(self, obj):
        v = obj.version_after
        if v:
            return v.field_dict.get("ipaddr6")
        return obj.netixlan.ipaddr6 or ""

    def asn(self, obj):
        return obj.netixlan.asn

    def changes(self, obj):
        vb = obj.version_before
        va = obj.version_after
        if not vb:
            return _("Initial creation of netixlan")
        rv = {}
        for k, v in list(va.field_dict.items()):
            if k in ["created", "updated", "version"]:
                continue
            v2 = vb.field_dict.get(k)
            if v != v2:
                if isinstance(v, ipaddress.IPv4Address) or isinstance(
                    v, ipaddress.IPv6Address
                ):
                    rv[k] = str(v)
                else:
                    rv[k] = v

        return json.dumps(rv)

    def rollback_status(self, obj):
        rs = obj.rollback_status()
        text = ""
        color = ""
        if rs == 0:
            text = _("CAN BE ROLLED BACK")
            color = "#e5f3d6"
        elif rs == 1:
            text = ("{}<br><small>{}</small>").format(
                _("CANNOT BE ROLLED BACK"), _("Has been changed since")
            )
            color = "#f3ded6"
        elif rs == 2:
            text = ("{}<br><small>{}</small>").format(
                _("CANNOT BE ROLLED BACK"),
                _("Netixlan with conflicting ipaddress now exists elsewhere"),
            )
            color = "#f3ded6"
        elif rs == -1:
            text = _("HAS BEEN ROLLED BACK")
            color = "#d6f0f3"
        return mark_safe(f'<div style="background-color:{color}">{text}</div>')


class IXLanIXFMemberImportLogAdmin(CustomResultLengthAdmin, admin.ModelAdmin):
    search_fields = ("ixlan__ix__id",)
    list_display = ("id", "ix", "ixlan_name", "source", "created", "changes")
    readonly_fields = ("ix", "ixlan_name", "source", "changes")
    inlines = (IXLanIXFMemberImportLogEntryInline,)
    actions = [rollback]

    def has_delete_permission(self, request, obj=None):
        return False

    def changes(self, obj):
        return obj.entries.count()

    def ix(self, obj):
        return mark_safe(
            '<a href="{}">{} (ID: {})</a>'.format(
                django.urls.reverse(
                    "admin:peeringdb_server_internetexchange_change",
                    args=(obj.ixlan.ix.id,),
                ),
                obj.ixlan.ix.name,
                obj.ixlan.ix.id,
            )
        )

    def ixlan_name(self, obj):
        return mark_safe(
            '<a href="{}">{} (ID: {})</a>'.format(
                django.urls.reverse(
                    "admin:peeringdb_server_ixlan_change", args=(obj.ixlan.id,)
                ),
                obj.ixlan.name or "",
                obj.ixlan.id,
            )
        )

    def source(self, obj):
        return obj.ixlan.ixf_ixp_member_list_url


class SponsorshipOrganizationInline(admin.TabularInline):
    model = SponsorshipOrganization
    extra = 1
    raw_id_fields = ("org",)
    autocomplete_lookup_fields = {
        "fk": ["org"],
    }


class SponsorshipAdmin(CustomResultLengthAdmin, admin.ModelAdmin):
    list_display = ("organizations", "start_date", "end_date", "level", "status")
    readonly_fields = ("organizations", "status", "notify_date")
    inlines = (SponsorshipOrganizationInline,)

    raw_id_fields = ("orgs",)

    autocomplete_lookup_fields = {
        "m2m": ["orgs"],
    }

    def status(self, obj):
        now = datetime.datetime.now().replace(tzinfo=UTC())
        if not obj.start_date or not obj.end_date:
            return _("Not Set")

        if obj.start_date <= now and obj.end_date >= now:
            for row in obj.sponsorshiporg_set.all():
                if row.logo:
                    return _("Active")
            return _("Logo Missing")
        elif now > obj.end_date:
            return _("Over")
        else:
            return _("Waiting")

    def organizations(self, obj):
        qset = obj.orgs.all().order_by("name")
        if not qset.count():
            return _("No organization(s) set")
        return mark_safe("<br>\n".join([html.escape(org.name) for org in qset]))


class PartnershipAdminForm(baseForms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fk_handleref_filter(self, "org")


class PartnershipAdmin(CustomResultLengthAdmin, admin.ModelAdmin):
    list_display = ("org_name", "level", "status")
    readonly_fields = ("status", "org_name")
    form = PartnershipAdminForm
    raw_id_fields = ("org",)
    autocomplete_lookup_fields = {
        "fk": ["org"],
    }

    def org_name(self, obj):
        if not obj.org:
            return ""
        return obj.org.name

    org_name.admin_order_field = "org__name"
    org_name.short_description = "Organization"

    def status(self, obj):
        if not obj.logo:
            return _("Logo Missing")
        return _("Active")


class RoundingDecimalFormField(DecimalField):
    def to_python(self, value):
        value = super().to_python(value)
        return round_decimal(value, self.decimal_places)


class OrganizationAdminForm(StatusForm):
    latitude = RoundingDecimalFormField(max_digits=9, decimal_places=6, required=False)
    longitude = RoundingDecimalFormField(max_digits=9, decimal_places=6, required=False)


class OrganizationAdmin(ModelAdminWithVQCtrl, SoftDeleteAdmin):
    list_display = ("handle", "name", "status", "created", "updated")
    ordering = ("-created",)
    search_fields = ("name",)
    list_filter = (StatusFilter, "flagged")
    readonly_fields = ("id", "grainy_namespace")
    form = OrganizationAdminForm

    fields = [
        "status",
        "name",
        "aka",
        "name_long",
        "address1",
        "address2",
        "city",
        "state",
        "zipcode",
        "country",
        "floor",
        "suite",
        "latitude",
        "longitude",
        "geocode_status",
        "geocode_date",
        "website",
        "notes",
        "logo",
        "verification_queue",
        "version",
        "id",
        "flagged",
        "flagged_date",
        "grainy_namespace",
    ]

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url(r"^org-merge-tool/merge$", self.org_merge_tool_merge_action),
            url(r"^org-merge-tool/$", self.org_merge_tool_view),
        ]
        return my_urls + urls

    def org_merge_tool_merge_action(self, request):
        if not request.user.is_superuser:
            return HttpResponseForbidden(request)

        try:
            orgs = Organization.objects.filter(id__in=request.GET.get("ids").split(","))
        except ValueError:
            return JsonResponse({"error": _("Malformed organization ids")}, status=400)

        try:
            org = Organization.objects.get(id=request.GET.get("id"))
        except Organization.DoesNotExist:
            return JsonResponse(
                {"error": _("Merge target organization does not exist")}, status=400
            )

        rv = merge_organizations(orgs, org, request)

        return JsonResponse(rv)

    def org_merge_tool_view(self, request):
        if not request.user.is_superuser:
            return HttpResponseForbidden()

        context = dict(
            self.admin_site.each_context(request),
            undo_url=django.urls.reverse(
                "admin:peeringdb_server_organizationmerge_changelist"
            ),
            title=_("Organization Merging Tool"),
        )
        return TemplateResponse(request, "admin/org_merge_tool.html", context)


#    inlines = (InternetExchangeFacilityInline,NetworkFacilityInline,)
admin.site.register(Organization, OrganizationAdmin)


class OrganizationMergeEntities(admin.TabularInline):
    model = OrganizationMergeEntity
    extra = 0

    readonly_fields = ("content_type", "object_id", "note")

    def has_delete_permission(self, request, obj=None):
        return False


class OrganizationMergeLog(ModelAdminWithUrlActions):
    list_display = ("id", "from_org", "to_org", "created")
    search_fields = ("from_org__name", "to_org__name")
    readonly_fields = ("from_org", "to_org", "undo_merge")
    inlines = (OrganizationMergeEntities,)

    def undo_merge(self, obj):
        return mark_safe(
            '<a class="grp-button grp-delete-link" href="{}">{}</a>'.format(
                django.urls.reverse(
                    "admin:peeringdb_server_organizationmerge_actions",
                    args=(obj.id, "undo"),
                ),
                _("Undo merge"),
            )
        )

    @transaction.atomic
    @reversion.create_revision()
    def undo(modeladmin, request, queryset):
        if request.user:
            reversion.set_user(request.user)
        for each in queryset:
            each.undo()

    undo.short_description = _("Undo merge")
    undo.allowed_permissions = ("change",)

    actions = [undo]

    def has_delete_permission(self, request, obj=None):
        return False


class FacilityAdminForm(StatusForm):
    latitude = RoundingDecimalFormField(max_digits=9, decimal_places=6, required=False)
    longitude = RoundingDecimalFormField(max_digits=9, decimal_places=6, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fk_handleref_filter(self, "org")


class FacilityAdmin(ModelAdminWithVQCtrl, SoftDeleteAdmin):
    list_display = ("name", "org", "city", "country", "status", "created", "updated")
    ordering = ("-created",)
    list_filter = (StatusFilter,)
    search_fields = ("name",)
    readonly_fields = ("id", "grainy_namespace")

    raw_id_fields = ("org",)
    autocomplete_lookup_fields = {
        "fk": ["org"],
    }

    form = FacilityAdminForm
    inlines = (
        InternetExchangeFacilityInline,
        NetworkFacilityInline,
    )

    fields = [
        "status",
        "name",
        "aka",
        "name_long",
        "address1",
        "address2",
        "city",
        "state",
        "zipcode",
        "country",
        "region_continent",
        "floor",
        "suite",
        "latitude",
        "longitude",
        "website",
        "clli",
        "rencode",
        "npanxx",
        "tech_email",
        "tech_phone",
        "sales_email",
        "sales_phone",
        "property",
        "diverse_serving_substations",
        # django-admin doesnt seem to support multichoicefield automatically
        # admins can edit this through the user-facing UX for now
        # TODO: revisit enabling this field in django admin if AC communicates the need
        # "available_voltage_services",
        "notes",
        "geocode_status",
        "geocode_date",
        "org",
        "verification_queue",
        "version",
        "id",
        "grainy_namespace",
    ]


class NetworkAdminForm(StatusForm):

    # set initial values on info_prefixes4 and 6 to 0
    # this streamlines the process of adding a network through
    # the django admin controlpanel (#289)
    info_prefixes4 = baseForms.IntegerField(required=False, initial=0)
    info_prefixes6 = baseForms.IntegerField(required=False, initial=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fk_handleref_filter(self, "org")


class NetworkAdmin(ModelAdminWithVQCtrl, SoftDeleteAdmin):
    list_display = ("name", "asn", "aka", "name_long", "status", "created", "updated")
    ordering = ("-created",)
    list_filter = (StatusFilter,)
    search_fields = ("name", "asn")
    readonly_fields = ("id", "grainy_namespace")
    form = NetworkAdminForm

    inlines = (
        NetworkContactInline,
        NetworkFacilityInline,
        NetworkInternetExchangeInline,
    )

    raw_id_fields = ("org",)
    autocomplete_lookup_fields = {
        "fk": [
            "org",
        ],
    }


class InternetExchangeFacilityAdmin(SoftDeleteAdmin):
    list_display = ("id", "ix", "facility", "status", "created", "updated")
    search_fields = ("ix__name", "facility__name")
    readonly_fields = ("id",)
    list_filter = (StatusFilter,)
    form = StatusForm

    raw_id_fields = ("ix", "facility")
    autocomplete_lookup_fields = {
        "fk": ["ix", "facility"],
    }


class IXLanPrefixAdmin(SoftDeleteAdmin):
    list_display = ("id", "prefix", "ixlan", "ix", "status", "created", "updated")
    readonly_fields = ("ix", "id", "in_dfz")
    search_fields = ("ixlan__name", "ixlan__ix__name", "prefix")
    list_filter = (StatusFilter,)
    form = IXLanPrefixForm

    raw_id_fields = ("ixlan",)
    autocomplete_lookup_fields = {
        "fk": ["ixlan"],
    }

    def ix(self, obj):
        return obj.ixlan.ix


class NetworkIXLanAdmin(SoftDeleteAdmin):
    list_display = (
        "id",
        "asn",
        "net",
        "ixlan",
        "ix",
        "ipaddr4",
        "ipaddr6",
        "status",
        "created",
        "updated",
    )
    search_fields = (
        "asn",
        "network__asn",
        "network__name",
        "ixlan__name",
        "ixlan__ix__name",
        "ipaddr4",
        "ipaddr6",
    )
    readonly_fields = ("id", "ix", "net")
    list_filter = (StatusFilter,)
    form = StatusForm

    raw_id_fields = ("network", "ixlan")
    autocomplete_lookup_fields = {
        "fk": ["network", "ixlan"],
    }

    def ix(self, obj):
        return obj.ixlan.ix

    def net(self, obj):
        return f"{obj.network.name} (AS{obj.network.asn})"

    def get_search_results(self, request, queryset, search_term):
        # Issue 913
        # If the search_term is for an ipaddress6, this will compress it
        search_term = coerce_ipaddr(search_term)
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        return queryset, use_distinct


class NetworkContactAdmin(SoftDeleteAdmin):
    list_display = (
        "id",
        "net",
        "role",
        "name",
        "phone",
        "email",
        "status",
        "created",
        "updated",
    )
    search_fields = ("network__asn", "network__name")
    readonly_fields = ("id", "net")
    list_filter = (StatusFilter,)
    form = StatusForm

    raw_id_fields = ("network",)
    autocomplete_lookup_fields = {
        "fk": [
            "network",
        ],
    }

    def net(self, obj):
        return f"{obj.network.name} (AS{obj.network.asn})"


class NetworkFacilityAdmin(SoftDeleteAdmin):
    list_display = ("id", "net", "facility", "status", "created", "updated")
    search_fields = ("network__asn", "network__name", "facility__name")
    readonly_fields = ("id", "net")
    list_filter = (StatusFilter,)
    form = StatusForm

    raw_id_fields = ("network", "facility")
    autocomplete_lookup_fields = {
        "fk": ["network", "facility"],
    }

    def net(self, obj):
        return f"{obj.network.name} (AS{obj.network.asn})"


class VerificationQueueAdmin(ModelAdminWithUrlActions):
    list_display = ("content_type", "item", "created", "view", "extra")
    filter_fields = ("content_type",)
    readonly_fields = ("created", "view", "extra")
    search_fields = ("item",)

    raw_id_fields = ("user",)
    autocomplete_lookup_fields = {
        "fk": ["user"],
    }

    def get_search_results(self, request, queryset, search_term):
        # queryset, use_distinct = super(VerificationQueueAdmin, self).get_search_results(request, queryset, search_term)
        if not search_term or search_term == "":
            return queryset, False

        use_distinct = True
        myset = VerificationQueueItem.objects.none()
        for model in QUEUE_ENABLED:
            if model == User:
                qrs = model.objects.filter(username__icontains=search_term)
            else:
                qrs = model.objects.filter(name__icontains=search_term)
            content_type = ContentType.objects.get_for_model(model)
            for instance in list(qrs):
                vq = VerificationQueueItem.objects.filter(
                    content_type=content_type, object_id=instance.id
                )
                myset |= queryset & vq
        return myset, use_distinct

    def make_redirect(self, obj, action):
        if action == "vq_approve":
            opts = type(obj.first().item)._meta
            return redirect(
                django.urls.reverse(
                    f"admin:{opts.app_label}_{opts.model_name}_change",
                    args=(obj.first().item.id,),
                )
            )
        opts = obj.model._meta
        return redirect(f"admin:{opts.app_label}_{opts.model_name}_changelist")

    @transaction.atomic
    def vq_approve(self, request, queryset):
        with reversion.create_revision():
            reversion.set_user(request.user)
            for each in queryset:
                each.approve()

    vq_approve.short_description = _("APPROVE selected items")
    vq_approve.allowed_permissions = ("change",)

    @transaction.atomic
    def vq_deny(modeladmin, request, queryset):
        for each in queryset:
            each.deny()

    vq_deny.short_description = _("DENY and delete selected items")
    vq_deny.allowed_permissions = ("change",)

    actions = [vq_approve, vq_deny]

    def view(self, obj):
        return mark_safe('<a href="{}">{}</a>'.format(obj.item_admin_url, _("View")))

    def extra(self, obj):
        if hasattr(obj.item, "org") and obj.item.org.id == settings.SUGGEST_ENTITY_ORG:
            return "Suggestion"
        return ""


class UserOrgAffiliationRequestAdmin(ModelAdminWithUrlActions, ProtectedDeleteAdmin):
    list_display = (
        "user",
        "asn",
        "org",
        "created",
        "status",
    )
    search_fields = (
        "user__username",
        "asn",
    )
    readonly_fields = ("created",)

    raw_id_fields = ("user", "org")
    autocomplete_lookup_fields = {
        "fk": ["user", "org"],
    }

    @transaction.atomic
    def approve_and_notify(self, request, queryset):
        for each in queryset:
            if each.status == "canceled":
                messages.error(
                    request, _("Cannot approve a canceled affiliation request")
                )
                continue

            each.approve()
            each.notify_ownership_approved()
            self.message_user(
                request,
                _("Affiliation request was approved and the user was notified."),
            )

    approve_and_notify.short_description = _("Approve and notify User")

    @transaction.atomic
    def approve(self, request, queryset):
        for each in queryset:
            if each.status == "canceled":
                messages.error(
                    request, _("Cannot approve a canceled affiliation request")
                )
                continue
            each.approve()

    approve.short_description = _("Approve")

    @transaction.atomic
    def deny(self, request, queryset):
        for each in queryset:
            if each.status == "canceled":
                messages.error(request, _("Cannot deny a canceled affiliation request"))
                continue
            each.deny()

    deny.short_description = _("Deny")

    actions = [approve_and_notify, approve, deny]


# need to do this for add via django admin to use the right model


class UserCreationForm(forms.UserCreationForm):

    # user creation through django-admin doesnt need
    # captcha checking

    require_captcha = False

    def clean_username(self):
        username = self.cleaned_data["username"]
        try:
            User._default_manager.get(username=username)
        except User.DoesNotExist:
            return username
        raise ValidationError(self.error_messages["duplicate_username"])

    class Meta(forms.UserCreationForm.Meta):
        model = User
        fields = ("username", "password", "email")


class UserAdmin(ModelAdminWithVQCtrl, UserAdmin):
    inlines = (UserOrgAffiliationRequestInline,)
    readonly_fields = (
        "email_status",
        "organizations",
        "view_permissions",
        "change_password",
    )
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "email_status",
        "status",
    )
    add_form = UserCreationForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "email"),
            },
        ),
    )
    fieldsets = (
        ((None, {"classes": ("wide",), "fields": ("email_status", "change_password")}),)
        + UserAdmin.fieldsets
        + ((None, {"classes": ("wide",), "fields": ("organizations",)}),)
    )

    # we want to get rid of user permissions and group editor as that
    # will be displayed on a separate page, for performance reasons

    for name, grp in fieldsets:
        grp["fields"] = tuple(
            fld
            for fld in grp["fields"]
            if fld
            not in [
                "groups",
                "user_permissions",
                "is_staff",
                "is_active",
                "is_superuser",
            ]
        )
        if name == "Permissions":
            grp["fields"] += ("view_permissions",)

    def version(self, obj):
        """
        Users are not versioned, but ModelAdminWithVQCtrl defines
        a readonly field called "version." For the sake of completion,
        return a 0 version here.
        """
        return 0

    def change_password(self, obj):
        return mark_safe(
            '<a href="{}">{}</a>'.format(
                django.urls.reverse("admin:auth_user_password_change", args=(obj.id,)),
                _("Change Password"),
            )
        )

    def view_permissions(self, obj):
        url = django.urls.reverse(
            "admin:%s_%s_change"
            % (UserPermission._meta.app_label, UserPermission._meta.model_name),
            args=(obj.id,),
        )

        return mark_safe('<a href="{}">{}</a>'.format(url, _("Edit Permissions")))

    def email_status(self, obj):
        if obj.email_confirmed:
            return mark_safe(
                '<span style="color:darkgreen">{}</span>'.format(_("VERIFIED"))
            )
        else:
            return mark_safe(
                '<span style="color:darkred">{}</span>'.format(_("UNVERIFIED"))
            )

    def organizations(self, obj):
        return mark_safe(
            loader.get_template("admin/user-organizations.html")
            .render({"organizations": obj.organizations, "user": obj})
            .replace("\n", "")
        )


class UserPermission(User):
    class Meta:
        proxy = True
        verbose_name = _("User Permission")
        verbose_name_plural = _("User Permissions")


class UserPermissionAdmin(UserAdmin):

    search_fields = ("username",)

    inlines = (
        UserOrgAffiliationRequestInline,
        UserPermissionInlineAdmin,
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                ),
                "classes": ("wide",),
            },
        ),
    )

    readonly_fields = ("user",)

    def get_form(self, request, obj=None, **kwargs):
        # we want to remove the password field from the form
        # since we don't send it and don't want to run clean for it
        form = super().get_form(request, obj, **kwargs)
        del form.base_fields["password"]
        return form

    def user(self, obj):
        url = django.urls.reverse(
            f"admin:{User._meta.app_label}_{User._meta.model_name}_change",
            args=(obj.id,),
        )

        return mark_safe(f'<a href="{url}">{obj.username}</a>')

    def clean_password(self):
        pass


## COMMANDLINE TOOL ADMIN


class CommandLineToolPrepareForm(baseForms.Form):
    """
    Form that allows user to select which commandline tool
    to run.
    """

    tool = baseForms.ChoiceField(choices=COMMANDLINE_TOOLS)


class CommandLineToolAdmin(CustomResultLengthAdmin, admin.ModelAdmin):
    """
    View that lets staff users run peeringdb command line tools.
    """

    list_display = ("tool", "description", "user", "created", "status")
    readonly_fields = (
        "tool",
        "description",
        "arguments",
        "result",
        "user",
        "created",
        "status",
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url(
                r"^prepare/$",
                self.prepare_command_view,
                name="peeringdb_server_commandlinetool_prepare",
            ),
            url(
                r"^preview/$",
                self.preview_command_view,
                name="peeringdb_server_commandlinetool_preview",
            ),
            url(
                r"^run/$",
                self.run_command_view,
                name="peeringdb_server_commandlinetool_run",
            ),
        ]
        return my_urls + urls

    def prepare_command_view(self, request):
        """
        This view has the user select which command they want to run and
        with which arguments.
        """
        if not self.has_add_permission(request):
            return HttpResponseForbidden()

        context = dict(self.admin_site.each_context(request))
        title = "Commandline Tools"

        action = "prepare"
        if request.method == "POST":
            form = CommandLineToolPrepareForm(request.POST, request.FILES)
            if form.is_valid():
                action = "preview"
                tool = acltools.get_tool(request.POST.get("tool"), form)
                context.update(tool=tool)
                title = tool.name
                form = tool.form
        else:
            form = CommandLineToolPrepareForm()

        context.update(
            {
                "adminform": helpers.AdminForm(
                    form,
                    list([(None, {"fields": form.base_fields})]),
                    self.get_prepopulated_fields(request),
                ),
                "action": action,
                "app_label": self.model._meta.app_label,
                "opts": self.model._meta,
                "title": title,
            }
        )
        return TemplateResponse(
            request,
            "admin/peeringdb_server/commandlinetool/prepare_command.html",
            context,
        )

    def preview_command_view(self, request):
        """
        This view has the user preview the result of running the command.
        """
        if not self.has_add_permission(request):
            return HttpResponseForbidden()

        context = dict(self.admin_site.each_context(request))
        if request.method == "POST":
            tool = acltools.get_tool_from_data(request.POST)
            context.update(tool=tool)
            if tool.form_instance.is_valid():
                action = "run"
                tool.run(request.user, commit=False)
            else:
                action = "run"
            form = tool.form_instance
        else:
            raise Exception(_("Only POST requests allowed."))

        context.update(
            {
                "adminform": helpers.AdminForm(
                    form,
                    list([(None, {"fields": form.base_fields})]),
                    self.get_prepopulated_fields(request),
                ),
                "action": action,
                "app_label": self.model._meta.app_label,
                "opts": self.model._meta,
                "title": _("{} (Preview)").format(tool.name),
            }
        )
        return TemplateResponse(
            request,
            "admin/peeringdb_server/commandlinetool/preview_command.html",
            context,
        )

    @transaction.atomic
    def run_command_view(self, request):
        """
        This view has the user running the command and commiting changes
        to the database.
        """
        if not self.has_add_permission(request):
            return HttpResponseForbidden()

        context = dict(self.admin_site.each_context(request))
        if request.method == "POST":
            tool = acltools.get_tool_from_data(request.POST)
            context.update(tool=tool)
            if tool.form_instance.is_valid():
                tool.run(request.user, commit=True)
            form = tool.form_instance
        else:
            raise Exception(_("Only POST requests allowed."))

        context.update(
            {
                "adminform": helpers.AdminForm(
                    form,
                    list([(None, {"fields": form.base_fields})]),
                    self.get_prepopulated_fields(request),
                ),
                "action": "run",
                "app_label": self.model._meta.app_label,
                "opts": self.model._meta,
                "title": tool.name,
            }
        )
        return TemplateResponse(
            request, "admin/peeringdb_server/commandlinetool/run_command.html", context
        )


class IXFImportEmailAdmin(CustomResultLengthAdmin, admin.ModelAdmin):
    list_display = (
        "subject",
        "recipients",
        "created",
        "sent",
        "net",
        "ix",
        "stale_info",
    )
    readonly_fields = (
        "net",
        "ix",
    )
    search_fields = ("subject", "ix__name", "net__name")
    change_list_template = "admin/change_list_with_regex_search.html"

    def stale_info(self, obj):
        not_sent = obj.sent is None
        if type(obj.sent) == datetime.datetime:
            re_sent = (obj.sent - obj.created) > datetime.timedelta(minutes=5)
        else:
            re_sent = False
        prod_mail_mode = not settings.MAIL_DEBUG
        return prod_mail_mode and (not_sent or re_sent)

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        # Require ^ and $ for regex
        if search_term.startswith("^") and search_term.endswith("$"):
            # Convert search to raw string
            try:
                search_term = search_term.encode("unicode-escape").decode()
            except AttributeError:
                return queryset, use_distinct

            # Validate regex expression
            try:
                re.compile(search_term)
            except re.error:
                return queryset, use_distinct

            # Add (case insensitive) regex search results to standard search results
            try:
                queryset = self.model.objects.filter(
                    subject__iregex=search_term
                ).order_by("-created")
            except OperationalError:
                return queryset, use_distinct

        return queryset, use_distinct


class DeskProTicketCCInline(admin.TabularInline):
    model = DeskProTicketCC


class DeskProTicketAdmin(CustomResultLengthAdmin, admin.ModelAdmin):
    list_display = (
        "id",
        "subject",
        "user",
        "created",
        "published",
        "deskpro_ref",
        "deskpro_id",
    )
    search_fields = ("subject",)
    change_list_template = "admin/change_list_with_regex_search.html"
    inlines = (DeskProTicketCCInline,)
    raw_id_fields = ("user",)

    autocomplete_lookup_fields = {
        "fk": [
            "user",
        ],
    }

    def get_readonly_fields(self, request, obj=None):
        if not obj:
            return self.readonly_fields
        return self.readonly_fields + ("user",)

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )

        # Require ^ and $ for regex
        if search_term.startswith("^") and search_term.endswith("$"):
            # Convert search to raw string
            try:
                search_term = search_term.encode("unicode-escape").decode()
            except AttributeError:
                return queryset, use_distinct

            # Validate regex expression
            try:
                re.compile(search_term)
            except re.error:
                return queryset, use_distinct

            # Add (case insensitive) regex search results to standard search results
            try:
                queryset = self.model.objects.filter(
                    subject__iregex=search_term
                ).order_by("-created")
            except OperationalError:
                return queryset, use_distinct

        return queryset, use_distinct

    def save_model(self, request, obj, form, change):
        if not obj.id and not obj.user_id:
            obj.user = request.user
        return super().save_model(request, obj, form, change)


@reversion.create_revision()
def apply_ixf_member_data(modeladmin, request, queryset):
    for ixf_member_data in queryset:
        try:
            ixf_member_data.apply(user=request.user, comment="Applied IX-F suggestion")
        except ValidationError as exc:
            messages.error(request, f"{ixf_member_data.ixf_id_pretty_str}: {exc}")


apply_ixf_member_data.short_description = _("Apply")


class IXFMemberDataAdmin(CustomResultLengthAdmin, admin.ModelAdmin):
    change_form_template = "admin/ixf_member_data_change_form.html"

    list_display = (
        "id",
        "ix",
        "asn",
        "ipaddr4",
        "ipaddr6",
        "action",
        "netixlan",
        "speed",
        "operational",
        "is_rs_peer",
        "created",
        "updated",
        "fetched",
        "changes",
        "actionable_error",
        "reason",
        "requirements",
    )
    readonly_fields = (
        "marked_for_removal",
        "fetched",
        "ix",
        "action",
        "changes",
        "reason",
        "netixlan",
        "log",
        "error",
        "actionable_error",
        "created",
        "updated",
        "status",
        "remote_data",
        "requirements",
        "requirement_of",
        "requirement_detail",
    )

    search_fields = ("asn", "ixlan__id", "ixlan__ix__name", "ipaddr4", "ipaddr6")

    fields = (
        "ix",
        "asn",
        "ipaddr4",
        "ipaddr6",
        "action",
        "netixlan",
        "speed",
        "operational",
        "is_rs_peer",
        "created",
        "updated",
        "fetched",
        "changes",
        "reason",
        "error",
        "log",
        "remote_data",
        "requirement_of",
        "requirement_detail",
        "deskpro_id",
        "deskpro_ref",
    )

    actions = [apply_ixf_member_data]

    raw_id_fields = ("ixlan",)

    autocomplete_lookup_fields = {
        "fk": [
            "ixlan",
        ],
    }

    def get_queryset(self, request):
        qset = super().get_queryset(request)

        if request.resolver_match.kwargs.get("object_id"):
            return qset

        return qset.filter(requirement_of__isnull=True)

    def ix(self, obj):
        return obj.ixlan.ix

    def requirements(self, obj):
        return len(obj.requirements)

    def requirement_detail(self, obj):
        lines = []

        for requirement in obj.requirements:
            url = django.urls.reverse(
                "admin:peeringdb_server_ixfmemberdata_change", args=(requirement.id,)
            )
            lines.append(f'<a href="{url}">{requirement} {requirement.action}</a>')

        if not lines:
            return _("No requirements")

        return mark_safe("<br>".join(lines))

    def netixlan(self, obj):
        if not obj.netixlan.id:
            return "-"
        url = django.urls.reverse(
            "admin:peeringdb_server_networkixlan_change", args=(obj.netixlan.id,)
        )
        return mark_safe(f'<a href="{url}">{obj.netixlan.id}</a>')

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.action != "add":
            # make identifying fields read-only
            # for modify / delete actions
            return self.readonly_fields + ("asn", "ipaddr4", "ipaddr6")
        return self.readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def remote_data(self, obj):
        return obj.json

    @transaction.atomic
    @reversion.create_revision()
    def response_change(self, request, obj):
        if "_save-and-apply" in request.POST:
            obj.save()
            obj.apply(user=request.user, comment="Applied IX-F suggestion")
        return super().response_change(request, obj)


class EnvironmentSettingForm(baseForms.ModelForm):

    value = baseForms.CharField(required=True, label=_("Value"))

    class Meta:
        fields = ["setting", "value"]


class EnvironmentSettingAdmin(CustomResultLengthAdmin, admin.ModelAdmin):
    list_display = ["setting", "value", "created", "updated", "user"]

    fields = ["setting", "value"]

    readonly_fields = ["created", "updated"]
    search_fields = ["setting"]

    form = EnvironmentSettingForm

    @transaction.atomic
    def save_model(self, request, obj, form, save):
        obj.user = request.user
        return obj.set_value(form.cleaned_data["value"])


class OrganizationAPIKeyAdmin(APIKeyModelAdmin):
    list_display = ["org", "prefix", "name", "created", "revoked"]
    search_fields = ("prefix", "org__name")


class UserAPIKeyAdmin(APIKeyModelAdmin):
    list_display = ["user", "prefix", "name", "readonly", "created", "revoked"]
    search_fields = ("prefix", "user__username", "user__email")


class GeoCoordinateAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "country",
        "city",
        "state",
        "zipcode",
        "address1",
        "longitude",
        "latitude",
        "fetched",
    ]


# Commented out via issue #860
# admin.site.register(EnvironmentSetting, EnvironmentSettingAdmin)
admin.site.register(IXFMemberData, IXFMemberDataAdmin)
admin.site.register(Facility, FacilityAdmin)
admin.site.register(InternetExchange, InternetExchangeAdmin)
admin.site.register(InternetExchangeFacility, InternetExchangeFacilityAdmin)
admin.site.register(IXLan, IXLanAdmin)
admin.site.register(IXLanPrefix, IXLanPrefixAdmin)
admin.site.register(NetworkIXLan, NetworkIXLanAdmin)
admin.site.register(NetworkContact, NetworkContactAdmin)
admin.site.register(NetworkFacility, NetworkFacilityAdmin)
admin.site.register(Network, NetworkAdmin)
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.register(VerificationQueueItem, VerificationQueueAdmin)
admin.site.register(Sponsorship, SponsorshipAdmin)
admin.site.register(Partnership, PartnershipAdmin)
admin.site.register(OrganizationMerge, OrganizationMergeLog)
admin.site.register(UserPermission, UserPermissionAdmin)
admin.site.register(IXLanIXFMemberImportLog, IXLanIXFMemberImportLogAdmin)
admin.site.register(CommandLineTool, CommandLineToolAdmin)
admin.site.register(UserOrgAffiliationRequest, UserOrgAffiliationRequestAdmin)
admin.site.register(DeskProTicket, DeskProTicketAdmin)
admin.site.register(IXFImportEmail, IXFImportEmailAdmin)
admin.site.unregister(APIKey)
admin.site.register(OrganizationAPIKey, OrganizationAPIKeyAdmin)
admin.site.register(UserAPIKey, UserAPIKeyAdmin)
admin.site.register(GeoCoordinateCache, GeoCoordinateAdmin)
