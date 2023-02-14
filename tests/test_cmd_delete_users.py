import io
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from peeringdb_server.models import Organization, User

from .util import reset_group_ids


def setup_users():
    reset_group_ids()

    user_a = User.objects.create_user(
        username="user_a", password="user_a", email="user_a@localhost"
    )
    user_b = User.objects.create_user(
        username="user_b", password="user_b", email="user_b@localhost"
    )
    user_c = User.objects.create_user(
        username="user_c", password="user_c", email="user_c@localhost"
    )

    org = Organization.objects.create(name="Test", status="ok")

    # user A is verified and member of an org

    org.admin_usergroup.user_set.add(user_a)
    user_a.set_verified()
    assert user_a.status == "ok"

    # user B is verified but not member of an org

    user_b.set_verified()
    assert user_b.status == "ok"

    # user C is not verified and not member of an org

    user_c.set_unverified()
    assert user_c.status == "pending"

    return (user_a, user_b, user_c, org)


def assert_user(user, status, flagged, notified):
    user.refresh_from_db()
    assert user.status == status
    if flagged:
        assert user.flagged_for_deletion is not None
    else:
        assert user.flagged_for_deletion is None

    if notified:
        assert user.notified_for_deletion is not None
    else:
        assert user.notified_for_deletion is None


@override_settings(MIN_AGE_ORPHANED_USER_DAYS=-1)
@pytest.mark.django_db
def test_run_non_committal():
    user_a, user_b, user_c, org = setup_users()

    call_command("pdb_delete_users")

    # no users should have changed

    assert_user(user_a, "ok", False, False)
    assert_user(user_b, "ok", False, False)
    assert_user(user_c, "pending", False, False)


@override_settings(MIN_AGE_ORPHANED_USER_DAYS=-1)
@pytest.mark.django_db
def test_run():
    user_a, user_b, user_c, org = setup_users()

    out = io.StringIO()
    call_command("pdb_delete_users", commit=True, stdout=out)

    assert "Sending 0 emails" in out.getvalue()

    assert_user(user_a, "ok", False, False)
    assert_user(user_b, "ok", True, False)
    assert_user(user_c, "pending", True, False)

    user_b.flagged_for_deletion = user_b.flagged_for_deletion - timedelta(
        days=settings.DELETE_ORPHANED_USER_DAYS - settings.NOTIFY_ORPHANED_USER_DAYS
    )
    user_b.save()

    user_c.flagged_for_deletion = user_c.flagged_for_deletion - timedelta(
        days=settings.DELETE_ORPHANED_USER_DAYS - settings.NOTIFY_ORPHANED_USER_DAYS
    )
    user_c.save()

    out = io.StringIO()
    call_command("pdb_delete_users", commit=True, stdout=out)

    assert "Sending 2 emails" in out.getvalue()

    assert_user(user_a, "ok", False, False)
    assert_user(user_b, "ok", True, True)
    assert_user(user_c, "pending", True, True)

    user_b.flagged_for_deletion = timezone.now() - timedelta(days=1)
    user_b.save()

    user_c.flagged_for_deletion = timezone.now() - timedelta(days=1)
    user_c.save()

    out = io.StringIO()
    call_command("pdb_delete_users", commit=True, stdout=out)
    out = out.getvalue()

    assert "Sending 0 emails" in out

    assert_user(user_a, "ok", False, False)

    assert not User.objects.filter(username="user_c").exists()

    user_b.refresh_from_db()

    assert user_b.is_active is False
    assert user_b.username == f"closed-account-{user_b.id}"


@override_settings(MIN_AGE_ORPHANED_USER_DAYS=-1)
@pytest.mark.django_db
def test_run_unflag():
    user_a, user_b, user_c, org = setup_users()

    out = io.StringIO()
    call_command("pdb_delete_users", commit=True, stdout=out)

    assert "Sending 0 emails" in out.getvalue()

    assert_user(user_a, "ok", False, False)
    assert_user(user_b, "ok", True, False)
    assert_user(user_c, "pending", True, False)

    org.usergroup.user_set.add(user_b)

    call_command("pdb_delete_users", commit=True)

    assert_user(user_a, "ok", False, False)
    assert_user(user_b, "ok", False, False)
    assert_user(user_c, "pending", True, False)


@override_settings(MIN_AGE_ORPHANED_USER_DAYS=-1)
@pytest.mark.django_db
def test_run_max_notifies():
    user_a, user_b, user_c, org = setup_users()

    out = io.StringIO()
    call_command("pdb_delete_users", commit=True, stdout=out)

    assert "Sending 0 emails" in out.getvalue()

    assert_user(user_a, "ok", False, False)
    assert_user(user_b, "ok", True, False)
    assert_user(user_c, "pending", True, False)

    user_b.flagged_for_deletion = user_b.flagged_for_deletion - timedelta(
        days=settings.DELETE_ORPHANED_USER_DAYS - settings.NOTIFY_ORPHANED_USER_DAYS
    )
    user_b.save()

    user_c.flagged_for_deletion = user_c.flagged_for_deletion - timedelta(
        days=settings.DELETE_ORPHANED_USER_DAYS - settings.NOTIFY_ORPHANED_USER_DAYS
    )
    user_c.save()

    out = io.StringIO()
    call_command("pdb_delete_users", commit=True, stdout=out, max_notify=1)

    out = out.getvalue()

    assert "Sending 1 emails" in out

    assert_user(user_a, "ok", False, False)
    assert_user(user_b, "ok", True, True)
    assert_user(user_c, "pending", True, False)
