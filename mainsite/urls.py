from django.conf import settings
from django.conf.urls.static import static

# auto admin
from django.contrib import admin
from django.urls import include, re_path
from django.views.generic.base import RedirectView
from two_factor.urls import urlpatterns as tf_urls

from peeringdb_server.two_factor_ui_next import (
    BackupTokensView,
    LoginView,
    ProfileView,
    QRGeneratorView,
    SetupCompleteView,
    TwoFactorDisableView,
    TwoFactorSetupView,
)

admin.autodiscover()

import allauth.account.views

import peeringdb_server.urls
from peeringdb_server.autocomplete_views import GrappelliHandlerefAutocomplete

tf_urls[0][0] = re_path(
    r"^account/login/$",
    LoginView.as_view(),
    name="login",
)

tf_urls[0][-1] = re_path(
    r"^account/disable-2fa/$",
    TwoFactorDisableView.as_view(),
    name="disable",
)

tf_urls[0][1] = re_path(
    r"^account/two_factor/setup/$",
    TwoFactorSetupView.as_view(),
    name="setup",
)

tf_urls[0][2] = re_path(
    r"^account/two_factor/backup/tokens/$",
    BackupTokensView.as_view(),
    name="backup_tokens",
)

tf_urls[0][3] = re_path(
    r"^account/two_factor/$",
    ProfileView.as_view(),
    name="profile",
)

tf_urls[0][4] = re_path(
    r"^account/two_factor/qrcode/$",
    QRGeneratorView.as_view(),
    name="qr",
)

tf_urls[0][5] = re_path(
    r"^account/two_factor/setup/complete/$",
    SetupCompleteView.as_view(),
    name="setup_complete",
)

urlpatterns = [
    # override grappelli autocomplete handler
    re_path(
        r"^grappelli/lookup/autocomplete/$",
        GrappelliHandlerefAutocomplete.as_view(),
        name="grp_autocomplete_lookup",
    ),
    # grappelli admin interface improvements
    re_path(r"^grappelli/", include("grappelli.urls")),
    # FIXME: adapt to DAL3 changes
    # url(r'^autocomplete/',  include('dal.urls')),
    # FIXME: can remove this if we upgrade to allauth > 0.24.2, upgrade
    # has been held off at this point because it requires migrations
    re_path(
        r"^accounts/confirm-email/(?P<key>[-:\w]+)/$",
        allauth.account.views.confirm_email,
        name="account_confirm_email",
    ),
    re_path(r"^accounts/", include("allauth.urls")),
    re_path(
        r"^cp/peeringdb_server/organizationmerge/add/",
        RedirectView.as_view(
            url="/cp/peeringdb_server/organization/org-merge-tool", permanent=False
        ),
    ),
    re_path(r"^cp/", admin.site.urls),
    re_path(r"", include(tf_urls)),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    re_path(r"^captcha/", include("captcha.urls")),
]

urlpatterns += peeringdb_server.urls.urlpatterns

# append the login view again,so the name is available for reverse lookups
urlpatterns += [tf_urls[0][0]]

handler_404 = "peeringdb_server.views.view_http_error_404"
handler_403 = "peeringdb_server.views.view_http_error_403"
