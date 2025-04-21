import random
import string
from datetime import datetime, timedelta, timezone

import pytest
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import override_settings

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    Organization,
    User,
    VerificationQueueItem,
)

NUM_YEAR_OLD_USERS = 20
NUM_MONTH_OLD_USERS = 15
NUM_DAY_OLD_USERS = 10

NUM_YEAR_OLD_IX = 10
NUM_MONTH_OLD_IX = 8
NUM_DAY_OLD_IX = 5

NUM_YEAR_OLD_FAC = 12
NUM_MONTH_OLD_FAC = 9
NUM_DAY_OLD_FAC = 6


@pytest.mark.django_db
def test_cleanup_users(year_old_users, month_old_users, day_old_users):
    vqi_count = VerificationQueueItem.objects.count()
    users_count = User.objects.count()
    call_command("pdb_cleanup_vq", "users", commit=True)

    # Assert we deleted VQI instances
    assert VerificationQueueItem.objects.count() == vqi_count - NUM_YEAR_OLD_USERS
    # Assert users themselves are not deleted
    assert User.objects.count() == users_count


# Try test with maximum age of vqi to be 14 days
@pytest.mark.django_db
@override_settings(VQUEUE_USER_MAX_AGE=14)
def test_cleanup_users_override_settings(
    year_old_users, month_old_users, day_old_users
):
    vqi_count = VerificationQueueItem.objects.count()
    users_count = User.objects.count()

    call_command("pdb_cleanup_vq", "users", commit=True)
    # Assert we deleted more VQI instances
    assert VerificationQueueItem.objects.count() == vqi_count - (
        NUM_YEAR_OLD_USERS + NUM_MONTH_OLD_USERS
    )
    # Assert users themselves are not deleted
    assert User.objects.count() == users_count


@pytest.mark.django_db
def test_cleanup_users_no_commit(year_old_users, month_old_users, day_old_users):
    vqi_count = VerificationQueueItem.objects.count()
    users_count = User.objects.count()

    call_command("pdb_cleanup_vq", "users", commit=False)
    # Assert we didn't delete VQI instances
    assert VerificationQueueItem.objects.count() == vqi_count
    # Assert users themselves are not deleted
    assert User.objects.count() == users_count


@pytest.mark.django_db
def test_cleanup_users_no_users(year_old_users, month_old_users, day_old_users):
    vqi_count = VerificationQueueItem.objects.count()
    users_count = User.objects.count()

    call_command("pdb_cleanup_vq", commit=True)
    # Assert we didn't delete VQI instances
    assert VerificationQueueItem.objects.count() == vqi_count
    # Assert users themselves are not deleted
    assert User.objects.count() == users_count


@pytest.mark.django_db
def test_cleanup_ix(year_old_ix, month_old_ix, day_old_ix):
    vqi_count = VerificationQueueItem.objects.count()
    ix_count = InternetExchange.objects.count()

    call_command("pdb_cleanup_vq", "ix", commit=True)

    assert VerificationQueueItem.objects.count() == vqi_count - NUM_YEAR_OLD_IX

    assert InternetExchange.objects.count() == ix_count


@pytest.mark.django_db
@override_settings(VQUEUE_IX_MAX_AGE=14)
def test_cleanup_ix_override_settings(year_old_ix, month_old_ix, day_old_ix):
    vqi_count = VerificationQueueItem.objects.count()
    ix_count = InternetExchange.objects.count()

    call_command("pdb_cleanup_vq", "ix", commit=True)

    assert VerificationQueueItem.objects.count() == vqi_count - (
        NUM_YEAR_OLD_IX + NUM_MONTH_OLD_IX
    )
    assert InternetExchange.objects.count() == ix_count


@pytest.mark.django_db
def test_cleanup_ix_no_commit(year_old_ix, month_old_ix, day_old_ix):
    vqi_count = VerificationQueueItem.objects.count()
    ix_count = InternetExchange.objects.count()

    call_command("pdb_cleanup_vq", "ix", commit=False)

    assert VerificationQueueItem.objects.count() == vqi_count
    assert InternetExchange.objects.count() == ix_count


@pytest.mark.django_db
def test_cleanup_fac(year_old_fac, month_old_fac, day_old_fac):
    vqi_count = VerificationQueueItem.objects.count()
    fac_count = Facility.objects.count()

    call_command("pdb_cleanup_vq", "fac", commit=True)

    assert VerificationQueueItem.objects.count() == vqi_count - NUM_YEAR_OLD_FAC
    assert Facility.objects.count() == fac_count


@pytest.mark.django_db
@override_settings(VQUEUE_FAC_MAX_AGE=14)
def test_cleanup_fac_override_settings(year_old_fac, month_old_fac, day_old_fac):
    vqi_count = VerificationQueueItem.objects.count()
    fac_count = Facility.objects.count()

    call_command("pdb_cleanup_vq", "fac", commit=True)

    assert VerificationQueueItem.objects.count() == vqi_count - (
        NUM_YEAR_OLD_FAC + NUM_MONTH_OLD_FAC
    )
    assert Facility.objects.count() == fac_count


@pytest.mark.django_db
def test_cleanup_fac_no_commit(year_old_fac, month_old_fac, day_old_fac):
    vqi_count = VerificationQueueItem.objects.count()
    fac_count = Facility.objects.count()

    call_command("pdb_cleanup_vq", "fac", commit=False)

    assert VerificationQueueItem.objects.count() == vqi_count
    assert Facility.objects.count() == fac_count


# --------- FIXTURES AND HELPERS -----------------


def create_users_and_vqi(users_to_generate, days_old):
    """
    Input: Number users to generate [int]
           Days old to make their VerificationQueueItem [int]
    Output: List of tuples, [(user, verification queue item), ...]
    """

    def random_str():
        return "".join(random.choice(string.ascii_letters) for i in range(4))

    def admin_user():
        user, _ = User.objects.get_or_create(username="admin")
        return user

    admin_user = admin_user()

    output = []
    created_date = datetime.now(timezone.utc) - timedelta(days=days_old)

    for i in range(users_to_generate):
        user = User.objects.create(
            username=f"User {random_str()}",
        )
        vqi = VerificationQueueItem.objects.create(
            content_type=ContentType.objects.get_for_model(User),
            object_id=user.id,
            user=admin_user,
        )
        vqi.created = created_date
        vqi.save()
        output.append((user, vqi))

    return output


@pytest.fixture()
def test_org():
    org = Organization.objects.create(name="Test Organization", status="ok")
    return org


def create_ix_and_vqi(ix_to_generate, days_old, org=None):
    """
    Input: Number of IXes to generate [int]
           Days old to make their VerificationQueueItem [int]
           Organization to associate with IXes
    Output: List of tuples, [(ix, verification queue item), ...]
    """

    def random_str():
        return "".join(random.choice(string.ascii_letters) for i in range(4))

    def admin_user():
        user, _ = User.objects.get_or_create(username="admin")
        return user

    if not org:
        org = Organization.objects.create(name=f"IX Org {random_str()}", status="ok")

    admin_user = admin_user()
    output = []
    created_date = datetime.now(timezone.utc) - timedelta(days=days_old)

    for i in range(ix_to_generate):
        ix = InternetExchange.objects.create(
            name=f"IX {random_str()}",
            org=org,
            status="ok",  # Add status for good measure
        )

        vqi = VerificationQueueItem.objects.create(
            content_type=ContentType.objects.get_for_model(InternetExchange),
            object_id=ix.id,
            user=admin_user,
        )
        vqi.created = created_date
        vqi.save()
        output.append((ix, vqi))

    return output


def create_fac_and_vqi(fac_to_generate, days_old, org=None):
    """
    Input: Number of facilities to generate [int]
           Days old to make their VerificationQueueItem [int]
           Organization to associate with facilities
    Output: List of tuples, [(facility, verification queue item), ...]
    """

    def random_str():
        return "".join(random.choice(string.ascii_letters) for i in range(4))

    def admin_user():
        user, _ = User.objects.get_or_create(username="admin")
        return user

    if not org:
        org = Organization.objects.create(
            name=f"Facility Org {random_str()}", status="ok"
        )

    admin_user = admin_user()
    output = []
    created_date = datetime.now(timezone.utc) - timedelta(days=days_old)

    for i in range(fac_to_generate):
        fac = Facility.objects.create(
            name=f"Facility {random_str()}", org=org, status="ok"
        )

        vqi = VerificationQueueItem.objects.create(
            content_type=ContentType.objects.get_for_model(Facility),
            object_id=fac.id,
            user=admin_user,
        )
        vqi.created = created_date
        vqi.save()
        output.append((fac, vqi))

    return output


@pytest.fixture()
def year_old_users():
    create_users_and_vqi(NUM_YEAR_OLD_USERS, 365)


@pytest.fixture()
def month_old_users():
    create_users_and_vqi(NUM_MONTH_OLD_USERS, 60)


@pytest.fixture()
def day_old_users():
    create_users_and_vqi(NUM_DAY_OLD_USERS, 1)


@pytest.fixture()
def year_old_ix(test_org):
    return create_ix_and_vqi(NUM_YEAR_OLD_IX, 365, test_org)


@pytest.fixture()
def month_old_ix(test_org):
    return create_ix_and_vqi(NUM_MONTH_OLD_IX, 60, test_org)


@pytest.fixture()
def day_old_ix(test_org):
    return create_ix_and_vqi(NUM_DAY_OLD_IX, 1, test_org)


@pytest.fixture()
def year_old_fac(test_org):
    return create_fac_and_vqi(NUM_YEAR_OLD_FAC, 365, test_org)


@pytest.fixture()
def month_old_fac(test_org):
    return create_fac_and_vqi(NUM_MONTH_OLD_FAC, 60, test_org)


@pytest.fixture()
def day_old_fac(test_org):
    return create_fac_and_vqi(NUM_DAY_OLD_FAC, 1, test_org)
