import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.parametrize(
    "method,path",
    (
        # login also gets `private` + `no-store` from two_factor's own
        # `never_cache`; this row asserts our local guarantee on `LoginView`
        # holds regardless of that upstream decorator
        ("get", "/account/login/"),
        ("get", "/register"),
        ("get", "/reset-password"),
        ("get", "/username-retrieve"),
        # POST without form data returns a 400 JsonResponse -- the header
        # must land on error paths too, hence `no_store_private` outermost
        ("post", "/username-retrieve/initiate"),
        # bogus key still routes through the wrapped confirm-email view
        ("get", "/accounts/confirm-email/bogus-key/"),
    ),
)
@pytest.mark.django_db
def test_auth_views_cache_control(method, path):
    """
    Session-bearing anonymous auth views (the #1205 middleware allowlist)
    must respond with `Cache-Control: private, no-store` so shared proxies
    never cache a response carrying `Set-Cookie` / CSRF state (#2032).
    """

    client = Client()
    response = getattr(client, method)(path)

    # compare directives, not the full header string -- other decorators
    # (e.g. `never_cache` on the two_factor login) may add more
    directives = {
        directive.strip() for directive in response["Cache-Control"].split(",")
    }
    assert "private" in directives
    assert "no-store" in directives


# `django_db` needed only because conftest's autouse `cleanup` fixture
# clears the db-backed caches
@pytest.mark.django_db
def test_account_confirm_email_url_unchanged():
    """
    Middleware and templates reverse `account_confirm_email` with a `key`
    kwarg -- shadowing the route in `mainsite.urls` (#2032) must not
    change the URL shape.
    """

    assert reverse("account_confirm_email", kwargs={"key": "x"}) == (
        "/accounts/confirm-email/x/"
    )
