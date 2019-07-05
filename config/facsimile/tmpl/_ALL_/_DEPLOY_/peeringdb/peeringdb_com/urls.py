from django.conf.urls import include, url
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic.base import RedirectView

# auto admin
from django.contrib import admin
admin.autodiscover()

import peeringdb_server.urls

import allauth.account.views

from peeringdb_server.views import view_login


urlpatterns = [
    url(r'^grappelli/', include('grappelli.urls')),
    #FIXME: adapt to DAL3 changes
    #url(r'^autocomplete/',  include('dal.urls')),
    #FIXME: can remove this if we upgrade to allauth > 0.24.2, upgrade
    #has been held off at this point because it requires migrations
    url(r'^accounts/confirm-email/(?P<key>[-:\w]+)/$', allauth.account.views.confirm_email, name="account_confirm_email"),
    url(r'^accounts/', include('allauth.urls')),
    url(r'^cp/peeringdb_server/organizationmerge/add/', RedirectView.as_view(url='/cp/peeringdb_server/organization/org-merge-tool', permanent=False)),
    # we want to use default pdb login for admin area, since that is rate limited.
    url(r'^cp/login/', view_login),
    url(r'^cp/',  include(admin.site.urls)),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    url(r'^captcha/', include('captcha.urls')),
    ]

urlpatterns += peeringdb_server.urls.urlpatterns

handler_404 = 'peeringdb_server.views.view_http_error_404'
handler_403 = 'peeringdb_server.views.view_http_error_403'

