"""
Delete childless org objects
"""

import reversion
from django.conf import settings
from django.core.management.base import BaseCommand
from django.template import loader
from django.utils import timezone

from peeringdb_server.models import Organization


class Command(BaseCommand):
    help = "Flags and deletes childless Organizations"

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
        self._delete_childless_org()

    @reversion.create_revision()
    def _delete_childless_org(self):
        # Flag all childless orgs

        self.log("Flagging childless orgs.")

        # We give new orgs a grace period, before they are considered for cleanup
        # this is done for two reasons
        #
        # 1. to avoid emailing new org users hours after creation
        # 2. to avoid flagging new orgs before any users have been added to them

        grace_period = timezone.now() - timezone.timedelta(
            days=settings.ORG_CHILDLESS_GRACE_DURATION
        )

        org_qset = Organization.objects.filter(
            status="ok", flagged__isnull=True, created__lte=grace_period
        )
        flagged_count = 0

        reversion.set_comment("pdb_delete_childless_org processing")

        for org in org_qset:
            # we need to ignore sponsorship orgs, since they may only exist
            # for the purpose of being a sponsor

            if org.sponsorship_set.exists():
                continue

            if org.is_empty:
                admins = org.admin_usergroup.user_set.all()

                self.log(f"Organization {org.name} flagged for deletion")

                if self.commit:
                    org.flagged = True
                    # Do not overwrite flagged date
                    if org.flagged_date is None:
                        org.flagged_date = timezone.now()
                    org.save()

                    for user in admins:
                        email_subject = f"Organization {org.name} flagged for deletion"
                        user.email_user(
                            email_subject,
                            loader.get_template(
                                "email/notify-org-admin-flagged.txt"
                            ).render(
                                {
                                    "org": org,
                                    "duration": settings.ORG_CHILDLESS_DELETE_DURATION,
                                }
                            ),
                        )
                flagged_count += 1

        time_threshold = timezone.now() - timezone.timedelta(
            days=settings.ORG_CHILDLESS_DELETE_DURATION
        )
        org_flagged_qset = Organization.objects.filter(
            status="ok", flagged=True, flagged_date__lte=time_threshold
        )

        org_delete_count = 0

        self.log("Deleting flagged orgs")
        for org in org_flagged_qset:
            # Before deleting, check again if the org is still childless
            #
            # Also check if org gained sponorship status
            #
            # Otherwise, do not delete, remove flags

            if org.is_empty and not org.sponsorship_set.exists():
                if self.commit:
                    org.delete()
                org_delete_count += 1
            else:
                if self.commit:
                    org.flagged = None
                    org.flagged_date = None
                    org.save()
        self.log(f"{org_delete_count} organizations deleted")
        self.log(f"{flagged_count} organizations flagged for deletion")
