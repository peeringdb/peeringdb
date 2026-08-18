from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest


def theme_mode(request: HttpRequest) -> dict[str, str | bool]:
    """
    Add theme preferences to all template contexts
    """
    theme_mode = request.COOKIES.get("theme", "light")
    is_dark_mode = request.COOKIES.get("is_dark_mode", "false") == "true"

    return {"theme_mode": theme_mode, "prefers_dark_mode": is_dark_mode}


def ui_version(request: HttpRequest) -> dict[str, bool]:
    """
    Context processor to determine the UI version to render
    based on user's opt-in/opt-out flags.
    """
    user = getattr(request, "user", AnonymousUser())
    context = {
        "ui_next": settings.DEFAULT_UI_NEXT_ENABLED,
    }

    if user.is_authenticated:
        context["ui_next"] = user.ui_next_enabled and not user.ui_next_rejected

    return context


def admin_config(request: HttpRequest) -> dict[str, object]:
    """
    Context processor to provide suggest entity org configuration values
    """
    return {"SUGGEST_ENTITY_ORG": settings.SUGGEST_ENTITY_ORG}


def notification_banner(request: HttpRequest) -> dict[str, object]:
    """
    Context processor that exposes the site-wide notification banner
    content to every template.

    Resolution order: EnvironmentSetting DB override, falling back to the
    NOTIFICATION_BANNER_CONTENT Django setting (which is itself populated
    from an environment variable of the same name). When the resulting
    value is empty the banner template renders nothing.
    """
    from peeringdb_server.models import EnvironmentSetting

    return {
        "NOTIFICATION_BANNER_CONTENT": EnvironmentSetting.get_setting_value(
            "NOTIFICATION_BANNER_CONTENT"
        ),
    }
