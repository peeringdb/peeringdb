"""
Deletes outdated pending affiliation requests from the database.

"""

from django.core.management.base import BaseCommand
from django.template import loader
from django.utils import timezone
from django.utils.translation import gettext as _

from mainsite import settings
from peeringdb_server.models import UserOrgAffiliationRequest


class Command(BaseCommand):
    help = "Deletes outdated pending affiliation requests from the database."

    def add_arguments(self, parser):
        # Add command line arguments
        parser.add_argument(
            "--days_old",
            type=int,
            default=settings.AFFILIATION_REQUEST_DELETE_DAYS,
            help="Number of days considered as old for pending requests.",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            default=False,
            help="Will commit changes to the database",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of requests to delete.",
        )

    def handle(self, *args, **options):
        # Get the command line arguments
        days_old = options.get("days_old")
        commit = options.get("commit")
        limit = options.get("limit")

        # Calculate the cutoff date
        cutoff_date = timezone.now() - timezone.timedelta(days=days_old)

        # Get the outdated pending affiliation requests
        old_requests = UserOrgAffiliationRequest.objects.filter(
            created__lt=cutoff_date, status="pending"
        )

        if limit:
            # Limit the number of requests to delete
            old_requests = old_requests[:limit]

        for request in old_requests:
            for admin in request.org.admin_usergroup.user_set.all():
                if commit:
                    # Send email notification to organization admins
                    admin.email_user(
                        _(
                            "PeeringDB: %(user_name)s's Outdated Pending Requests Deleted"
                        )
                        % {"user_name": request.user.full_name},
                        loader.get_template(
                            "email/notify-org-admin-old-pending-uoar-deleted.txt"
                        ).render(
                            {
                                "user": request.user,
                                "days_old": days_old,
                            }
                        ),
                    )

            if commit:
                # Send email notification to the user
                request.user.email_user(
                    _("PeeringDB: %(org_name)s Outdated Pending Requests Deleted")
                    % {"org_name": request.org},
                    loader.get_template(
                        "email/notify-user-old-pending-uoar-deleted.txt"
                    ).render(
                        {
                            "org": request.org,
                            "days_old": days_old,
                        }
                    ),
                )

        if commit:
            if limit:
                # Delete the limited number of requests
                for request in old_requests[:limit]:
                    request.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully deleted {len(old_requests[:limit])} old pending requests."
                    )
                )
            if not limit:
                # Delete all the requests
                old_requests.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully deleted {old_requests.count()} old pending requests."
                    )
                )

        if not commit:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry Run: Would have deleted {old_requests.count()} old pending requests."
                )
            )
