"""
Tests for the pdb_delete_addressless_netixlan management command (#2005).
"""

from io import StringIO

import pytest
import reversion
from django.core.management import call_command

from peeringdb_server.models import (
    InternetExchange,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    Network,
    NetworkIXLan,
    Organization,
)


@pytest.fixture
def entities(db):
    org = Organization.objects.create(name="Test Org", status="ok")
    ix = InternetExchange.objects.create(name="Test IX", status="ok", org=org)
    net = Network.objects.create(name="Test Net", asn=2906, status="ok", org=org)
    return {"org": org, "ix": ix, "ixlan": ix.ixlan, "net": net}


def make_netixlan(entities, ipaddr4=None, ipaddr6=None, status="ok"):
    return NetworkIXLan.objects.create(
        network=entities["net"],
        ixlan=entities["ixlan"],
        asn=entities["net"].asn,
        speed=10000,
        ipaddr4=ipaddr4,
        ipaddr6=ipaddr6,
        status=status,
    )


def record_ixf_entry(entities, netixlan, action="add"):
    """
    Attach an IX-F import log entry capturing the netixlan's *current*
    version - mirrors what the importer records when it touches a row.
    Call this while the netixlan holds the state you want the log to remember.
    """
    with reversion.create_revision():
        netixlan.save()
    version = reversion.models.Version.objects.get_for_object(netixlan).first()
    log = IXLanIXFMemberImportLog.objects.create(ixlan=entities["ixlan"])
    IXLanIXFMemberImportLogEntry.objects.create(
        log=log,
        netixlan=netixlan,
        version_after=version,
        action=action,
    )


@pytest.mark.django_db
def test_dry_run_does_not_delete(entities):
    blank = make_netixlan(entities)
    record_ixf_entry(entities, blank)
    out = StringIO()

    call_command("pdb_delete_addressless_netixlan", stdout=out)

    blank.refresh_from_db()
    assert blank.status == "ok"
    assert "[pretend]" in out.getvalue()
    assert "1 IX-F netixlan(s) deleted" in out.getvalue()


@pytest.mark.django_db
def test_commit_soft_deletes_ixf_created_blank(entities):
    blank = make_netixlan(entities)
    record_ixf_entry(entities, blank)
    out = StringIO()

    call_command("pdb_delete_addressless_netixlan", "--commit", stdout=out)

    blank.refresh_from_db()
    assert blank.status == "deleted"
    assert "1 IX-F netixlan(s) deleted" in out.getvalue()


@pytest.mark.django_db
def test_skips_blank_without_ixf_provenance(entities):
    # address-less but never touched by the importer (e.g. an admin blank) -
    # must be reported and left alone
    blank = make_netixlan(entities)
    out = StringIO()

    call_command("pdb_delete_addressless_netixlan", "--commit", stdout=out)

    blank.refresh_from_db()
    assert blank.status == "ok"
    assert "SKIP (not an IX-F blank-add" in out.getvalue()
    assert "0 IX-F netixlan(s) deleted, 1 address-less netixlan(s) skipped" in (
        out.getvalue()
    )


@pytest.mark.django_db
def test_skips_blank_that_once_had_an_address(entities):
    # importer added this row WITH an address; it was blanked later (e.g. by an
    # admin, #644). The "add" entry's version had an ip, so this is not a
    # #2005 artifact and must be skipped.
    netixlan = make_netixlan(entities, ipaddr4="195.69.147.250")
    record_ixf_entry(entities, netixlan, action="add")

    netixlan.ipaddr4 = None
    netixlan.save()

    out = StringIO()
    call_command("pdb_delete_addressless_netixlan", "--commit", stdout=out)

    netixlan.refresh_from_db()
    assert netixlan.status == "ok"
    assert "0 IX-F netixlan(s) deleted, 1 address-less netixlan(s) skipped" in (
        out.getvalue()
    )


@pytest.mark.django_db
def test_skips_blank_only_modified_by_importer(entities):
    # importer only ever modified this row (no "add" entry); a current blank
    # state is not attributable to a #2005 blank-add - skip it
    blank = make_netixlan(entities)
    record_ixf_entry(entities, blank, action="modify")
    out = StringIO()

    call_command("pdb_delete_addressless_netixlan", "--commit", stdout=out)

    blank.refresh_from_db()
    assert blank.status == "ok"
    assert "0 IX-F netixlan(s) deleted" in out.getvalue()


@pytest.mark.django_db
def test_leaves_netixlans_with_an_address_alone(entities):
    with_v4 = make_netixlan(entities, ipaddr4="195.69.147.250")
    record_ixf_entry(entities, with_v4)
    out = StringIO()

    call_command("pdb_delete_addressless_netixlan", "--commit", stdout=out)

    with_v4.refresh_from_db()
    assert with_v4.status == "ok"
    assert "0 IX-F netixlan(s) deleted" in out.getvalue()


@pytest.mark.django_db
def test_ignores_already_deleted_netixlan(entities):
    already = make_netixlan(entities, status="deleted")
    record_ixf_entry(entities, already)
    out = StringIO()

    call_command("pdb_delete_addressless_netixlan", "--commit", stdout=out)

    already.refresh_from_db()
    assert already.status == "deleted"
    assert "0 IX-F netixlan(s) deleted" in out.getvalue()
