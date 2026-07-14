"""
Tests for pdb_normalize_name_whitespace management command (#1984).
"""

from io import StringIO

import pytest
from django.core.management import call_command

from peeringdb_server.management.commands.pdb_normalize_name_whitespace import (
    normalize_name,
)
from peeringdb_server.models import Network, Organization


@pytest.mark.parametrize(
    "value,expected",
    [
        # interior runs collapse to a single space
        ("Foo  Bar", "Foo Bar"),
        ("Foo   Bar", "Foo Bar"),
        ("Foo \t Bar", "Foo Bar"),
        ("Foo\t\tBar", "Foo Bar"),
        # leading/trailing (incl. runs) are stripped
        ("Webair Internet Development ", "Webair Internet Development"),
        ("  Foo  ", "Foo"),
        # single interior separator left untouched (not a duplicate risk)
        ("Foo Bar", "Foo Bar"),
        ("Foo\tBar", "Foo\tBar"),
        # empty / null pass through
        ("", ""),
        (None, None),
    ],
)
@pytest.mark.django_db
def test_normalize_name(value, expected):
    # django_db required: the autouse cleanup fixture clears the geo
    # DatabaseCache, which hits the DB (see test_cmd_pdb_convert_irr_as_set_postfix)
    assert normalize_name(value) == expected


# --- Integration tests for the management command ---


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org", status="ok")


def make_network(org, asn, name, status="ok"):
    return Network.objects.create(name=name, asn=asn, status=status, org=org)


@pytest.mark.django_db
def test_dry_run_does_not_modify(org):
    # interior double space survives create (mixin strips ends only)
    net = make_network(org, 1001, "Foo  Bar")
    out = StringIO()

    call_command("pdb_normalize_name_whitespace", stdout=out)

    net.refresh_from_db()
    assert net.name == "Foo  Bar"
    assert "[pretend]" in out.getvalue()
    assert "1 object(s) normalized" in out.getvalue()


@pytest.mark.django_db
def test_commit_collapses_interior_whitespace(org):
    net = make_network(org, 1002, "36media  GmbH")
    out = StringIO()

    call_command("pdb_normalize_name_whitespace", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.name == "36media GmbH"
    assert "1 object(s) normalized" in out.getvalue()
    assert "'36media  GmbH' -> '36media GmbH'" in out.getvalue()


@pytest.mark.django_db
def test_commit_normalizes_organization(org):
    dirty = Organization.objects.create(name="Acme  Holdings", status="ok")
    out = StringIO()

    call_command("pdb_normalize_name_whitespace", "--commit", stdout=out)

    dirty.refresh_from_db()
    assert dirty.name == "Acme Holdings"


@pytest.mark.django_db
def test_collision_is_skipped_not_applied(org):
    # a clean name and a whitespace variant that would collapse onto it: the
    # variant must be left alone (unique=True -> collapsing would 500) and
    # reported as a conflict for manual merge
    clean = make_network(org, 1003, "OpenLab Network")
    variant = make_network(org, 1004, "OpenLab  Network")
    out = StringIO()

    call_command("pdb_normalize_name_whitespace", "--commit", stdout=out)

    clean.refresh_from_db()
    variant.refresh_from_db()
    assert clean.name == "OpenLab Network"
    assert variant.name == "OpenLab  Network"  # untouched
    assert "CONFLICT" in out.getvalue()
    assert "1 conflict(s) skipped" in out.getvalue()
    assert "0 object(s) normalized" in out.getvalue()


@pytest.mark.django_db
def test_collision_with_deleted_row_is_skipped(org):
    # the name UNIQUE index spans deleted rows too (soft-delete never renames),
    # so a normalize that would collapse onto a DELETED row's name must be
    # skipped, not raise IntegrityError and abort the whole run
    make_network(org, 1007, "OpenLab Network", status="deleted")
    variant = make_network(org, 1008, "OpenLab  Network")
    out = StringIO()

    call_command("pdb_normalize_name_whitespace", "--commit", stdout=out)

    variant.refresh_from_db()
    assert variant.name == "OpenLab  Network"  # untouched, no IntegrityError
    assert "CONFLICT" in out.getvalue()
    assert "1 conflict(s) skipped" in out.getvalue()
    assert "0 object(s) normalized" in out.getvalue()


@pytest.mark.django_db
def test_skips_deleted_rows(org):
    net = make_network(org, 1005, "Foo  Bar", status="deleted")
    out = StringIO()

    call_command("pdb_normalize_name_whitespace", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.name == "Foo  Bar"
    assert "0 object(s) normalized" in out.getvalue()


@pytest.mark.django_db
def test_clean_names_untouched(org):
    net = make_network(org, 1006, "Perfectly Fine Name")
    out = StringIO()

    call_command("pdb_normalize_name_whitespace", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.name == "Perfectly Fine Name"
    assert "0 object(s) normalized" in out.getvalue()
