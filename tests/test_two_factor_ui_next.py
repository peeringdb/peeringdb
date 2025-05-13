from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase, override_settings
from django.views.generic.base import TemplateView

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
