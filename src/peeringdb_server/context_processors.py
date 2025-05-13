from django.conf import settings
from django.contrib.auth.models import AnonymousUser


def theme_mode(request):
    """
    Add theme preferences to all template contexts
    """
    theme_mode = request.COOKIES.get("theme", "light")
    is_dark_mode = request.COOKIES.get("is_dark_mode", "false") == "true"

    return {"theme_mode": theme_mode, "prefers_dark_mode": is_dark_mode}


def ui_version(request):
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
