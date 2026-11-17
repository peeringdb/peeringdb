"""
Tests for pdb_strip_name_emoji management command (#2018).

The test database is utf8mb3, which can't store 4-byte emoji, so these tests
use BMP pictographs (U+2600-27BF); the command treats both the same.
"""

import csv
from io import StringIO
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import override_settings

from peeringdb_server.mail import mail_org_admins_emoji_removed
from peeringdb_server.models import Facility, Network, Organization, User


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org", status="ok")


def make_network(org, asn, name, status="ok", **kwargs):
    return Network.objects.create(name=name, asn=asn, status=status, org=org, **kwargs)


def run(*args):
    out = StringIO()
    call_command("pdb_strip_name_emoji", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_dry_run_does_not_modify(org):
    net = make_network(org, 1001, "Acme ★")

    output = run()

    net.refresh_from_db()
    assert net.name == "Acme ★"
    assert "[pretend] would change net" in output
    assert "1 field(s) changed, 0 skipped" in output


@pytest.mark.django_db
def test_commit_strips_name_aka_and_name_long(org):
    net = make_network(
        org,
        1002,
        "★ Acme Net ★",
        aka="Acme \u2764\ufe0f",  # heart + variation selector
        name_long="Acme Long ☎ Name",
    )

    output = run("--commit")

    net.refresh_from_db()
    assert net.name == "Acme Net"
    assert net.aka == "Acme"
    assert net.name_long == "Acme Long Name"
    assert "3 field(s) changed, 0 skipped" in output


@pytest.mark.django_db
def test_commit_covers_other_entities(org):
    org.name = "Test Org ✈"
    org.save()
    fac = Facility.objects.create(name="Fac ☂", status="ok", org=org)

    run("--commit")

    org.refresh_from_db()
    fac.refresh_from_db()
    assert org.name == "Test Org"
    assert fac.name == "Fac"


@pytest.mark.django_db
def test_collision_is_skipped_and_rest_applied(org):
    # a collision must not halt the run: the other rows are still applied
    clean = make_network(org, 1003, "OpenLab")
    variant = make_network(org, 1004, "OpenLab ★", aka="OpenLab ★")
    other = make_network(org, 1005, "Other ★")

    output = run("--commit")

    clean.refresh_from_db()
    variant.refresh_from_db()
    other.refresh_from_db()
    assert clean.name == "OpenLab"
    assert variant.name == "OpenLab ★"  # untouched
    assert variant.aka == "OpenLab"  # not unique, still applied
    assert other.name == "Other"
    assert f"skipped: collides with net id:{clean.id}" in output
    assert "2 field(s) changed, 1 skipped" in output


@pytest.mark.django_db
def test_collision_with_deleted_row_is_skipped(org):
    # the name UNIQUE index spans deleted rows too
    make_network(org, 1006, "OpenLab", status="deleted")
    variant = make_network(org, 1007, "OpenLab ★")

    output = run("--commit")

    variant.refresh_from_db()
    assert variant.name == "OpenLab ★"
    assert "0 field(s) changed, 1 skipped" in output


@pytest.mark.django_db
@pytest.mark.parametrize("args", [(), ("--commit",)])
def test_collision_within_run_is_skipped(org, args):
    # two rows that strip to the same name: the second is skipped in both
    # modes, so the dry-run report matches what a commit does
    first = make_network(org, 1013, "OpenLab ★")
    second = make_network(org, 1014, "OpenLab ☎")

    output = run(*args)

    assert f"skipped: collides with net id:{first.id} (changed in this run)" in output
    assert "1 field(s) changed, 1 skipped" in output
    second.refresh_from_db()
    assert second.name == "OpenLab ☎"


@pytest.mark.django_db
def test_integrity_error_skips_row_and_continues(org):
    failing = make_network(org, 1015, "Failing ★")
    other = make_network(org, 1016, "Other ★")
    save = Network.save

    def save_or_fail(self, *args, **kwargs):
        if self.id == failing.id:
            raise IntegrityError("duplicate entry")
        return save(self, *args, **kwargs)

    with patch.object(Network, "save", save_or_fail):
        output = run("--commit")

    failing.refresh_from_db()
    other.refresh_from_db()
    assert failing.name == "Failing ★"
    assert other.name == "Other"
    assert "skipped: integrity error" in output
    assert "1 field(s) changed, 1 skipped" in output


@pytest.mark.django_db
def test_integrity_error_releases_claim_and_limit_slot(org):
    # the failed row neither blocks a later row with the same new name nor
    # keeps its org's --limit slot
    failing = make_network(org, 1040, "OpenLab ★")
    other_org = Organization.objects.create(name="Other Org", status="ok")
    other = make_network(other_org, 1041, "OpenLab ☎")
    save = Network.save

    def save_or_fail(self, *args, **kwargs):
        if self.id == failing.id:
            raise IntegrityError("duplicate entry")
        return save(self, *args, **kwargs)

    with patch.object(Network, "save", save_or_fail):
        output = run("--commit", "--limit", "1")

    other.refresh_from_db()
    assert other.name == "OpenLab"
    assert "1 field(s) changed, 1 skipped" in output


@pytest.mark.django_db
@pytest.mark.parametrize("args", [(), ("--commit",)])
def test_parent_status_is_skipped_and_rest_applied(org, args):
    # save() refuses a live fac under a deleted org; that row is skipped in
    # both modes and the rest of the run still applies
    deleted_org = Organization.objects.create(name="Deleted Org", status="ok")
    fac = Facility.objects.create(name="Fac ☂", status="ok", org=deleted_org)
    Organization.objects.filter(id=deleted_org.id).update(status="deleted")
    net = make_network(org, 1042, "Acme ★")

    output = run(*args)

    fac.refresh_from_db()
    net.refresh_from_db()
    assert fac.name == "Fac ☂"
    assert f"skipped: parent status fac id:{fac.id} name" in output
    assert "1 field(s) changed, 1 skipped" in output
    assert net.name == ("Acme" if args else "Acme ★")


@pytest.mark.django_db
def test_negative_limit_rejected():
    with pytest.raises(CommandError, match="--limit"):
        run("--limit", "-1")


@pytest.mark.django_db
def test_name_whitespace_normalized_after_strip(org):
    # no-break spaces around the emoji would otherwise leave a run that
    # validate_name (#1984) rejects; aka keeps its whitespace as is
    net = make_network(org, 1027, "Acme\u00a0★\u00a0Net", aka="Acme\u00a0★\u00a0Net")

    run("--commit")

    net.refresh_from_db()
    assert net.name == "Acme Net"
    assert net.aka == "Acme\u00a0\u00a0Net"


@pytest.mark.django_db
def test_emoji_only_name_is_skipped_but_blankable_field_cleared(org):
    net = make_network(org, 1008, "★★", aka="☎")

    output = run("--commit")

    net.refresh_from_db()
    assert net.name == "★★"  # required field: can't be emptied
    assert net.aka == ""
    assert "skipped: nothing left after removing emoji" in output


@pytest.mark.django_db
def test_skips_deleted_rows(org):
    net = make_network(org, 1009, "Acme ★", status="deleted")

    output = run("--commit")

    net.refresh_from_db()
    assert net.name == "Acme ★"
    assert "0 field(s) changed, 0 skipped" in output


@pytest.mark.django_db
def test_clean_names_untouched(org):
    net = make_network(org, 1010, "Acme™ Café", aka="Zürich")

    output = run("--commit")

    net.refresh_from_db()
    assert net.name == "Acme™ Café"
    assert net.aka == "Zürich"
    assert "0 field(s) changed, 0 skipped" in output


@pytest.mark.django_db
def test_report_csv(org, tmp_path):
    make_network(org, 1011, "OpenLab")
    net = make_network(org, 1012, "OpenLab ★")
    report = tmp_path / "emoji.csv"

    run("--report", str(report))

    with open(report, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows == [
        {
            "ref_tag": "net",
            "id": str(net.id),
            "org_id": str(org.id),
            "field": "name",
            "current": "OpenLab ★",
            "proposed": "OpenLab",
            "result": rows[0]["result"],
        }
    ]
    assert rows[0]["result"].startswith("skipped: collides with net id:")


@pytest.mark.django_db
def test_trademark_signs_follow_setting(org):
    net = make_network(org, 1020, "fibertime™", aka="Acme ★")

    run("--commit")
    net.refresh_from_db()
    assert net.name == "fibertime™"  # off by default
    assert net.aka == "Acme"

    with override_settings(EMOJI_INCLUDE_TRADEMARK_SIGNS=True):
        run("--commit")
    net.refresh_from_db()
    assert net.name == "fibertime"


NOTIFY = "peeringdb_server.management.commands.pdb_strip_name_emoji.mail_org_admins_emoji_removed"


@pytest.mark.django_db
def test_notify_dry_run_sends_nothing(org):
    make_network(org, 1021, "Acme ★")

    with patch(NOTIFY) as notify:
        output = run("--notify")

    notify.assert_not_called()
    assert f"would notify org id:{org.id} admins (0 user(s)) of 1 change(s)" in output


@pytest.mark.django_db
def test_commit_without_notify_sends_nothing(org, django_capture_on_commit_callbacks):
    # notifications are opt-in: --commit alone applies the changes, no mail
    make_network(org, 1028, "Acme ★")

    with patch(NOTIFY) as notify:
        with django_capture_on_commit_callbacks(execute=True):
            output = run("--commit")

    notify.assert_not_called()
    assert "notify" not in output


@pytest.mark.django_db
def test_notify_after_commit_one_mail_per_org(org, django_capture_on_commit_callbacks):
    other_org = Organization.objects.create(name="Other Org", status="ok")
    make_network(org, 1022, "Acme ★", aka="Acme ☎")
    make_network(other_org, 1023, "Other ★")
    # skipped rows go to the AC report, not to the owner
    make_network(org, 1024, "★★")

    with patch(NOTIFY) as notify:
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            run("--commit", "--notify")

    assert len(callbacks) == 1
    sent = {call.args[0].id: call.args[1] for call in notify.call_args_list}
    assert set(sent) == {org.id, other_org.id}
    assert [(c["field"], c["proposed"]) for c in sent[org.id]] == [
        ("Name", "Acme"),
        ("Also Known As", "Acme"),
    ]


@pytest.mark.django_db
def test_notify_failure_does_not_stop_other_orgs(
    org, django_capture_on_commit_callbacks
):
    other_org = Organization.objects.create(name="Other Org", status="ok")
    make_network(org, 1025, "Acme ★")
    make_network(other_org, 1026, "Other ★")

    with patch(NOTIFY, side_effect=[Exception("smtp down"), None]) as notify:
        with django_capture_on_commit_callbacks(execute=True):
            run("--commit", "--notify")

    assert notify.call_count == 2


@pytest.mark.django_db
@override_settings(MAIL_DEBUG=False)
def test_mail_org_admins_emoji_removed(org):
    admin = User.objects.create_user(
        username="emoji_admin", password="x", email="admin@localhost"
    )
    member = User.objects.create_user(
        username="emoji_member", password="x", email="member@localhost"
    )
    org.admin_usergroup.user_set.add(admin)
    org.usergroup.user_set.add(member)
    mail.outbox = []

    mail_org_admins_emoji_removed(
        org,
        [
            {
                "entity_type": "Facility",
                "ref_tag": "fac",
                "id": 7,
                "field": "Name",
                "current": "Acme ★ VEL1 & VEL2",
                "proposed": "Acme VEL1 & VEL2",
            }
        ],
    )

    assert len(mail.outbox) == 1  # admins only
    message = mail.outbox[0]
    assert message.to == ["admin@localhost"]
    assert '"Acme VEL1 & VEL2"' in message.body  # not HTML-escaped
    assert "/fac/7" in message.body


@pytest.mark.django_db
def test_limit_batches_by_organization(org):
    # org is first in the run: its own row and its network change together
    org.name = "Test Org ★"
    org.save()
    own_net = make_network(org, 1030, "Acme ★")
    other_org = Organization.objects.create(name="Other Org ★", status="ok")
    other_net = make_network(other_org, 1031, "Other ★")

    run("--commit", "--limit", "1")

    org.refresh_from_db()
    own_net.refresh_from_db()
    other_org.refresh_from_db()
    other_net.refresh_from_db()
    assert (org.name, own_net.name) == ("Test Org", "Acme")
    assert (other_org.name, other_net.name) == ("Other Org ★", "Other ★")

    # the next run continues with the remaining organization
    run("--commit", "--limit", "1")

    other_org.refresh_from_db()
    other_net.refresh_from_db()
    assert (other_org.name, other_net.name) == ("Other Org", "Other")


@pytest.mark.django_db
def test_limit_skipped_org_does_not_use_a_slot(org):
    # org only has a row that can't be changed (nothing left but emoji)
    make_network(org, 1032, "★★")
    other_org = Organization.objects.create(name="Other Org", status="ok")
    other_net = make_network(other_org, 1033, "Other ★")

    output = run("--commit", "--limit", "1")

    other_net.refresh_from_db()
    assert other_net.name == "Other"
    assert "1 field(s) changed, 1 skipped" in output


@pytest.mark.django_db
def test_limit_bounds_notifications(org, django_capture_on_commit_callbacks):
    other_org = Organization.objects.create(name="Other Org", status="ok")
    make_network(org, 1034, "Acme ★")
    make_network(other_org, 1035, "Other ★")

    with patch(NOTIFY) as notify:
        with django_capture_on_commit_callbacks(execute=True):
            run("--commit", "--notify", "--limit", "1")

    assert notify.call_count == 1
