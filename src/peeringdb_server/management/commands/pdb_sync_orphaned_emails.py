"""
Django management command to sync orphaned User.email to EmailAddress table.

This command finds users where User.email is set but doesn't exist in their
emailaddress_set, and creates the corresponding EmailAddress objects.

Usage:
    python manage.py pdb_sync_orphaned_emails
    python manage.py pdb_sync_orphaned_emails --dry-run
"""

from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand
from django.db import transaction

from peeringdb_server.models import User


class Command(BaseCommand):
    help = "Sync orphaned User.email values to EmailAddress table (issue #1852)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be synced without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )
            self.stdout.write("")

        synced = 0
        skipped_already_exists = 0
        skipped_duplicate = 0
        duplicate_users = []

        users = User.objects.exclude(email__isnull=True).exclude(email="")

        self.stdout.write("=" * 80)
        self.stdout.write("Scanning users for orphaned emails...")
        self.stdout.write("=" * 80)
        self.stdout.write("")

        for user in users:
            # Check if user already has EmailAddress for their email
            if EmailAddress.objects.filter(
                user=user, email__iexact=user.email
            ).exists():
                skipped_already_exists += 1
                continue

            # Check if another user already has this email
            existing_email = EmailAddress.objects.filter(
                email__iexact=user.email
            ).first()
            if existing_email:
                other_user = existing_email.user

                self.stdout.write(
                    self.style.ERROR(
                        f"DUPLICATE EMAIL: User {user.id} ({user.username}) has email '{user.email}' "
                        f"which is already in EmailAddress table for user {other_user.id} ({other_user.username})"
                    )
                )
                duplicate_users.append(
                    {
                        "user_id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "conflict_user_id": other_user.id,
                        "conflict_username": other_user.username,
                    }
                )
                skipped_duplicate += 1
                continue

            # Create EmailAddress for this user
            if not dry_run:
                with transaction.atomic():
                    EmailAddress.objects.create(
                        user=user,
                        email=user.email,
                        verified=False,
                        primary=True,
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"SYNCED: User {user.id} ({user.username}) - email '{user.email}' "
                        f"(verified=False, will need confirmation)"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"WOULD SYNC: User {user.id} ({user.username}) - email '{user.email}'"
                    )
                )
            synced += 1

        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Total users with email: {users.count()}")
        self.stdout.write(f"Users synced: {synced}")
        self.stdout.write(
            f"Skipped (already have EmailAddress): {skipped_already_exists}"
        )
        self.stdout.write(f"Skipped (duplicate email conflict): {skipped_duplicate}")
        self.stdout.write("=" * 80)

        if synced > 0:
            if dry_run:
                self.stdout.write("")
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would sync {synced} orphaned User.email values"
                    )
                )
            else:
                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully synced {synced} orphaned User.email values to EmailAddress table"
                    )
                )
        elif skipped_already_exists > 0:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "No action needed - all users already have EmailAddress objects"
                )
            )

        if duplicate_users:
            self.stdout.write("")
            self.stdout.write("=" * 80)
            self.stdout.write(
                self.style.ERROR(
                    "DUPLICATE EMAIL CONFLICTS REQUIRING MANUAL RESOLUTION"
                )
            )
            self.stdout.write("=" * 80)
            for dup in duplicate_users:
                self.stdout.write(
                    f"User {dup['user_id']} ({dup['username']}) has email '{dup['email']}' "
                    f"which conflicts with User {dup['conflict_user_id']} ({dup['conflict_username']})"
                )
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Please manually resolve {len(duplicate_users)} duplicate email conflict(s) "
                    "by either deleting duplicate users or changing their email addresses."
                )
            )
            self.stdout.write("=" * 80)
