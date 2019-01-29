from __future__ import absolute_import, division, print_function

import datetime
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
import reversion
from reversion.models import Version, Revision

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
        parser.add_argument("--format", action="store", default="text",
                            help="output format to use")

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
        date = dt.replace(tzinfo=None).strftime("%Y-%m-%d")
        stats = {"users": 0}

        for tag in self.tags:
            model = REFTAG_MAP[tag]
            stats[tag] = 0
            for obj in model.objects.filter(created__lte=dt):
                if self.status_at_date(obj, dt) == "ok":
                    stats[tag] += 1

        for user in get_user_model().objects.filter(created__lte=dt):
            if user.is_verified:
                stats["users"] += 1

        codec = options.get("format")
        if codec == "text":
            print(date)
            print("-------------")
            for each in stats.keys():
                print("{}: {}".format(each, stats[each]))

        elif codec == "json":
            print(json.dumps({date: stats}))

        else:
            raise Exception("unknown format {}".format(codec))
