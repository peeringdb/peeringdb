from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from peeringdb_server.models import VerificationQueueItem, User

class CustomBaseCommand(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write("[pretend] {}".format(msg))

    def handle(self, *args, **options):
        self.commit = options.get("commit")


class Command(CustomBaseCommand):

    help = "Use this tool to clean up the Verification Queue"
    
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--users", action="store_true", help="will commit the changes"
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write("[pretend] {}".format(msg))

    def handle(self, *args, **options):
        super().handle(*args, **options)
        self.users = options.get("users")

        if self.users:
            self._clean_users()
        else:
            self.log(
                "Users option is currently the only one supported,"
                " and the --users flag must be provided to use it.")

    def _clean_users(self):
        model = User
        content_type = ContentType.objects.get_for_model(model)
        date = datetime.now(timezone.utc) - timedelta(days=90)

        qset = VerificationQueueItem.objects.filter(
            content_type=content_type,
            created__lte=date
        )
        count = qset.count()
        
        self.log(f"Deleting VerificationQueueItems for Users created before {date:%x}")
        self.log(f"Items flagged for deletion: {count}")

        counter = 0

        for vqi in qset:
            count += 1
            self.log(f"Deleting VerificationQueueItem for ={poc.id} ... {counter} / {count}")
    
            if self.commit:
                vqi.delete()