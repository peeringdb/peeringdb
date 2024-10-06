"""
Run the IX-F Importer.
"""

import datetime
import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.template import loader
from django.utils import timezone

from peeringdb_server.models import (
    DataChangeEmail,
    DataChangeNotificationQueue,
    DataChangeWatchedObject,
)


class PretendMode(IOError):
    pass


class Command(BaseCommand):
    help = "Sends data change notifications to users that are watching objects for such changes"
    commit = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit changes to the database"
        )
        parser.add_argument(
            "--reset-queue",
            action="store_true",
            help="Removes all Data Change Notification Queue items",
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[Pretend] {msg}")

    def initiate_reset_flags(self, **options):
        flags = [
            "reset_queue",
        ]
        self.active_flags = []
        for flag in flags:
            setattr(self, flag, options.get(flag, False))
            if options.get(flag, False):
                self.active_flags.append(flag)

        self.release_env_check(self.active_flags)
        return self.active_flags

    def release_env_check(self, active_flags):
        if settings.RELEASE_ENV == "prod":
            if len(active_flags) == 1:
                raise PermissionError(
                    f"Cannot use flag '{active_flags[0]}'' in production"
                )
            elif len(active_flags) >= 1:
                raise PermissionError(
                    "Cannot use flags '{}' in production".format(
                        ", ".join(active_flags)
                    )
                )
        return True

    def reset_all_queue(self):
        self.log("Resetting data change notification queue: removing all entries")
        if self.commit:
            DataChangeNotificationQueue.objects.all().delete()

    def cleanup(self):
        """
        data-change notification state cleanup

        remove watched objects for non-permissioned users
        """

        DataChangeEmail.objects.filter(sent__isnull=True).delete()

        # delete stale DataChangeWatchedObject instances

        deleted = DataChangeWatchedObject.cleanup()

        if deleted:
            self.log(f"Removed {deleted} stale watched-object instances")

        # delete old queue entries

        max_age = timezone.now() - datetime.timedelta(
            seconds=settings.DATA_CHANGE_NOTIFY_MAX_AGE
        )
        old = DataChangeNotificationQueue.objects.filter(created__lte=max_age)
        old_num = old.count()
        if old_num:
            old.delete()
            self.log(f"Removed {old_num} old notifications from queue (< {max_age})")

    def create_emails(self):
        users, collected = DataChangeWatchedObject.collect()

        self.emails = {}

        for user_id, notifications in collected.items():
            self.log(f"Preparing notification for user {users[user_id].username}")
            user_notifications = {}
            for notification in notifications.values():
                watched_object = notification.get("watched")
                entries = notification.get("entries")
                self.log(f"    {watched_object}")
                user_notifications[watched_object] = entries

            email = self.create_email(users[user_id], user_notifications)
            self.emails[user_id] = {
                "email": email,
                "watched_objects": [o.id for o in user_notifications.keys()],
            }

    def create_email(self, user, notifications):
        message = loader.get_template("email/data-change-notification.txt").render(
            {
                "notifications": notifications,
                "support_email": settings.SERVER_EMAIL,
                "separator": ("-" * 80),
            }
        )

        return DataChangeEmail.objects.create(
            user=user,
            email=user.email,
            content=message,
            subject="Data change notification",
        )

    def send_emails(self):
        self.log(f"Sending {len(self.emails)} email(s) ..")

        for _, email in self.emails.items():
            if self.commit:
                try:
                    email["email"].send()
                except Exception as exc:
                    self.log(f"[error] trying to send to {email['email'].user}: {exc}")
                    self.errors.append(exc)

                if email["email"].sent:
                    DataChangeWatchedObject.objects.filter(
                        id__in=email["watched_objects"]
                    ).update(last_notified=timezone.now())

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.active_reset_flags = self.initiate_reset_flags(**options)
        self.errors = []

        self._run()

        if self.errors:
            sys.exit(1)

    @transaction.atomic()
    def _run(self):
        sid = None
        try:
            sid = transaction.savepoint()
            self.cleanup()
            self.create_emails()
            self.send_emails()

            if not self.commit:
                raise PretendMode()

        except PretendMode:
            if sid:
                transaction.savepoint_rollback(sid)
            else:
                transaction.rollback()
