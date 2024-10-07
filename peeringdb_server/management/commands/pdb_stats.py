"""
Post stat breakdown for any given date.
"""

import datetime
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from reversion.models import Version

from peeringdb_server.models import REFTAG_MAP, UTC, Network


class Command(BaseCommand):
    """
    Posts stat breakdown for any given date, if not date is supplied
    today will be used
    """

    tags = [
        "fac",
        "ix",
        "net",
        "org",
        "carrier",
        "campus",
        "netixlan",
        "netfac",
        "automated_nets",
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--date", action="store", default=None, help="generate stats for this date"
        )
        parser.add_argument(
            "--format", action="store", default="text", help="output format to use"
        )

    def status_at_date(self, obj, dt):
        versions = Version.objects.get_for_object(obj)
        version = (
            versions.filter(revision__date_created__lte=dt)
            .order_by("-revision__date_created")
            .first()
        )
        if version:
            return version.field_dict["status"]
        else:
            return obj.status

    def handle(self, *args, **options):
        date = options.get("date", None)
        if date:
            dt = datetime.datetime.strptime(date, "%Y%m%d")
            stats = self.generate_for_past_date(dt)
        else:
            stats = self.generate_for_current_date()

        self.print_stats(stats, output_format=options.get("format"))

    def stats(self, dt):
        """
        Generates and returns a fresh stats dict with user count
        for the specified date

        Argument(s)

        - dt: datetime object

        Return(s)

        `dict`
        """

        stats = {"users": 0}

        for user in get_user_model().objects.filter(created__lte=dt):
            if user.is_verified_user:
                stats["users"] += 1

        return stats

    def print_stats(self, stats, output_format="text"):
        """
        Output generated stats in a userfriendly format

        Argument(s)

        - stats: `dict` generated via `generate_for_current_date`

        Keyword Argument(s)

        - output_format: `str` ("text" or "json")
        """

        dt = stats["dt"]
        stats = stats["stats"]

        date = dt.replace(tzinfo=None).strftime("%Y-%m-%d")
        if output_format == "text":
            self.stdout.write(date)
            self.stdout.write("-------------")
            for each in self.tags + ["users"]:
                self.stdout.write(f"{each}: {stats[each]}")
        elif output_format == "json":
            self.stdout.write(json.dumps({date: stats}))
        else:
            raise Exception(f"unknown format {output_format}")

    def generate_for_current_date(self):
        """
        Generate and return stats for current date

        Returns

        `dict` with `stats` and `dt` keys
        """

        dt = datetime.datetime.now(datetime.timezone.utc)

        stats = self.stats(dt)

        for tag in self.tags:
            if tag == "automated_nets":
                stats[tag] = Network.automated_net_count().count()
                continue
            model = REFTAG_MAP[tag]
            stats[tag] = model.objects.filter(status="ok").count()

        return {"stats": stats, "dt": dt}

    def generate_for_past_date(self, dt):
        """
        Generate and return stats for past date

        Argument(s)

        - dt: `datetime` instance

        Returns

        `dict` with `stats` and `dt` keys
        """

        dt = dt.replace(hour=23, minute=23, second=59, tzinfo=UTC())
        stats = self.stats(dt)

        for tag in self.tags:
            if tag == "automated_nets":
                stats[tag] = (
                    Network.automated_net_count().filter(created__lte=dt).count()
                )
                continue
            model = REFTAG_MAP[tag]
            stats[tag] = 0
            for obj in model.objects.filter(created__lte=dt):
                if self.status_at_date(obj, dt) == "ok":
                    stats[tag] += 1

        return {"stats": stats, "dt": dt}
