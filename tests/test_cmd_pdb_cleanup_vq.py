from datetime import datetime, timezone, timedelta
import pytest
import random
import string

from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

from peeringdb_server.models import User, VerificationQueueItem

NUM_YEAR_OLD_USERS = 20
NUM_MONTH_OLD_USERS = 15
NUM_DAY_OLD_USERS = 10


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
def test_cleanup_users_override_settings(year_old_users, month_old_users, day_old_users):
    vqi_count = VerificationQueueItem.objects.count()
    users_count = User.objects.count()

    call_command("pdb_cleanup_vq", "users", commit=True)
    # Assert we deleted more VQI instances
    assert VerificationQueueItem.objects.count() == vqi_count - (NUM_YEAR_OLD_USERS + NUM_MONTH_OLD_USERS)
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

# --------- FIXTURES AND HELPERS -----------------

def create_users_and_vqi(users_to_generate, days_old):
    """
    Input: Number users to generate [int]
           Days old to make their VerificationQueueItem [int]
    Output: List of tuples, [(user, verification queue item), ...]
    """

    def random_str():
        return ''.join(random.choice(string.ascii_letters) for i in range(4))

    def admin_user():
        user, _ = User.objects.get_or_create(username="admin")
        return user

    admin_user = admin_user()

    output = []
    created_date = datetime.now(timezone.utc) - timedelta(days=days_old)

    for i in range(users_to_generate):
        user = User.objects.create(
                username=f'User {random_str()}',
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
def year_old_users():
    create_users_and_vqi(NUM_YEAR_OLD_USERS, 365)

@pytest.fixture()
def month_old_users():
    create_users_and_vqi(NUM_MONTH_OLD_USERS, 60)

@pytest.fixture()
def day_old_users():
    create_users_and_vqi(NUM_DAY_OLD_USERS, 1)

