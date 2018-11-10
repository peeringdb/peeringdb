from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from reversion.models import Version, Revision

import reversion
import datetime

from peeringdb_server.models import REFTAG_MAP, UTC


class Command(BaseCommand):
    """
    Posts stat breakdown for any given date, if not date is supplied
    today will be used
    """

    tags = ["fac", "ix", "net", "org"]

    def add_arguments(self, parser):
        parser.add_argument("--date", action="store", default=None,
                            help="generate stats for this date")

    def status_at_date(self, obj, dt):
        versions = Version.objects.get_for_object(obj)
        version = versions.filter(revision__date_created__lte=dt).order_by(
            "-revision__date_created").first()
        if version:
            return version.field_dict["status"]
        else:
            return obj.status

    def handle(self, *args, **options):
        date = options.get('date', None)
        if date:
            dt = datetime.datetime.strptime(date, "%Y%m%d")
        else:
            dt = datetime.datetime.now()

        dt = dt.replace(hour=23, minute=23, second=59, tzinfo=UTC())

        print("{}".format(dt.replace(tzinfo=None).strftime("%Y-%m-%d")))
        print("-------------")

        stats = {"users": 0}

        for tag in self.tags:
            model = REFTAG_MAP[tag]
            stats[tag] = 0
            for obj in model.objects.filter(created__lte=dt):
                if self.status_at_date(obj, dt) == "ok":
                    stats[tag] += 1

            print "{}: {}".format(tag, stats[tag])

        for user in get_user_model().objects.filter(created__lte=dt):
            if user.is_verified:
                stats["users"] += 1

        print "users: {}".format(stats["users"])
