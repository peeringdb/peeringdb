from django.conf.urls import include, url
from django.conf import settings
from rest_framework_swagger.views import get_swagger_view

import peeringdb_server.rest

from peeringdb_server.models import (InternetExchange, Network, Facility,
                                     Organization)

from peeringdb_server.autocomplete_views import (
    FacilityAutocompleteForNetwork, FacilityAutocompleteForExchange,
    OrganizationAutocomplete, ExchangeAutocomplete, ExchangeAutocompleteJSON,
    IXLanAutocomplete, FacilityAutocomplete, FacilityAutocompleteJSON,
    clt_history)

from peeringdb_server.export_views import (
    view_export_ixf_ix_members,
    view_export_ixf_ixlan_members,
    AdvancedSearchExportView,
)

from peeringdb_server.import_views import (
    view_import_ixlan_ixf_preview,
)

from django.views.i18n import JavaScriptCatalog

# o
# SITE

from peeringdb_server.views import (
    view_index,
    view_login,
    view_registration,
    view_password_reset,
    view_password_change,
    view_set_user_locale,
    view_network,
    view_network_by_asn,
    view_network_by_query,
    view_suggest,
    view_exchange,
    view_facility,
    view_organization,
    view_affiliate_to_org,
    view_request_ownership,
    view_verify,
    view_profile,
    view_profile_v1,
    view_advanced_search,
    view_sponsorships,
    view_partnerships,
    view_aup,
    view_username_retrieve,
    view_username_retrieve_initiate,
    view_username_retrieve_complete,
    view_maintenance,
    resend_confirmation_mail,
    request_login,
    request_logout,
    request_api_search,
    request_search,
    request_translation,
)
import peeringdb_server.org_admin_views
import peeringdb_server.data_views

urlpatterns = [
    url(r'^api_search$', request_api_search),
    url(r'^search$', request_search),
    url(r'^advanced_search', view_advanced_search),
    url(r'^auth$', request_login),
    url(r'^logout$', request_logout),
    url(r'^login$', view_login),
    url(r'^register$', view_registration),
    url(r'^reset-password$', view_password_reset),
    url(r'^change-password$', view_password_change),
    url(r'^set-user-locale$', view_set_user_locale),
    url(r'^username-retrieve/initiate$', view_username_retrieve_initiate),
    url(r'^username-retrieve/complete$', view_username_retrieve_complete),
    url(r'^username-retrieve$', view_username_retrieve),
    url(r'^verify$', view_verify),
    url(r'^profile$', view_profile),
    url(r'^profile/v1$', view_profile_v1),
    url(r'^resend_email_confirmation$', resend_confirmation_mail),
    url(r'^sponsors$', view_sponsorships),
    url(r'^partners$', view_partnerships),
    url(r'^aup$', view_aup),
    url(r'^affiliate-to-org$', view_affiliate_to_org),
    url(r'^request-ownership$', view_request_ownership),
    url(r'^%s/(?P<id>\d+)/?$' % Network.handleref.tag, view_network),
    url(r'^%s/(?P<id>\d+)/?$' % InternetExchange.handleref.tag, view_exchange),
    url(r'^%s/(?P<id>\d+)/?$' % Facility.handleref.tag, view_facility),
    url(r'^%s/(?P<id>\d+)/?$' % Organization.handleref.tag, view_organization),
    url(r'^%s$' % Network.handleref.tag, view_network_by_query),
    url(r'^asn/(?P<asn>\d+)/?$', view_network_by_asn),
    url(r'^org_admin/users$', peeringdb_server.org_admin_views.users),
    url(r'^org_admin/user_permissions$',
        peeringdb_server.org_admin_views.user_permissions),
    url(r'^org_admin/user_permissions/update$',
        peeringdb_server.org_admin_views.user_permission_update),
    url(r'^org_admin/user_permissions/remove$',
        peeringdb_server.org_admin_views.user_permission_remove),
    url(r'^org_admin/permissions$',
        peeringdb_server.org_admin_views.permissions),
    url(r'^org_admin/uoar/approve$',
        peeringdb_server.org_admin_views.uoar_approve),
    url(r'^org_admin/uoar/deny$', peeringdb_server.org_admin_views.uoar_deny),
    url(r'^org_admin/manage_user/update$',
        peeringdb_server.org_admin_views.manage_user_update),
    url(r'^org_admin/manage_user/delete$',
        peeringdb_server.org_admin_views.manage_user_delete),
    url(r'^data/countries$', peeringdb_server.data_views.countries),
    url(r'^data/countries_b$', peeringdb_server.data_views.countries_w_blank),
    url(r'^data/facilities$', peeringdb_server.data_views.facilities),
    url(r'^data/enum/(?P<name>[\w_]+)$', peeringdb_server.data_views.enum),
    url(r'^data/asns$', peeringdb_server.data_views.asns),
    url(r'^data/organizations$', peeringdb_server.data_views.organizations),
    url(r'^data/locales$', peeringdb_server.data_views.languages),
    url(r'^export/ix/(?P<ix_id>\d+)/ixp-member-list$',
        view_export_ixf_ix_members),
    url(r'^export/ixlan/(?P<ixlan_id>\d+)/ixp-member-list$',
        view_export_ixf_ixlan_members),
    url(r'^export/advanced-search/(?P<tag>[\w_]+)/(?P<fmt>[\w_-]+)$',
        AdvancedSearchExportView.as_view()),
    url(r'^import/ixlan/(?P<ixlan_id>\d+)/ixf/preview$',
        view_import_ixlan_ixf_preview),
    url(r'^$', view_index),
    url(r'^i18n/', include('django.conf.urls.i18n')),
    url('jsi18n/', JavaScriptCatalog.as_view(), name='javascript-catalog'),
    url(r'^(net|ix|fac|org|asn)/translate$', request_translation),
    url(r'^suggest/(?P<reftag>fac)$', view_suggest),
    url(r'^maintenance$', view_maintenance, name="maintenance")
]

# o
# REST API

urlpatterns += [
    url(r'^api/', include(peeringdb_server.rest.urls)),
    url(r'^api-auth/',
        include('rest_framework.urls', namespace='rest_framework')),
    url(r'^apidocs/', get_swagger_view(title="PeeringDB API")),
]

# AUTOCOMPLETE

urlpatterns += [
    url(r'^autocomplete/fac/net/(?P<net_id>\d+)/$',
        FacilityAutocompleteForNetwork.as_view(), name="autocomplete-fac-net"),
    url(r'^autocomplete/fac/ix/(?P<ix_id>\d+)/$',
        FacilityAutocompleteForExchange.as_view(), name="autocomplete-fac-ix"),
    url(r'^autocomplete/org/$', OrganizationAutocomplete.as_view(),
        name="autocomplete-org"),
    url(r'^autocomplete/ix/json$', ExchangeAutocompleteJSON.as_view(),
        name="autocomplete-ix-json"),
    url(r'^autocomplete/ix$', ExchangeAutocomplete.as_view(),
        name="autocomplete-ix"),
    url(r'^autocomplete/fac/json$', FacilityAutocompleteJSON.as_view(),
        name="autocomplete-fac-json"),
    url(r'^autocomplete/fac$', FacilityAutocomplete.as_view(),
        name="autocomplete-fac"),
    url(r'^autocomplete/ixlan/$', IXLanAutocomplete.as_view(),
        name="autocomplete-ixlan"),
]

# Admin autocomplete for commandlinetool history

urlpatterns += [
    url(r'^autocomplete/admin/clt-history/{}/$'.format(tool_id),
        ToolHistory.as_view(),
        name="autocomplete-admin-clt-history-{}".format(tool_id))
    for tool_id, ToolHistory in clt_history.items()
]

# Oauth2

urlpatterns += [
    url(r'^oauth2/',
        include('oauth2_provider.urls', namespace='oauth2_provider')),
]

# DEBUG
if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        url(r'^__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns
