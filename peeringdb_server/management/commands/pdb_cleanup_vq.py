from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from peeringdb_server.models import VerificationQueueItem, User
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand

class Command(PeeringDBBaseCommand):

    help = "Use this tool to clean up the Verification Queue"
    
    def add_arguments(self, parser):
        super().add_arguments(parser)
        subparsers = parser.add_subparsers()
        parser_users = subparsers.add_parser('users',
             help='Tool to remove outdated user verification requests')
        parser_users.set_defaults(func=self._clean_users)

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write("[pretend] {}".format(msg))

    def handle(self, *args, **options):
        super().handle(*args, **options)

        if options.get("func"):
            options["func"]()

    def _clean_users(self):
        model = User
        content_type = ContentType.objects.get_for_model(model)
        date = datetime.now(timezone.utc) - timedelta(days=settings.VQUEUE_USER_MAX_AGE)

        qset = VerificationQueueItem.objects.filter(
            content_type=content_type,
            created__lte=date
        )
        count = qset.count()

        self.log(f"Deleting VerificationQueueItems for Users created before {date:%x}")
        self.log(f"Items flagged for deletion: {count}")

        counter = 0

        for vqi in qset:
            counter += 1
            self.log(f"Deleting VerificationQueueItem for {vqi.content_type} "
                     f"id #{vqi.object_id}... {counter} / {count}")
    
            if self.commit:
                vqi.delete()