"""
The About page lives on the docs site; www links and the old /about route
point there (#2004).
"""

import pytest
from django.test import Client, override_settings

pytestmark = pytest.mark.django_db

DOCS_ABOUT_URL = "https://docs.peeringdb.com/#about-peeringdb"


def assert_about_links(html, count):
    assert 'href="/about"' not in html
    assert html.count(f'href="{DOCS_ABOUT_URL}"') == count


def test_about_links_point_to_docs():
    # footer and the index "learn more" line
    response = Client().get("/")
    assert response.status_code == 200
    assert_about_links(response.content.decode(), 2)


@override_settings(DEFAULT_UI_NEXT_ENABLED=True)
def test_about_links_point_to_docs_ui_next():
    # header dropdown, expanded header nav, footer and the index "learn more" line
    response = Client().get("/")
    assert response.status_code == 200
    assert_about_links(response.content.decode(), 4)


def test_about_route_redirects_to_docs():
    response = Client().get("/about")
    assert response.status_code == 301
    assert response["Location"] == DOCS_ABOUT_URL
