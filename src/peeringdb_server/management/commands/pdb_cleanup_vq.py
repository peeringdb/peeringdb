"""
Verification queue cleanup.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import User, VerificationQueueItem


class Command(PeeringDBBaseCommand):
    help = "Use this tool to clean up the Verification Queue"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "objtype",
            nargs="?",
            choices=["users"],
            help="What objects should be cleaned up",
        )

    def handle(self, *args, **options):
        super().handle(*args, **options)

        if options.get("objtype") == "users":
            self._clean_users()

    def _clean_users(self):
        model = User
        content_type = ContentType.objects.get_for_model(model)
        date = datetime.now(timezone.utc) - timedelta(days=settings.VQUEUE_USER_MAX_AGE)

        qset = VerificationQueueItem.objects.filter(
            content_type=content_type, created__lte=date
        )
        count = qset.count()

        self.log(f"Deleting VerificationQueueItems for Users created before {date:%x}")
        self.log(f"Items flagged for deletion: {count}")

        counter = 0

        for vqi in qset:
            counter += 1
            self.log(
                f"Deleting VerificationQueueItem for {vqi.content_type} "
                f"id #{vqi.object_id}... {counter} / {count}"
            )

            if self.commit:
                vqi.delete()
