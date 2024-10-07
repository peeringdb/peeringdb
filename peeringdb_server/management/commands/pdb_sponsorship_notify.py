"""
Look for expired sponsorships and sends a notification to sponsorship admin for recently expired sponsorships.
"""

import datetime

from django.core.management.base import BaseCommand

from peeringdb_server.models import Sponsorship


class Command(BaseCommand):
    help = "Looks for expired sponsorships and sends a notification to sponsorship admin for recently expired sponsorships"

    def log(self, msg):
        print(msg)

    def handle(self, *args, **options):
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        for sponsorship in Sponsorship.objects.filter(end_date__lt=now):
            if (
                sponsorship.notify_date is None
                or sponsorship.notify_date < sponsorship.end_date
            ):
                sponsorship.notify_expiration()
                # if b:
                #    self.log("Sent expiration notices for %s, expired on %s" % (sponsorship.org.name, sponsorship.end_date))
