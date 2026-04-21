from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from peeringdb_server.context_processors import (
    notification_banner,
    theme_mode,
    ui_version,
)
from peeringdb_server.models import EnvironmentSetting

User = get_user_model()


class ContextProcessorTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_anonymous_user(self):
        request = self.factory.get("/")
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()
        context = ui_version(request)
        self.assertEqual(context["ui_next"], settings.DEFAULT_UI_NEXT_ENABLED)

    def test_authenticated_user_enabled(self):
        user = User.objects.create(
            username="u1", opt_flags=settings.USER_OPT_FLAG_UI_NEXT
        )
        request = self.factory.get("/")
        request.user = user
        context = ui_version(request)
        self.assertTrue(context["ui_next"])

    def test_authenticated_user_rejected(self):
        user = User.objects.create(
            username="u2", opt_flags=settings.USER_OPT_FLAG_UI_NEXT_REJECTED
        )
        request = self.factory.get("/")
        request.user = user
        context = ui_version(request)
        self.assertFalse(context["ui_next"])

    def test_theme_mode_default(self):
        request = self.factory.get("/")
        context = theme_mode(request)
        assert context["theme_mode"] == "light"
        assert context["prefers_dark_mode"] is False

    def test_theme_mode_dark_enabled(self):
        request = self.factory.get("/")
        request.COOKIES["theme"] = "dark"
        request.COOKIES["is_dark_mode"] = "true"
        context = theme_mode(request)
        assert context["theme_mode"] == "dark"
        assert context["prefers_dark_mode"] is True

    def test_theme_mode_dark_cookie_false_flag(self):
        request = self.factory.get("/")
        request.COOKIES["theme"] = "dark"
        request.COOKIES["is_dark_mode"] = "false"
        context = theme_mode(request)
        assert context["theme_mode"] == "dark"
        assert context["prefers_dark_mode"] is False

    def test_theme_mode_unexpected_values(self):
        request = self.factory.get("/")
        request.COOKIES["theme"] = "test"
        request.COOKIES["is_dark_mode"] = "test"
        context = theme_mode(request)
        assert context["theme_mode"] == "test"
        assert context["prefers_dark_mode"] is False

    def test_notification_banner_falls_back_to_setting(self):
        # With no EnvironmentSetting row, the context processor must
        # return the Django setting value (populated from env var or default).
        EnvironmentSetting.objects.filter(
            setting="NOTIFICATION_BANNER_CONTENT"
        ).delete()
        request = self.factory.get("/")
        with self.settings(NOTIFICATION_BANNER_CONTENT="<b>hi</b>"):
            context = notification_banner(request)
        assert context["NOTIFICATION_BANNER_CONTENT"] == "<b>hi</b>"

    def test_notification_banner_db_override(self):
        # An EnvironmentSetting row must take precedence over the Django
        # setting — this is what allows staff to set it via the admin.
        EnvironmentSetting.objects.filter(
            setting="NOTIFICATION_BANNER_CONTENT"
        ).delete()
        user = User.objects.create(username="banner_admin")
        EnvironmentSetting.objects.create(
            setting="NOTIFICATION_BANNER_CONTENT",
            value_str='<a href="/elections">Vote now</a>',
            user=user,
        )
        request = self.factory.get("/")
        with self.settings(NOTIFICATION_BANNER_CONTENT="fallback"):
            context = notification_banner(request)
        assert (
            context["NOTIFICATION_BANNER_CONTENT"]
            == '<a href="/elections">Vote now</a>'
        )
