"""
Put peeringdb in or out of maintenance mode.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from peeringdb_server import maintenance


class Command(BaseCommand):
    help = "Put instance in or out of maintenance mode"

    def add_arguments(self, parser):
        parser.add_argument("state", nargs="?", choices=["on", "off"])
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.state = options.get("state")

        if not settings.TUTORIAL_MODE:
            self.log(
                "Command cannot be run on environment's that are not in tutorial mode. "
                " Maintenance mode "
                " is currently implemented to the extent that it is required to facilitate"
                " an environment reset on `tutorial` type servers and probably needs more work"
                " to be useful on production."
            )
            return

        self.log(f"Setting maintenance mode {self.state}")
        if self.state == "on":
            maintenance.on()
        else:
            maintenance.off()
