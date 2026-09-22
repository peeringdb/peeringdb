"""
Every `data-edit-data` id used by a template must be assigned to a loader.

`twentyc.data.loaders.loader()` throws when an id has no assignment:

    throw("Could not find suitable loader for data id "+id+
          ", are you certain it's assigned?")

The throw escapes the select widget's `set()`, which aborts widget
initialisation for the rest of the list -- the visible symptom is the first
row of a table getting real inputs while every later row is left showing
edit-mode labels with no controls, and Cancel no longer working. Nothing in
the Python test suite exercises the JS, so this static check stands in for it.
"""

import re
from pathlib import Path

import pytest

# even though nothing here touches the database, the autouse cleanup
# fixture clears the geo DatabaseCache, which does
pytestmark = pytest.mark.django_db

# resolve from the installed package: the repo has src/peeringdb_server while
# the container mounts it as peeringdb_server, so a path relative to tests/
# only works in one of the two
import peeringdb_server

APP = Path(peeringdb_server.__file__).parent
STATIC = APP / "static"
TEMPLATES = APP / "templates"

# the two entry-point bundles are kept in lockstep
BUNDLES = ("peeringdb.js", "peeringdb_ui_next.js")

EDIT_DATA_RE = re.compile(r'data-edit-data="([^"{}]+)"')
ASSIGN_RE = re.compile(r'twentyc\.data\.loaders\.assign\(\s*"([^"]+)"')


def template_data_ids():
    ids = set()
    for path in TEMPLATES.rglob("*.html"):
        ids.update(EDIT_DATA_RE.findall(path.read_text()))
    return ids


def assigned_data_ids(bundle):
    return set(ASSIGN_RE.findall((STATIC / bundle).read_text()))


def template_assigned_data_ids():
    # some ids are assigned inline by the page that uses them, against a
    # page-specific loader (e.g. `permissions` -> `org_admin` in
    # view_organization_tools.html) rather than globally in a bundle
    ids = set()
    for path in TEMPLATES.rglob("*.html"):
        ids.update(ASSIGN_RE.findall(path.read_text()))
    return ids


def test_every_template_data_id_has_a_loader():
    """
    Every id is assigned somewhere -- in a bundle, or inline by a page.

    This does not verify that a page-scoped assignment is reachable from the
    page that uses the id; it catches the case that actually broke the
    netixlan table, which was an id assigned nowhere at all.
    """
    used = template_data_ids()
    # sanity: the scan finds something, so a broken regex cannot pass vacuously
    assert "enum/policy_general" in used
    assert "enum/meta_planned_status_change" in used

    inline = template_assigned_data_ids()
    for bundle in BUNDLES:
        missing = sorted(used - assigned_data_ids(bundle) - inline)
        assert not missing, f"{bundle} is missing loader assignments for: {missing}"


def test_bundles_assign_the_same_data_ids():
    # a data id assigned in only one bundle breaks that half of the site
    first, second = (assigned_data_ids(b) for b in BUNDLES)
    assert not first ^ second, (
        "loader assignments differ between the bundles: "
        f"only in {BUNDLES[0]}: {sorted(first - second)}, "
        f"only in {BUNDLES[1]}: {sorted(second - first)}"
    )
