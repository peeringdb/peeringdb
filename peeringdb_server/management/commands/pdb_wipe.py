"""
Wipe all peering data.
"""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from peeringdb_server.models import REFTAG_MAP, Partnership, Sponsorship, User


class Command(BaseCommand):
    help = "Wipe all peering data, including users - superusers will be kept - cannot be used in production environments"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

        parser.add_argument(
            "--keep-users", action="store_true", help="do not delete users"
        )

        parser.add_argument(
            "--load-data", action="store_true", help="load data after wipe"
        )

        parser.add_argument(
            "--load-data-url",
            type=str,
            default="https://www.peeringdb.com/api",
            help="load data from here",
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.keep_users = options.get("keep_users", False)
        self.load_data = options.get("load_data", False)
        self.load_data_url = options.get("load_data_url")

        settings.ELASTICSEARCH_DSL_AUTOSYNC = False
        settings.ELASTICSEARCH_DSL_AUTO_REFRESH = False

        if not settings.TUTORIAL_MODE:
            self.log("Command can only be run with tutorial mode enabled")
            return

        self.log("Wiping peeringdb data")

        if not self.keep_users:
            if self.commit:
                User.objects.filter(is_superuser=False).delete()
            self.log("Deleted users")

        if self.commit:
            REFTAG_MAP["org"].objects.all().delete()

        self.log("Deleted peering entities")

        if self.commit:
            Sponsorship.objects.all().delete()
            Partnership.objects.all().delete()

        self.log("Deleted sponsorships and partnerships")

        if self.commit:
            call_command("deleterevisions")

        self.log("Deleted reversion data")

        if self.commit:
            call_command("clearsessions", stdout=self.stdout)

        self.log("Cleared seassions")

        self.log(
            "Search indexes will need to be manually updated (if applicable) using the search_index command"
        )

        if self.load_data:
            call_command(
                "pdb_load_data",
                commit=self.commit,
                url=self.load_data_url,
                stdout=self.stdout,
            )
