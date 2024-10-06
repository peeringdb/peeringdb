from datetime import datetime, timedelta, timezone

import pytest
from django.core.management import call_command
from django.test import override_settings

from peeringdb_server.models import Sponsorship

FIVE_MONTHS_AGO = datetime.now(tz=timezone.utc) - timedelta(days=150)
TWO_MONTHS_AGO = datetime.now(tz=timezone.utc) - timedelta(days=60)
# max number of seconds we allow between running command and asserting date is
# the same
SECONDS_THRESHOLD = 120


@pytest.mark.django_db
@override_settings(SPONSORSHIPS_EMAIL="localhost")
def test_send_email(outdated_sponsorship):
    NOW = datetime.now(tz=timezone.utc)
    sponsorship = Sponsorship.objects.all()[0]
    call_command("pdb_sponsorship_notify")
    sponsorship.refresh_from_db()
    assert (sponsorship.notify_date - NOW) < timedelta(seconds=SECONDS_THRESHOLD)


@pytest.fixture
def outdated_sponsorship():
    # Has not been notified of expiration
    org = Sponsorship.objects.create(
        start_date=FIVE_MONTHS_AGO,
        end_date=TWO_MONTHS_AGO,
        notify_date=None,
        level=2,
    )
    return org
