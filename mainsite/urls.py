from django.conf.urls import include, url
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic.base import RedirectView

from peeringdb_server.views import LoginView

from two_factor.urls import urlpatterns as tf_urls

# auto admin
from django.contrib import admin

admin.autodiscover()

import peeringdb_server.urls

import allauth.account.views

tf_urls[0][0] = url(
    regex=r'^account/login/$',
    view=LoginView.as_view(),
    name='login',
)

urlpatterns = [
    url(r"^grappelli/", include("grappelli.urls")),
    # FIXME: adapt to DAL3 changes
    # url(r'^autocomplete/',  include('dal.urls')),
    # FIXME: can remove this if we upgrade to allauth > 0.24.2, upgrade
    # has been held off at this point because it requires migrations
    url(
        r"^accounts/confirm-email/(?P<key>[-:\w]+)/$",
        allauth.account.views.confirm_email,
        name="account_confirm_email",
    ),
    url(r"^accounts/", include("allauth.urls")),
    url(
        r"^cp/peeringdb_server/organizationmerge/add/",
        RedirectView.as_view(
            url="/cp/peeringdb_server/organization/org-merge-tool", permanent=False
        ),
    ),
    url(r"^cp/", admin.site.urls),
    url(r'', include(tf_urls)),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    url(r"^captcha/", include("captcha.urls")),
]

urlpatterns += peeringdb_server.urls.urlpatterns

handler_404 = "peeringdb_server.views.view_http_error_404"
handler_403 = "peeringdb_server.views.view_http_error_403"
