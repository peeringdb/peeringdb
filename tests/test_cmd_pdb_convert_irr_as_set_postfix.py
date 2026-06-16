"""
Tests for pdb_convert_irr_as_set_postfix management command.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from peeringdb_server.management.commands.pdb_convert_irr_as_set_postfix import (
    convert_irr_as_set,
)
from peeringdb_server.models import Network, Organization


@pytest.mark.parametrize(
    "value,expected",
    [
        # single postfix token
        ("AS-FOO@RIPE", "RIPE::AS-FOO"),
        # lowercase input is normalized
        ("as-foo@ripe", "RIPE::AS-FOO"),
        # plain AS number postfix
        ("AS12345@RIPE", "RIPE::AS12345"),
        # multiple postfix tokens
        ("AS-FOO@RIPE AS-BAR@RADB", "RIPE::AS-FOO RADB::AS-BAR"),
        # mixed: one postfix, one already prefix
        ("RIPE::AS-FOO AS-BAR@RADB", "RIPE::AS-FOO RADB::AS-BAR"),
        # all prefix - no change
        ("RIPE::AS-FOO RADB::AS-BAR", "RIPE::AS-FOO RADB::AS-BAR"),
        # no source - no change
        ("AS-FOO", "AS-FOO"),
        # hierarchical prefix - no change
        ("RIPE::AS12345:AS-FOO", "RIPE::AS12345:AS-FOO"),
        # hierarchical postfix (set name contains colon)
        ("AS12345:AS-FOO@RIPE", "RIPE::AS12345:AS-FOO"),
        # comma-separated (non-validator save path)
        ("AS-FOO@RIPE,AS-BAR@RADB", "RIPE::AS-FOO RADB::AS-BAR"),
        # comma + space separated
        ("AS-FOO@RIPE, AS-BAR@RADB", "RIPE::AS-FOO RADB::AS-BAR"),
    ],
)
@pytest.mark.django_db
def test_convert_irr_as_set(value, expected):
    # django_db mark is required even though this test is a pure function call:
    # tests/conftest.py has an autouse `cleanup` fixture that clears all caches,
    # and the `geo` cache is a DatabaseCache backend (see settings/__init__.py),
    # so cache clearing hits the DB.
    assert convert_irr_as_set(value) == expected


# --- Integration tests for the management command ---


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org", status="ok")


def make_network(org, asn, irr_as_set, status="ok"):
    return Network.objects.create(
        name=f"Network {asn}",
        asn=asn,
        irr_as_set=irr_as_set,
        status=status,
        org=org,
    )


@pytest.mark.django_db
def test_dry_run_does_not_modify(org):
    net = make_network(org, 1001, "AS-FOO@RIPE")
    out = StringIO()

    call_command("pdb_convert_irr_as_set_postfix", stdout=out)

    net.refresh_from_db()
    assert net.irr_as_set == "AS-FOO@RIPE"
    assert "[pretend]" in out.getvalue()
    assert "1 network(s) converted" in out.getvalue()


@pytest.mark.django_db
def test_commit_converts_single_postfix(org):
    net = make_network(org, 1002, "AS-FOO@RIPE")
    out = StringIO()

    call_command("pdb_convert_irr_as_set_postfix", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO"
    assert "1 network(s) converted" in out.getvalue()


@pytest.mark.django_db
def test_commit_converts_multiple_postfix_tokens(org):
    net = make_network(org, 1003, "AS-FOO@RIPE AS-BAR@RADB")
    out = StringIO()

    call_command("pdb_convert_irr_as_set_postfix", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO RADB::AS-BAR"


@pytest.mark.django_db
def test_commit_converts_mixed_format(org):
    net = make_network(org, 1004, "RIPE::AS-FOO AS-BAR@RADB")
    out = StringIO()

    call_command("pdb_convert_irr_as_set_postfix", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO RADB::AS-BAR"


@pytest.mark.django_db
def test_skips_network_already_using_prefix(org):
    net = make_network(org, 1005, "RIPE::AS-FOO")
    out = StringIO()

    call_command("pdb_convert_irr_as_set_postfix", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.irr_as_set == "RIPE::AS-FOO"
    assert "0 network(s) converted" in out.getvalue()


@pytest.mark.django_db
def test_skips_network_with_empty_irr_as_set(org):
    net = make_network(org, 1006, "")
    out = StringIO()

    call_command("pdb_convert_irr_as_set_postfix", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.irr_as_set == ""
    assert "0 network(s) converted" in out.getvalue()


@pytest.mark.django_db
def test_skips_non_ok_networks(org):
    net = make_network(org, 1007, "AS-FOO@RIPE", status="deleted")
    out = StringIO()

    call_command("pdb_convert_irr_as_set_postfix", "--commit", stdout=out)

    net.refresh_from_db()
    assert net.irr_as_set == "AS-FOO@RIPE"
    assert "0 network(s) converted" in out.getvalue()


@pytest.mark.django_db
def test_commit_converts_multiple_networks(org):
    net1 = make_network(org, 1008, "AS-FOO@RIPE")
    net2 = make_network(org, 1009, "AS-BAR@RADB")
    net3 = make_network(org, 1010, "ARIN::AS-BAZ")
    out = StringIO()

    call_command("pdb_convert_irr_as_set_postfix", "--commit", stdout=out)

    net1.refresh_from_db()
    net2.refresh_from_db()
    net3.refresh_from_db()
    assert net1.irr_as_set == "RIPE::AS-FOO"
    assert net2.irr_as_set == "RADB::AS-BAR"
    assert net3.irr_as_set == "ARIN::AS-BAZ"
    assert "2 network(s) converted" in out.getvalue()
