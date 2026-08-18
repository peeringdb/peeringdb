"""
Tests for the quick-search form markup (#2032).

The search view reads `request.GET.getlist("q")`, so the forms must submit
GET with an input named `q` — a POST form breaks no-JS search and makes the
result URL unbookmarkable, and a GET form must not carry a csrf token or the
token leaks into the query string.
"""

import pytest
from django.template.loader import render_to_string
from django.test import Client, override_settings

pytestmark = pytest.mark.django_db

# search partials that no view reachable from "/" includes; rendered directly
STANDALONE_SEARCH_TEMPLATES = [
    "site/header-search-container.html",
    "site/inline_search.html",
    "site/inline_search_hidden.html",
    "site_next/inline_search.html",
    "site_next/inline_search_hidden.html",
]


def extract_search_form(html):
    start = html.index('<form action="/search"')
    end = html.index("</form>", start)
    return html[start:end]


def assert_get_search_form(form):
    assert 'method="GET"' in form
    # a GET submit would put the token in the URL
    assert "csrfmiddlewaretoken" not in form
    # the search view only looks at the `q` param
    assert 'name="q"' in form
    assert 'name="term"' not in form


def test_landing_page_quick_search_submits_get():
    response = Client().get("/")
    assert response.status_code == 200
    assert_get_search_form(extract_search_form(response.content.decode()))


@override_settings(DEFAULT_UI_NEXT_ENABLED=True)
def test_landing_page_quick_search_submits_get_ui_next():
    # anonymous users get the site_next templates off this setting alone
    # (see util.resolve_template)
    response = Client().get("/")
    assert response.status_code == 200
    assert_get_search_form(extract_search_form(response.content.decode()))


@pytest.mark.parametrize("template_name", STANDALONE_SEARCH_TEMPLATES)
def test_standalone_search_partials_submit_get(template_name):
    html = render_to_string(template_name)
    assert_get_search_form(extract_search_form(html))
