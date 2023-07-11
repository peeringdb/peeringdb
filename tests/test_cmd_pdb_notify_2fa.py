from datetime import datetime, timedelta, timezone

import pytest
from django.core.management import call_command
from django_otp.plugins.otp_totp.models import TOTPDevice

from peeringdb_server.models import Organization, User


@pytest.fixture
def setup_data():
    users = [
        "org_admin",
        "user_a",
        "user_b",
        "user_c",
        "user_d",
        "user_e",
        "user_f",
    ]
    # create test users
    for name in users:
        setattr(
            setup_data,
            name,
            User.objects.create_user(name, "%s@localhost" % name, name),
        )
        getattr(setup_data, name).set_password(name)

    # create test org
    setup_data.org_required_2fa_a = Organization.objects.create(
        name="Test org 2FA A", status="ok", require_2fa=True
    )
    setup_data.org_required_2fa_b = Organization.objects.create(
        name="Test org 2FA B", status="ok", require_2fa=True
    )
    setup_data.org_disabled_2fa = Organization.objects.create(
        name="Test org no 2FA", status="ok"
    )

    # add org_admin user to org as admin
    setup_data.org_required_2fa_a.admin_usergroup.user_set.add(setup_data.org_admin)

    # distribute group members
    for user_index, user in enumerate(users):
        if user_index in [1, 2]:
            setup_data.org_required_2fa_a.usergroup.user_set.add(
                getattr(setup_data, user)
            )
        elif user_index in [3, 4]:
            setup_data.org_required_2fa_b.usergroup.user_set.add(
                getattr(setup_data, user)
            )
            TOTPDevice.objects.create(user=getattr(setup_data, user), name="default")
        elif user_index in [5, 6]:
            setup_data.org_disabled_2fa.usergroup.user_set.add(
                getattr(setup_data, user)
            )

    yield setup_data


@pytest.mark.django_db
def test_send_email(setup_data):
    # Access the variables defined in setUpTestData
    org_required_2fa_a = setup_data.org_required_2fa_a
    org_required_2fa_b = setup_data.org_required_2fa_b
    org_disabled_2fa = setup_data.org_disabled_2fa
    MONTHS_AGO = datetime.now(tz=timezone.utc) - timedelta(days=30)
    assert (
        org_required_2fa_a.last_notified is None
        and org_required_2fa_b.last_notified is None
        and org_disabled_2fa.last_notified is None
    )

    # run pdb_notify_2fa command with
    call_command("pdb_notify_2fa", "--commit")
    org_required_2fa_a.refresh_from_db()
    org_required_2fa_b.refresh_from_db()
    org_disabled_2fa.refresh_from_db()

    # check if last_notified is updated only for org that require 2FA has member with 2FA disabled
    assert org_required_2fa_a.last_notified is not None
    assert org_required_2fa_b.last_notified is None
    assert org_disabled_2fa.last_notified is None
    last_notified = org_required_2fa_a.last_notified

    # check if last_notified is not updated if current last_notified is less than a month
    call_command("pdb_notify_2fa", "--commit")
    org_required_2fa_a.refresh_from_db()
    assert org_required_2fa_a.last_notified == last_notified

    # set the last_notified as a month has been passed
    org_required_2fa_a.last_notified = MONTHS_AGO
    org_required_2fa_a.save()

    # check if last_notified is updated if current last_notified is more than a month
    call_command("pdb_notify_2fa", "--commit")
    org_required_2fa_a.refresh_from_db()
    assert org_required_2fa_a.last_notified != last_notified
