"""
Base class to use for command creation.
"""

from django.core.management.base import BaseCommand


class PeeringDBBaseCommand(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Commit the changes.")

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def handle(self, *args, **options):
        self.commit = options.get("commit")
