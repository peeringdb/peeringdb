import allauth.account.views
from django.conf import settings
from django.conf.urls.static import static

# auto admin
from django.contrib import admin
from django.urls import include, re_path
from django.views.generic.base import RedirectView
from two_factor.urls import urlpatterns as tf_urls

import peeringdb_server.urls
from peeringdb_server.autocomplete_views import (
    GrappelliHandlerefAutocomplete,
    PDBAdminM2MLookup,
    PDBAdminRelatedLookup,
)
from peeringdb_server.two_factor_ui_next import (
    BackupTokensView,
    LoginView,
    ProfileView,
    QRGeneratorView,
    SetupCompleteView,
    TwoFactorDisableView,
    TwoFactorSetupView,
)
from peeringdb_server.util import no_store_private

admin.autodiscover()


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
    # override grappelli's lookup handlers so they enforce admin
    # permissions; must precede the grappelli.urls include
    re_path(
        r"^grappelli/lookup/related/$",
        PDBAdminRelatedLookup.as_view(),
        name="grp_related_lookup",
    ),
    re_path(
        r"^grappelli/lookup/m2m/$",
        PDBAdminM2MLookup.as_view(),
        name="grp_m2m_lookup",
    ),
    re_path(
        r"^grappelli/lookup/autocomplete/$",
        GrappelliHandlerefAutocomplete.as_view(),
        name="grp_autocomplete_lookup",
    ),
    # grappelli admin interface improvements
    re_path(r"^grappelli/", include("grappelli.urls")),
    # allauth only serves email confirmation, which our emails link to; its
    # other views skip the project's login, signup, reset and email policies,
    # so they redirect to our pages or are not routed. The confirm-email
    # pattern is allauth's own, its name is reversed by middleware and
    # templates, and no_store_private keeps it out of shared caches (#2032).
    re_path(
        r"^accounts/confirm-email/(?P<key>[-:\w]+)/$",
        no_store_private(allauth.account.views.confirm_email),
        name="account_confirm_email",
    ),
    re_path(
        r"^accounts/login/$",
        RedirectView.as_view(pattern_name="two_factor:login", query_string=True),
        name="account_login",
    ),
    # DRF's browsable-API login is a plain password login; send it through
    # the wizard too (the rest_framework include stays for its logout and
    # reverse names). /cp/login/ is redirected by two_factor's patch_admin.
    re_path(
        r"^api-auth/login/$",
        RedirectView.as_view(pattern_name="two_factor:login", query_string=True),
    ),
    re_path(
        r"^accounts/password/reset/$",
        RedirectView.as_view(pattern_name="reset-password"),
        name="account_reset_password",
    ),
    re_path(
        r"^accounts/password/change/$",
        RedirectView.as_view(pattern_name="user-profile"),
        name="account_change_password",
    ),
    re_path(
        r"^accounts/email/$",
        RedirectView.as_view(pattern_name="user-profile"),
        name="account_email",
    ),
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

# django resolves these as `handler404` / `handler403` on the urlconf module;
# they were spelled with an underscore since bff6f7f2 and therefore never read (#2032)
handler400 = "peeringdb_server.views.view_http_error_400"
handler404 = "peeringdb_server.views.view_http_error_404"
handler403 = "peeringdb_server.views.view_http_error_403"
