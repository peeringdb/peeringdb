"""
Tests for how the csrf token reaches ajax requests (#2043).

Two ordering invariants carry the fix, and neither is visible to a test that
only exercises python:

- the header template must publish `PeeringDB.csrf` while the document parses,
  not from a `window.load` handler - the edit ui binds on DOMContentLoaded, and
  a throw in any other load handler stops later ones from running at all
- `$.ajaxSetup` must be registered at module scope rather than from
  `PeeringDB.init()`, which itself only runs on `window.load`

Both have now caused a production csrf outage (fb85d749, then #2043), so they
are pinned here.
"""

import pytest
from django.contrib.staticfiles.finders import find
from django.test import Client, override_settings

pytestmark = pytest.mark.django_db

UI_SCRIPTS = ["peeringdb.js", "peeringdb_ui_next.js"]

# django renders `{{ csrf_token }}` as the 11-char string "NOTPROVIDED" when no
# token is available; django only accepts 32 or 64 (`_check_token_format`)
CSRF_TOKEN_LENGTH = 64


def assert_token_published_before_load(html):
    assignment = html.index("PeeringDB.csrf = '")
    load_handler = html.index('$(window).bind("load"')
    assert assignment < load_handler, (
        "the csrf token is assigned from a window.load handler - it must be "
        "published during parse, or a throw in an earlier load handler leaves "
        "every ajax POST on the page without a token (#2043)"
    )

    start = assignment + len("PeeringDB.csrf = '")
    token = html[start : html.index("'", start)]
    assert len(token) == CSRF_TOKEN_LENGTH, (
        f"rendered csrf token is {len(token)} chars ({token!r}); django rejects "
        "any length other than 32 or 64 as 'incorrect length'"
    )


def test_header_publishes_csrf_token_during_parse():
    response = Client().get("/")
    assert response.status_code == 200
    assert_token_published_before_load(response.content.decode())


@override_settings(DEFAULT_UI_NEXT_ENABLED=True)
def test_header_publishes_csrf_token_during_parse_ui_next():
    # anonymous users get the site_next templates off this setting alone
    # (see util.resolve_template)
    response = Client().get("/")
    assert response.status_code == 200
    assert_token_published_before_load(response.content.decode())


@pytest.mark.parametrize("script_name", UI_SCRIPTS)
def test_ajaxsetup_registered_outside_init(script_name):
    js = open(find(script_name)).read()

    # first statement after the PeeringDB object literal closes, so anything
    # at a later offset is module scope rather than a method body
    module_scope = js.index('$(twentyc.data).on("load-enum/traffic"')
    assert js.index("$.ajaxSetup(") > module_scope, (
        f"{script_name}: $.ajaxSetup is registered inside the PeeringDB object "
        "- it must run at parse time, since init() only runs on window.load "
        "and a throw ahead of it would send every POST with no csrf header "
        "(#2043)"
    )

    # module scope alone is not enough - deferring the call into the load
    # handler below reproduces the same outage while clearing the check above
    assert js.index("$.ajaxSetup(") < js.index('$(window).bind("load"'), (
        f"{script_name}: $.ajaxSetup is registered from a window.load handler "
        "- it must run at parse time, or a throw in an earlier load handler "
        "leaves every POST on the page with no csrf header (#2043)"
    )
