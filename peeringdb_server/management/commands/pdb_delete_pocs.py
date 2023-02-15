"""
Hard delete old soft-deleted network contract instances.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from reversion.models import Version

from peeringdb_server.models import NetworkContact


class Command(BaseCommand):
    help = "Hard deletes old soft-deleted network contact instances"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        self._hard_delete_old_pocs()

    def _hard_delete_old_pocs(self):
        qset = NetworkContact.objects.filter(status="deleted")

        date = timezone.now() - timedelta(days=settings.POC_DELETION_PERIOD)

        qset = qset.filter(updated__lte=date)
        count = qset.count()

        self.log(f"Checking soft-deleted poc instances older than {date}")
        self.log(f"Network contacts flagged for hard delete: {count}")

        counter = 1

        for poc in qset:
            self.log(f"Deleting poc={poc.id} ... {counter} / {count}")
            counter += 1

            if self.commit:
                # remove poc reversion data

                versions = Version.objects.get_for_object(poc)
                versions.delete()

                # remove poc

                poc.delete(hard=True)
