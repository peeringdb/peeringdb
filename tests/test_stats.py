import io
import datetime
import pytest

from .util import ClientCase, Group, override_group_id

from django.core.management import call_command
from django.conf import settings
from django.contrib.auth import get_user_model

from peeringdb_server.models import REFTAG_MAP, UTC, Network
from peeringdb_server.stats import stats


DATE_PAST = datetime.datetime(year=2019, month=11, day=1)


def setup_data():

    call_command("pdb_generate_test_data", limit=3, commit=True)

    date_past = DATE_PAST.replace(tzinfo=UTC())

    # one object of each type moved to the past

    for tag in ["fac", "net", "org", "ix"]:
        for obj in REFTAG_MAP[tag].objects.all():
            obj.created = obj.updated = date_past
            obj.save()
            break

    # create users

    User = get_user_model()

    for i in range(1, 7):
        User.objects.create_user(f"user_{i}", f"user_{i}@localhost", "secret")

    # move users 4, 5, 6 to the past

    User.objects.filter(username__in=["user_4", "user_5", "user_6"]).update(
        created=date_past
    )

    # verify all users except 1 and 4

    user_group, _ = Group.objects.get_or_create(name="user")
    guest_group, _ = Group.objects.get_or_create(name="guest")

    settings.USER_GROUP_ID = user_group.id
    settings.GUEST_GROUP_ID = guest_group.id

    with override_group_id():
        for user in User.objects.exclude(username__in=["user_1", "user_4"]):
            user.set_verified()


@pytest.mark.django_db
def test_generate_for_past_date(db, data_stats_past):
    output = io.StringIO()
    setup_data()
    call_command("pdb_stats", date=DATE_PAST.strftime("%Y%m%d"), stdout=output)
    assert output.getvalue() == data_stats_past.txt


@pytest.mark.django_db
def test_generate_for_current_date(db, data_stats_current):
    output = io.StringIO()
    setup_data()
    call_command("pdb_stats", stdout=output)

    for user in get_user_model().objects.all():
        print(user.username)

    assert data_stats_current.txt in output.getvalue()


@pytest.mark.django_db
def test_global_stats(db, data_stats_global):
    setup_data()

    # test_automated_network_count shows that "automated networks" counts
    # networks w allow_ixp_update=True
    if data_stats_global.name == "test_automated_network_count":
        network = Network.objects.first()
        network.allow_ixp_update = False
        network.save()

    global_stats = stats()
    assert global_stats == data_stats_global.expected
