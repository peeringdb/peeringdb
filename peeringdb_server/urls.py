"""
Django url to view routing.
"""
import django_security_keys.views as security_keys_views
from django.conf import settings
from django.conf.urls import include, url
from django.urls import path
from django.views.generic import RedirectView, TemplateView
from django.views.i18n import JavaScriptCatalog

import peeringdb_server.api_key_views
import peeringdb_server.data_views
import peeringdb_server.org_admin_views
import peeringdb_server.rest
from peeringdb_server.autocomplete_views import (
    DeletedVersionAutocomplete,
    ExchangeAutocomplete,
    ExchangeAutocompleteJSON,
    FacilityAutocomplete,
    FacilityAutocompleteForExchange,
    FacilityAutocompleteForNetwork,
    FacilityAutocompleteJSON,
    IXLanAutocomplete,
    NetworkAutocomplete,
    OrganizationAutocomplete,
    clt_history,
)
from peeringdb_server.export_views import (
    AdvancedSearchExportView,
    view_export_ixf_ix_members,
    view_export_ixf_ixlan_members,
)
from peeringdb_server.import_views import (
    view_import_ixlan_ixf_preview,
    view_import_net_ixf_postmortem,
    view_import_net_ixf_preview,
)
from peeringdb_server.models import Facility, InternetExchange, Network, Organization
from peeringdb_server.oauth_views import AuthorizationView
from peeringdb_server.views import (
    OrganizationLogoUpload,
    cancel_affiliation_request,
    network_dismiss_ixf_proposal,
    network_reset_ixf_proposals,
    profile_add_email,
    profile_delete_email,
    profile_set_primary_email,
    request_api_search,
    request_logout,
    request_search,
    request_translation,
    resend_confirmation_mail,
    unwatch_network,
    validator_result_cache,
    view_about,
    view_advanced_search,
    view_affiliate_to_org,
    view_aup,
    view_close_account,
    view_exchange,
    view_facility,
    view_index,
    view_maintenance,
    view_network,
    view_network_by_asn,
    view_network_by_query,
    view_organization,
    view_password_change,
    view_password_reset,
    view_profile,
    view_profile_v1,
    view_registration,
    view_request_ownership,
    view_set_user_locale,
    view_sponsorships,
    view_suggest,
    view_username_retrieve,
    view_username_retrieve_complete,
    view_username_retrieve_initiate,
    view_verify,
    watch_network,
)

# o
# SITE


urlpatterns = [
    url(
        r"^robots.txt$",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
    ),
    url(r"^api_search$", request_api_search),
    url(r"^search$", request_search),
    url(r"^advanced_search", view_advanced_search),
    url(r"^logout$", request_logout),
    url(
        r"^login$",
        RedirectView.as_view(pattern_name="two_factor:login", permanent=True),
    ),
    url(r"^register$", view_registration, name="register"),
    url(r"^reset-password$", view_password_reset, name="reset-password"),
    url(r"^change-password$", view_password_change),
    url(r"^set-user-locale$", view_set_user_locale),
    url(
        r"^username-retrieve/initiate$",
        view_username_retrieve_initiate,
        name="username-retrieve-initiate",
    ),
    url(r"^username-retrieve/complete$", view_username_retrieve_complete),
    url(r"^username-retrieve$", view_username_retrieve, name="username-retrieve"),
    url(r"^verify$", view_verify),
    url(r"^profile$", view_profile, name="user-profile"),
    url(r"^profile/close$", view_close_account, name="close-account"),
    url(r"^profile/v1$", view_profile_v1),
    url(r"^profile/email/add", profile_add_email, name="profile-add-email"),
    url(r"^profile/email/delete", profile_delete_email, name="profile-remove-email"),
    url(
        r"^profile/email/primary",
        profile_set_primary_email,
        name="profile-set-primary-email",
    ),
    url(r"^resend_email_confirmation$", resend_confirmation_mail),
    url(r"^sponsors$", view_sponsorships),
    # url(r'^partners$', view_partnerships),
    url(r"^aup$", view_aup),
    url(r"^about$", view_about),
    url(r"^affiliate-to-org$", view_affiliate_to_org),
    path(
        "org/<str:id>/upload-logo",
        OrganizationLogoUpload.as_view(),
        name="org-logo-upload",
    ),
    url(
        r"^cancel-affiliation-request/(?P<uoar_id>\d+)/$",
        cancel_affiliation_request,
        name="cancel-affiliation-request",
    ),
    url(r"^request-ownership$", view_request_ownership),
    url(
        r"^%s/(?P<net_id>\d+)/dismiss-ixf-proposal/(?P<ixf_id>\d+)/$"
        % Network.handleref.tag,
        network_dismiss_ixf_proposal,
        name="net-dismiss-ixf-proposal",
    ),
    url(
        r"^%s/(?P<net_id>\d+)/reset-ixf-proposals/$" % Network.handleref.tag,
        network_reset_ixf_proposals,
        name="net-reset-ixf-proposals",
    ),
    url(r"^%s/(?P<id>\d+)/?$" % Network.handleref.tag, view_network, name="net-view"),
    url(
        r"^%s/(?P<id>\d+)/watch/?$" % Network.handleref.tag,
        watch_network,
        name="net-watch",
    ),
    url(
        r"^%s/(?P<id>\d+)/unwatch/?$" % Network.handleref.tag,
        unwatch_network,
        name="net-unwatch",
    ),
    url(
        r"^%s/(?P<id>\d+)/?$" % InternetExchange.handleref.tag,
        view_exchange,
        name="ix-view",
    ),
    url(r"^%s/(?P<id>\d+)/?$" % Facility.handleref.tag, view_facility, name="fac-view"),
    url(
        r"^%s/(?P<id>\d+)/?$" % Organization.handleref.tag,
        view_organization,
        name="org-view",
    ),
    url(r"^%s$" % Network.handleref.tag, view_network_by_query),
    url(r"^asn/(?P<asn>\d+)/?$", view_network_by_asn, name="net-view-asn"),
    url(r"^user_keys/add$", peeringdb_server.api_key_views.add_user_key),
    url(r"^user_keys/revoke$", peeringdb_server.api_key_views.remove_user_key),
    url(
        r"^security_keys/request_registration$",
        security_keys_views.request_registration,
        name="security-keys-request-registration",
    ),
    url(
        r"^security_keys/request_authentication$",
        security_keys_views.request_authentication,
        name="security-keys-request-authentication",
    ),
    url(
        r"^security_keys/verify_authentication$",
        security_keys_views.verify_authentication,
    ),
    url(r"^security_keys/add$", security_keys_views.register_security_key),
    url(r"^security_keys/remove$", security_keys_views.remove_security_key),
    url(r"^org_admin/users$", peeringdb_server.org_admin_views.users),
    url(
        r"^org_admin/user_permissions$",
        peeringdb_server.org_admin_views.user_permissions,
    ),
    url(
        r"^org_admin/user_permissions/update$",
        peeringdb_server.org_admin_views.user_permission_update,
    ),
    url(
        r"^org_admin/user_permissions/remove$",
        peeringdb_server.org_admin_views.user_permission_remove,
    ),
    url(r"^org_admin/permissions$", peeringdb_server.org_admin_views.permissions),
    url(r"^org_admin/uoar/approve$", peeringdb_server.org_admin_views.uoar_approve),
    url(r"^org_admin/uoar/deny$", peeringdb_server.org_admin_views.uoar_deny),
    url(
        r"^org_admin/manage_user/update$",
        peeringdb_server.org_admin_views.manage_user_update,
    ),
    url(
        r"^org_admin/user_options$",
        peeringdb_server.org_admin_views.update_user_options,
        name="org-admin-user-options",
    ),
    url(
        r"^org_admin/manage_user/delete$",
        peeringdb_server.org_admin_views.manage_user_delete,
    ),
    url(r"^org_admin/manage_key/add$", peeringdb_server.api_key_views.manage_key_add),
    url(
        r"^org_admin/manage_key/update$",
        peeringdb_server.api_key_views.manage_key_update,
    ),
    url(
        r"^org_admin/manage_key/revoke$",
        peeringdb_server.api_key_views.manage_key_revoke,
    ),
    url(
        r"^org_admin/key_permissions$",
        peeringdb_server.api_key_views.key_permissions,
    ),
    url(
        r"^org_admin/key_permissions/update$",
        peeringdb_server.api_key_views.key_permission_update,
    ),
    url(
        r"^org_admin/key_permissions/remove$",
        peeringdb_server.api_key_views.key_permission_remove,
    ),
    url(r"^data/countries$", peeringdb_server.data_views.countries),
    url(r"^data/sponsors$", peeringdb_server.data_views.sponsorships),
    url(r"^data/countries_b$", peeringdb_server.data_views.countries_w_blank),
    url(r"^data/facilities$", peeringdb_server.data_views.facilities),
    url(r"^data/enum/(?P<name>[\w_]+)$", peeringdb_server.data_views.enum),
    url(r"^data/asns$", peeringdb_server.data_views.asns),
    url(r"^data/organizations$", peeringdb_server.data_views.organizations),
    url(r"^data/my_organizations$", peeringdb_server.data_views.my_organizations),
    url(r"^data/locales$", peeringdb_server.data_views.languages),
    url(r"^export/ix/(?P<ix_id>\d+)/ixp-member-list$", view_export_ixf_ix_members),
    url(
        r"^export/ixlan/(?P<ixlan_id>\d+)/ixp-member-list$",
        view_export_ixf_ixlan_members,
    ),
    url(
        r"^export/advanced-search/(?P<tag>[\w_]+)/(?P<fmt>[\w_-]+)$",
        AdvancedSearchExportView.as_view(),
    ),
    url(r"^import/ixlan/(?P<ixlan_id>\d+)/ixf/preview$", view_import_ixlan_ixf_preview),
    url(r"^import/net/(?P<net_id>\d+)/ixf/postmortem$", view_import_net_ixf_postmortem),
    url(r"^import/net/(?P<net_id>\d+)/ixf/preview$", view_import_net_ixf_preview),
    url(r"^$", view_index),
    url(r"^i18n/", include("django.conf.urls.i18n")),
    url("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    url(r"^(net|ix|fac|org|asn)/translate$", request_translation),
    url(r"^suggest/(?P<reftag>fac)$", view_suggest),
    url(r"^maintenance$", view_maintenance, name="maintenance"),
]

# o
# REST API

urlpatterns += [
    url(r"^api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    url(
        r"^apidocs/swagger/",
        TemplateView.as_view(
            template_name="apidocs/swagger.html",
            extra_context={"schema_url": "openapi-schema"},
        ),
        name="swagger-ui",
    ),
    url(
        r"^apidocs/",
        TemplateView.as_view(
            template_name="apidocs/redoc.html",
            extra_context={"schema_url": "openapi-schema"},
        ),
        name="redoc-ui",
    ),
    url(r"^api/", include(peeringdb_server.rest.urls)),
]

# AUTOCOMPLETE

urlpatterns += [
    url(
        r"^autocomplete/fac/net/(?P<net_id>\d+)/$",
        FacilityAutocompleteForNetwork.as_view(),
        name="autocomplete-fac-net",
    ),
    url(
        r"^autocomplete/fac/ix/(?P<ix_id>\d+)/$",
        FacilityAutocompleteForExchange.as_view(),
        name="autocomplete-fac-ix",
    ),
    url(
        r"^autocomplete/org/$",
        OrganizationAutocomplete.as_view(),
        name="autocomplete-org",
    ),
    url(
        r"^autocomplete/ix/json$",
        ExchangeAutocompleteJSON.as_view(),
        name="autocomplete-ix-json",
    ),
    url(r"^autocomplete/ix$", ExchangeAutocomplete.as_view(), name="autocomplete-ix"),
    url(
        r"^autocomplete/fac/json$",
        FacilityAutocompleteJSON.as_view(),
        name="autocomplete-fac-json",
    ),
    url(r"^autocomplete/fac$", FacilityAutocomplete.as_view(), name="autocomplete-fac"),
    url(r"^autocomplete/net$", NetworkAutocomplete.as_view(), name="autocomplete-net"),
    url(
        r"^autocomplete/ixlan/$", IXLanAutocomplete.as_view(), name="autocomplete-ixlan"
    ),
    url(
        r"^autocomplete/admin/deletedversions$",
        DeletedVersionAutocomplete.as_view(),
        name="autocomplete-admin-deleted-versions",
    ),
]
# Admin CSV export for pdb_validate_data command
urlpatterns += [
    path(
        "pdb_validate_data/export/<cache_id>",
        validator_result_cache,
    )
]
# Admin autocomplete for commandlinetool history

urlpatterns += [
    url(
        rf"^autocomplete/admin/clt-history/{tool_id}/$",
        ToolHistory.as_view(),
        name=f"autocomplete-admin-clt-history-{tool_id}",
    )
    for tool_id, ToolHistory in list(clt_history.items())
]


# Oauth2
urlpatterns += [
    url(r"^oauth2/authorize/", AuthorizationView.as_view(), name="authorize"),
]
urlpatterns += [
    url(r"^oauth2/", include("oauth2_provider.urls", namespace="oauth2_provider")),
]

# DEBUG
if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        url(r"^__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
