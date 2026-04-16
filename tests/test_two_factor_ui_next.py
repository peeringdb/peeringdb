from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.views.generic.base import TemplateView
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from peeringdb_server.two_factor_ui_next import UIAwareMixin
from peeringdb_server.util import resolve_template


class DummyView(UIAwareMixin, TemplateView):
    template_name = "two_factor/profile.html"


class ResolveTemplateTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_resolve_template_unauthenticated_default_disabled(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertEqual(resolve_template(request, "site/base.html"), "site/base.html")

    @override_settings(DEFAULT_UI_NEXT_ENABLED=True)
    def test_resolve_template_unauthenticated_default_enabled(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertEqual(
            resolve_template(request, "site/base.html"), "site_next/base.html"
        )

    @override_settings(USER_OPT_FLAG_UI_NEXT=2, USER_OPT_FLAG_UI_NEXT_REJECTED=4)
    def test_resolve_template_authenticated_next_enabled(self):
        user = User(username="testuser")
        user.opt_flags = 2
        request = self.factory.get("/")
        request.user = user
        self.assertEqual(
            resolve_template(request, "two_factor/profile.html"),
            "two_factor_next/profile.html",
        )

    @override_settings(USER_OPT_FLAG_UI_NEXT=2, USER_OPT_FLAG_UI_NEXT_REJECTED=4)
    def test_resolve_template_authenticated_next_rejected(self):
        user = User(username="testuser")
        user.opt_flags = 2 | 4
        request = self.factory.get("/")
        request.user = user
        self.assertEqual(
            resolve_template(request, "two_factor/profile.html"),
            "two_factor/profile.html",
        )

    @override_settings(USER_OPT_FLAG_UI_NEXT=2)
    def test_uiaware_mixin_template_resolution(self):
        user = User(username="testuser")
        user.opt_flags = 2
        request = self.factory.get("/")
        request.user = user

        view = DummyView()
        view.request = request
        templates = view.get_template_names()

        self.assertEqual(templates[0], "two_factor_next/profile.html")


class BackupTokensViewDispatchTests(TestCase):
    """
    Tests for BackupTokensView.dispatch to verify that users who have TOTP set
    up but logged in via passkey can access the backup tokens page without being
    redirected by otp_required (which doesn't recognize passkey as OTP-verified).

    Regression test for https://github.com/peeringdb/peeringdb/issues/1911
    """

    @classmethod
    def setUpTestData(cls):
        UserModel = get_user_model()
        cls.user = UserModel.objects.create_user(
            username="backup_test_user",
            email="backup_test@example.com",
            password="testpassword123",
        )

    def setUp(self):
        self.client = Client()
        self.url = reverse("two_factor:backup_tokens")

    def test_unauthenticated_user_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/login/", response["Location"])

    def test_dispatch_with_mfa_amr_bypasses_otp_required(self):
        """Passkey + security key login (amr contains 'mfa') can access backup tokens."""
        self.client.force_login(self.user)
        session = self.client.session
        session["amr"] = ["mfa"]
        session.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_dispatch_with_passkey_auth_bypasses_otp_required(self):
        """Passkey-only login (used_passkey_auth in session) can access backup tokens."""
        self.client.force_login(self.user)
        session = self.client.session
        session["used_passkey_auth"] = True
        session.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_dispatch_without_mfa_session_redirects(self):
        """Logged-in user whose OTP device is not verified and has no passkey session markers is redirected by otp_required."""
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)

    def test_dispatch_with_verified_totp_allows_access(self):
        """Standard password + TOTP login with a verified OTP device can access backup tokens."""
        device = TOTPDevice.objects.create(user=self.user, name="default", confirmed=True)
        self.client.force_login(self.user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
