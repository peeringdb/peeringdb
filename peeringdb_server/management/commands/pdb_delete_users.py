"""
Delete childless org objects
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from peeringdb_server.models import User


class PretendMode(IOError):
    pass


class Command(BaseCommand):
    help = "Flags and deletes elderyly orphaned user accounts"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

        parser.add_argument(
            "--max-notify",
            type=int,
            default=10,
            help="maximum amount of user notifications to send",
        )

        parser.add_argument(
            "--max-flag",
            type=int,
            default=0,
            help="maximum amount of user flags to set, set to not limit",
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        self.max_notify = options.get("max_notify")
        self.max_flag = options.get("max_flag")

        self.notifications = []

        sid = transaction.savepoint()

        try:
            with transaction.atomic():
                self.flag_users()
                self.unflag_users()
                self.notify_users()
                self.delete_users()

                if not self.commit:
                    raise PretendMode()

        except PretendMode:
            if sid:
                transaction.savepoint_rollback(sid)
            else:
                transaction.rollback()

        self.send_emails()

    def flag_users(self):
        min_age = timezone.now() - timedelta(days=settings.MIN_AGE_ORPHANED_USER_DAYS)

        qset = User.objects.filter(flagged_for_deletion__isnull=True)
        qset = qset.filter(is_active=True)
        qset = qset.prefetch_related("groups")
        qset = qset.exclude(groups__name__startswith="org.")
        qset = qset.exclude(never_flag_for_deletion=True)
        qset = qset.exclude(date_joined__gte=min_age)

        if self.max_flag > 0:
            self.log(f"Flagging {self.max_flag} of {qset.count()} orphaned users ...")
            qset = qset[: self.max_flag]
        else:
            self.log(f"Flagging {qset.count()} users ...")

        for user in qset:
            deletion_date = timezone.now() + timedelta(
                days=settings.DELETE_ORPHANED_USER_DAYS
            )
            self.log(f"Flagging {user} for deletion on {deletion_date}")
            user.flagged_for_deletion = deletion_date
            user.notified_for_deletion = None
            user.save()

    def unflag_users(self):
        qset = User.objects.filter(flagged_for_deletion__isnull=False)
        qset = qset.prefetch_related("groups")
        qset = qset.filter(groups__name__startswith="org.")

        for user in qset:
            self.log(f"{user} no longer orphaned - removing flag")
            user.flagged_for_deletion = None
            user.notified_for_deletion = None
            user.save()

    def notify_users(self):
        now = timezone.now()
        qset = User.objects.filter(flagged_for_deletion__isnull=False)
        qset = qset.filter(notified_for_deletion__isnull=True).order_by(
            "flagged_for_deletion"
        )

        for user in qset[: self.max_notify]:
            notify_date = user.flagged_for_deletion - timedelta(
                days=settings.NOTIFY_ORPHANED_USER_DAYS
            )

            if notify_date > now:
                continue

            self.log(f"Notifying {user} about pending deletion")
            self.notifications.append(
                (
                    user,
                    "Pending account removal",
                    f"As your account `{user.username}` is no longer associated with any "
                    f"organizations, it will be removed on {user.flagged_for_deletion}."
                    "\n\n"
                    "If you wish to keep your account, please affiliate it with an "
                    "organization.",
                )
            )
            user.notified_for_deletion = timezone.now()
            user.save()

    def send_emails(self):
        count = len(self.notifications)

        if not self.commit:
            self.log(f"Would send {count} emails ...")
            return

        self.log(f"Sending {count} emails ...")

        for user, subject, text in self.notifications:
            user.email_user(subject, text)

    def delete_users(self):
        now = timezone.now()

        qset = User.objects.filter(
            flagged_for_deletion__lte=now, never_flag_for_deletion=False
        )

        for user in qset:
            self.log(f"Closing {user}'s account ..")
            user.close_account()
