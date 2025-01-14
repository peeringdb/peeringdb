"""
Django url to view routing.
"""

import django_security_keys.views as security_keys_views
from django.conf import settings
from django.urls import include, path, re_path
from django.views.generic import RedirectView, TemplateView
from django.views.i18n import JavaScriptCatalog
from oauth2_provider.views import ConnectDiscoveryInfoView

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
    FacilityAutocompleteForOrganization,
    FacilityAutocompleteJSON,
    InternetExchangeFacilityAutoComplete,
    IXLanAutocomplete,
    NetworkAutocomplete,
    NetworkFacilityAutocomplete,
    OrganizationAutocomplete,
    clt_history,
)
from peeringdb_server.export_views import (
    AdvancedSearchExportView,
    kmz_download,
    view_export_ixf_ix_members,
    view_export_ixf_ixlan_members,
)
from peeringdb_server.import_views import (
    view_import_ixlan_ixf_preview,
    view_import_net_ixf_postmortem,
    view_import_net_ixf_preview,
)
from peeringdb_server.models import (
    Campus,
    Carrier,
    Facility,
    InternetExchange,
    Network,
    Organization,
)
from peeringdb_server.oauth_views import AuthorizationView, OAuthMetadataView
from peeringdb_server.verified_update.views import (
    view_verified_update,
    view_verified_update_accept,
)
from peeringdb_server.views import (
    OrganizationLogoUpload,
    cancel_affiliation_request,
    handle_2fa,
    network_dismiss_ixf_proposal,
    network_reset_ixf_proposals,
    profile_add_email,
    profile_delete_email,
    profile_set_primary_email,
    request_api_search,
    request_logout,
    request_search,
    request_search_v2,
    request_translation,
    resend_confirmation_mail,
    search_elasticsearch,
    unwatch_network,
    validator_result_cache,
    view_about,
    view_advanced_search,
    view_affiliate_to_org,
    view_aup,
    view_campus,
    view_carrier,
    view_close_account,
    view_exchange,
    view_facility,
    view_healthcheck,
    view_index,
    view_maintenance,
    view_name_change,
    view_network,
    view_network_by_asn,
    view_network_by_query,
    view_organization,
    view_password_change,
    view_password_reset,
    view_profile,
    view_profile_passkey,
    view_profile_v1,
    view_registration,
    view_remove_org_affiliation,
    view_request_ownership,
    view_self_entity,
    view_set_user_locale,
    view_set_user_org,
    view_sponsorships,
    view_suggest,
    view_username_change,
    view_username_retrieve,
    view_username_retrieve_complete,
    view_username_retrieve_initiate,
    view_verify,
    watch_network,
)

# SITE


urlpatterns = [
    re_path(
        r"^robots.txt$",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
    ),
    re_path(r"^api_search$", request_api_search),
    re_path(r"^search$", request_search),
    re_path(r"^search/v2$", request_search_v2),
    re_path(r"^advanced_search", view_advanced_search),
    re_path(r"^logout$", request_logout),
    re_path(
        r"^login$",
        RedirectView.as_view(pattern_name="two_factor:login", permanent=True),
    ),
    re_path(r"^account/passkey$", view_profile_passkey, name="profile_passkey"),
    re_path(r"^register$", view_registration, name="register"),
    re_path(r"^reset-password$", view_password_reset, name="reset-password"),
    re_path(r"^change-password$", view_password_change),
    re_path(r"^change-username$", view_username_change),
    re_path(r"^change-name", view_name_change, name="change-name"),
    re_path(r"^set-user-locale$", view_set_user_locale),
    re_path(
        r"^username-retrieve/initiate$",
        view_username_retrieve_initiate,
        name="username-retrieve-initiate",
    ),
    re_path(r"^username-retrieve/complete$", view_username_retrieve_complete),
    re_path(r"^username-retrieve$", view_username_retrieve, name="username-retrieve"),
    re_path(r"^verify$", view_verify),
    re_path(r"^profile$", view_profile, name="user-profile"),
    re_path(r"^profile/close$", view_close_account, name="close-account"),
    re_path(r"^profile/v1$", view_profile_v1),
    re_path(r"^profile/email/add", profile_add_email, name="profile-add-email"),
    re_path(
        r"^profile/email/delete", profile_delete_email, name="profile-remove-email"
    ),
    re_path(
        r"^profile/email/primary",
        profile_set_primary_email,
        name="profile-set-primary-email",
    ),
    re_path(r"^resend_email_confirmation$", resend_confirmation_mail),
    re_path(r"^sponsors$", view_sponsorships, name="sponsors"),
    # re_path(r'^partners$', view_partnerships),
    re_path(r"^aup$", view_aup, name="aup"),
    re_path(r"^about$", view_about, name="about"),
    re_path(r"^affiliate-to-org$", view_affiliate_to_org),
    path(
        "org/<str:id>/upload-logo",
        OrganizationLogoUpload.as_view(),
        name="org-logo-upload",
    ),
    re_path(
        r"^cancel-affiliation-request/(?P<uoar_id>\d+)/$",
        cancel_affiliation_request,
        name="cancel-affiliation-request",
    ),
    re_path(r"^request-ownership$", view_request_ownership),
    re_path(r"^verified-update/$", view_verified_update),
    re_path(r"^verified-update/accept/$", view_verified_update_accept),
    re_path(
        r"^%s/(?P<net_id>\d+)/dismiss-ixf-proposal/(?P<ixf_id>\d+)/$"
        % Network.handleref.tag,
        network_dismiss_ixf_proposal,
        name="net-dismiss-ixf-proposal",
    ),
    re_path(
        r"^%s/(?P<net_id>\d+)/reset-ixf-proposals/$" % Network.handleref.tag,
        network_reset_ixf_proposals,
        name="net-reset-ixf-proposals",
    ),
    re_path(
        r"^%s/(?P<id>\d+)/?$" % Network.handleref.tag, view_network, name="net-view"
    ),
    re_path(
        r"^%s/(?P<id>\d+)/watch/?$" % Network.handleref.tag,
        watch_network,
        name="net-watch",
    ),
    re_path(
        r"^%s/(?P<id>\d+)/unwatch/?$" % Network.handleref.tag,
        unwatch_network,
        name="net-unwatch",
    ),
    re_path(
        r"^%s/(?P<id>\d+)/?$" % InternetExchange.handleref.tag,
        view_exchange,
        name="ix-view",
    ),
    re_path(
        r"^%s/(?P<id>\d+)/?$" % Facility.handleref.tag, view_facility, name="fac-view"
    ),
    re_path(
        r"^%s/(?P<id>\d+)/?$" % Carrier.handleref.tag, view_carrier, name="carrier-view"
    ),
    re_path(
        r"^%s/(?P<id>\d+)/?$" % Campus.handleref.tag, view_campus, name="campus-view"
    ),
    re_path(
        r"^%s/(?P<id>\d+)/?$" % Organization.handleref.tag,
        view_organization,
        name="org-view",
    ),
    re_path(r"^(net|ix|org|fac|carrier|campus)/self$", view_self_entity),
    re_path(r"^set-organization/$", view_set_user_org, name="set-organization"),
    re_path(
        r"^remove-affiliation/$", view_remove_org_affiliation, name="remove-affiliation"
    ),
    re_path(r"^%s$" % Network.handleref.tag, view_network_by_query),
    re_path(r"^asn/(?P<asn>\d+)/?$", view_network_by_asn, name="net-view-asn"),
    re_path(r"^user_keys/add$", peeringdb_server.api_key_views.add_user_key),
    re_path(r"^user_keys/revoke$", peeringdb_server.api_key_views.remove_user_key),
    re_path(
        r"^security_keys/request_registration$",
        security_keys_views.request_registration,
        name="security-keys-request-registration",
    ),
    re_path(
        r"^security_keys/request_authentication$",
        security_keys_views.request_authentication,
        name="security-keys-request-authentication",
    ),
    re_path(
        r"^security_keys/verify_authentication$",
        security_keys_views.verify_authentication,
    ),
    re_path(r"^security_keys/add$", security_keys_views.register_security_key),
    re_path(r"^security_keys/remove$", security_keys_views.remove_security_key),
    re_path(r"^org_admin/users$", peeringdb_server.org_admin_views.users),
    re_path(
        r"^org_admin/user_permissions$",
        peeringdb_server.org_admin_views.user_permissions,
    ),
    re_path(
        r"^org_admin/user_permissions/update$",
        peeringdb_server.org_admin_views.user_permission_update,
    ),
    re_path(
        r"^org_admin/user_permissions/remove$",
        peeringdb_server.org_admin_views.user_permission_remove,
    ),
    re_path(r"^org_admin/permissions$", peeringdb_server.org_admin_views.permissions),
    re_path(r"^org_admin/uoar/approve$", peeringdb_server.org_admin_views.uoar_approve),
    re_path(r"^org_admin/uoar/deny$", peeringdb_server.org_admin_views.uoar_deny),
    re_path(
        r"^org_admin/manage_user/update$",
        peeringdb_server.org_admin_views.manage_user_update,
    ),
    re_path(
        r"^org_admin/user_options$",
        peeringdb_server.org_admin_views.update_user_options,
        name="org-admin-user-options",
    ),
    re_path(r"^org_admin/handle-2fa$", handle_2fa, name="handle-2fa"),
    re_path(
        r"^org_admin/manage_user/delete$",
        peeringdb_server.org_admin_views.manage_user_delete,
    ),
    re_path(
        r"^org_admin/manage_key/add$", peeringdb_server.api_key_views.manage_key_add
    ),
    re_path(
        r"^org_admin/manage_key/update$",
        peeringdb_server.api_key_views.manage_key_update,
    ),
    re_path(
        r"^org_admin/manage_key/revoke$",
        peeringdb_server.api_key_views.manage_key_revoke,
    ),
    re_path(
        r"^org_admin/key_permissions$",
        peeringdb_server.api_key_views.key_permissions,
    ),
    re_path(
        r"^org_admin/key_permissions/update$",
        peeringdb_server.api_key_views.key_permission_update,
    ),
    re_path(
        r"^org_admin/key_permissions/remove$",
        peeringdb_server.api_key_views.key_permission_remove,
    ),
    re_path(
        r"^data/countries$",
        peeringdb_server.data_views.countries,
        name="data-countries",
    ),
    re_path(
        r"^data/sponsors$",
        peeringdb_server.data_views.sponsorships,
        name="data-sponsors",
    ),
    re_path(
        r"^data/countries_b$",
        peeringdb_server.data_views.countries_w_blank,
        name="data-countries",
    ),
    re_path(
        r"^data/facilities$",
        peeringdb_server.data_views.facilities,
        name="data-facilities",
    ),
    re_path(
        r"^data/enum/(?P<name>[\w_]+)$",
        peeringdb_server.data_views.enum,
        name="data-enum",
    ),
    re_path(r"^data/asns$", peeringdb_server.data_views.asns, name="data-asns"),
    re_path(
        r"^data/organizations$",
        peeringdb_server.data_views.organizations,
        name="data-organizations",
    ),
    re_path(r"^data/my_organizations$", peeringdb_server.data_views.my_organizations),
    re_path(
        r"^data/locales$", peeringdb_server.data_views.languages, name="data-locales"
    ),
    re_path(
        r"^data/campus_facilities$",
        peeringdb_server.data_views.campus_facilities,
        name="data-campus-facilities",
    ),
    re_path(r"^export/ix/(?P<ix_id>\d+)/ixp-member-list$", view_export_ixf_ix_members),
    re_path(
        r"^export/ixlan/(?P<ixlan_id>\d+)/ixp-member-list$",
        view_export_ixf_ixlan_members,
    ),
    re_path(
        r"^export/advanced-search/(?P<tag>[\w_]+)/(?P<fmt>[\w_-]+)$",
        AdvancedSearchExportView.as_view(),
    ),
    re_path(
        settings.KMZ_DOWNLOAD_PATH,
        kmz_download,
        name="kmz-download",
    ),
    re_path(
        r"^import/ixlan/(?P<ixlan_id>\d+)/ixf/preview$", view_import_ixlan_ixf_preview
    ),
    re_path(
        r"^import/net/(?P<net_id>\d+)/ixf/postmortem$", view_import_net_ixf_postmortem
    ),
    re_path(r"^import/net/(?P<net_id>\d+)/ixf/preview$", view_import_net_ixf_preview),
    re_path(r"^$", view_index, name="home"),
    re_path(r"^i18n/", include("django.conf.urls.i18n")),
    re_path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    re_path(r"^(net|ix|fac|org|asn)/translate$", request_translation),
    re_path(r"^suggest/(?P<reftag>fac)$", view_suggest),
    re_path(r"^maintenance$", view_maintenance, name="maintenance"),
    re_path(r"^healthcheck$", view_healthcheck, name="healthcheck"),
]

# o
# REST API

urlpatterns += [
    re_path(r"^api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    re_path(
        r"^apidocs/swagger/",
        TemplateView.as_view(
            template_name="apidocs/swagger.html",
            extra_context={"schema_url": "openapi-schema"},
        ),
        name="swagger-ui",
    ),
    re_path(
        r"^apidocs/",
        TemplateView.as_view(
            template_name="apidocs/redoc.html",
            extra_context={"schema_url": "openapi-schema"},
        ),
        name="redoc-ui",
    ),
    re_path(
        r"^api/",
        include((peeringdb_server.rest.urls, "peeringdb_server"), namespace="api"),
    ),
]

# AUTOCOMPLETE

urlpatterns += [
    re_path(
        r"^autocomplete/fac/net/(?P<net_id>\d+)/$",
        FacilityAutocompleteForNetwork.as_view(),
        name="autocomplete-fac-net",
    ),
    re_path(
        r"^autocomplete/fac/ix/(?P<ix_id>\d+)/$",
        FacilityAutocompleteForExchange.as_view(),
        name="autocomplete-fac-ix",
    ),
    re_path(
        r"^autocomplete/fac/org/(?P<org_id>\d+)/$",
        FacilityAutocompleteForOrganization.as_view(),
        name="autocomplete-fac-org",
    ),
    re_path(
        r"^autocomplete/org/$",
        OrganizationAutocomplete.as_view(),
        name="autocomplete-org",
    ),
    re_path(
        r"^autocomplete/ix/json$",
        ExchangeAutocompleteJSON.as_view(),
        name="autocomplete-ix-json",
    ),
    re_path(
        r"^autocomplete/ix$", ExchangeAutocomplete.as_view(), name="autocomplete-ix"
    ),
    re_path(
        r"^autocomplete/fac/json$",
        FacilityAutocompleteJSON.as_view(),
        name="autocomplete-fac-json",
    ),
    re_path(
        r"^autocomplete/fac$", FacilityAutocomplete.as_view(), name="autocomplete-fac"
    ),
    re_path(
        r"^autocomplete/net$", NetworkAutocomplete.as_view(), name="autocomplete-net"
    ),
    re_path(
        r"^autocomplete/ixlan/$", IXLanAutocomplete.as_view(), name="autocomplete-ixlan"
    ),
    re_path(
        r"^autocomplete/netfac/(?P<net_id>\d+)/$",
        NetworkFacilityAutocomplete.as_view(),
        name="autocomplete-netfac",
    ),
    re_path(
        r"^autocomplete/ixfac/(?P<ix_id>\d+)/$",
        InternetExchangeFacilityAutoComplete.as_view(),
        name="autocomplete-ixfac",
    ),
    re_path(
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
    re_path(
        rf"^autocomplete/admin/clt-history/{tool_id}/$",
        ToolHistory.as_view(),
        name=f"autocomplete-admin-clt-history-{tool_id}",
    )
    for tool_id, ToolHistory in list(clt_history.items())
]


# Oauth2
urlpatterns += [
    re_path(r"^oauth2/authorize/", AuthorizationView.as_view(), name="authorize"),
]
urlpatterns += [
    re_path(r"^oauth2/", include("oauth2_provider.urls", namespace="oauth2_provider")),
    re_path(
        r"^oauth2/\.well-known/oauth-authorization-server/?$",
        OAuthMetadataView.as_view(),
        name="oauth2_provider_metadata",
    ),
    # add both of these to root path as well
    # .well-known/openid-configuration is specifically for OpenID Connect Providers and includes OpenID-specific details.
    # .well-known/oauth-authorization-server is for OAuth 2.0 Authorization Servers and includes general OAuth 2.0 details.
    re_path(
        r"^\.well-known/openid-configuration/?$",
        ConnectDiscoveryInfoView.as_view(),
        name="oidc-connect-discovery-info",
    ),
    re_path(
        r"^\.well-known/oauth-authorization-server/?$",
        OAuthMetadataView.as_view(),
        name="oauth2_provider_metadata",
    ),
]

urlpatterns += [
    path("_search", search_elasticsearch, name="search_elasticsearch"),
]

# DEBUG
if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        re_path(r"^__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
