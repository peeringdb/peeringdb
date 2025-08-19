"""
Verification queue cleanup.
"""

import datetime
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import (
    Facility,
    InternetExchange,
    User,
    VerificationQueueItem,
)


class Command(PeeringDBBaseCommand):
    help = "Use this tool to clean up the Verification Queue"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "objtype",
            nargs="?",
            choices=["users", "ix", "fac"],
            help="What objects should be cleaned up",
        )

    def handle(self, *args, **options):
        super().handle(*args, **options)

        if options.get("objtype") == "users":
            self._clean_users()
        elif options.get("objtype") == "ix":
            self._clean_ix()
        elif options.get("objtype") == "fac":
            self._clean_fac()

    def _clean_users(self):
        self._clean_verification_queue_items(User, "VQUEUE_USER_MAX_AGE")

    def _clean_ix(self):
        self._clean_verification_queue_items(InternetExchange, "VQUEUE_IX_MAX_AGE")

    def _clean_fac(self):
        self._clean_verification_queue_items(Facility, "VQUEUE_FAC_MAX_AGE")

    def _clean_verification_queue_items(self, model, setting_name):
        content_type = ContentType.objects.get_for_model(model)
        days = getattr(settings, setting_name)
        date = datetime.datetime.now(datetime.timezone.utc) - timedelta(days=days)

        qset = VerificationQueueItem.objects.filter(
            content_type=content_type, created__lte=date
        )

        count = qset.count()
        model_name = model._meta.verbose_name_plural

        self.log(
            f"Deleting VerificationQueueItems for {model_name} created before {date:%x}"
        )
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
