import StringIO
import datetime
import pytest

from util import ClientCase, Group

from django.core.management import call_command
from django.conf import settings
from django.contrib.auth import get_user_model

from peeringdb_server.models import REFTAG_MAP, UTC


DATE_PAST = datetime.datetime(year=2019,month=11,day=1)

def setup_data():

    call_command("pdb_generate_test_data", limit=3, commit=True)

    date_past = DATE_PAST.replace(tzinfo=UTC())

    # one object of each type moved to the past

    for tag in ["fac","net","org","ix"]:
        for obj in REFTAG_MAP[tag].objects.all():
            obj.created = obj.updated = date_past
            obj.save()
            break

    # create users

    User = get_user_model()

    for i in range(1,7):
        User.objects.create_user("user_{}".format(i),
                                 "user_{}@localhost".format(i),
                                 "secret")

    # move users 4, 5, 6 to the past

    User.objects.filter(pk__in=[4,5,6]).update(created=date_past)

    # verify all users except 1 and 4

    for user in User.objects.exclude(pk__in=[1,4]):
        user.set_verified()


@pytest.mark.djangodb
def test_generate_for_past_date(db, data_stats_past):
    output = StringIO.StringIO()
    setup_data()
    call_command("pdb_stats", date=DATE_PAST.strftime("%Y%m%d"), stdout=output)
    assert output.getvalue() == data_stats_past.txt


@pytest.mark.djangodb
def test_generate_for_current_date(db, data_stats_current):
    output = StringIO.StringIO()
    setup_data()
    call_command("pdb_stats", stdout=output)
    assert output.getvalue().find(data_stats_current.txt) > -1


