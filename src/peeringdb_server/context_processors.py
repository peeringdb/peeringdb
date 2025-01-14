def theme_mode(request):
    """
    Add theme preferences to all template contexts
    """
    theme_mode = request.COOKIES.get("theme", "light")
    is_dark_mode = request.COOKIES.get("is_dark_mode", "false") == "true"

    return {"theme_mode": theme_mode, "prefers_dark_mode": is_dark_mode}
