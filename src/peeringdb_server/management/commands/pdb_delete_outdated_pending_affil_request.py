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
            "--days-old",
            type=int,
            default=settings.AFFILIATION_REQUEST_DELETE_DAYS,
            help="Number of days considered old for pending requests.",
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
            default=10,
            help="Limit the number of requests to delete.",
        )

    def handle(self, *args, **options):
        days_old = options.get("days_old")
        commit = options.get("commit")
        limit = options.get("limit")

        cutoff_date = timezone.now() - timezone.timedelta(days=days_old)
        old_requests = UserOrgAffiliationRequest.objects.filter(
            created__lt=cutoff_date, status="pending"
        )

        if limit:
            old_requests = old_requests[:limit]

        num_requests = len(old_requests)
        if not commit:
            # loop through the outdated pending requests and write to stdout

            for request in old_requests:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Dry Run: Deleting outdated pending request from user `{request.user}` to `{request.org}`"
                    )
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry Run: Would have deleted {num_requests} old pending requests."
                )
            )
            return  # Exit early for dry runs

        self.process_requests(old_requests, days_old)

    def process_requests(self, requests, days_old):
        """
        Loops through the outdated pending requests and sends email notifications to the user and the org admins and then deletes the requests.
        """

        for request in requests:
            org_name = request.org_name
            if request.org:
                org_name = request.org.name
            elif request.asn:
                org_name = f"AS{request.asn}"

            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleting outdated pending request from user `{request.user}` to `{org_name}`"
                )
            )

            self.send_email_notifications(request, days_old, org_name)
        self.delete_requests(requests)

    def send_email_notifications(self, request, days_old, org_name):
        """
        Send email notifications to the user and the org admins about the deletion of the outdated pending requests.
        """
        if request.org:
            for admin in request.org.admin_usergroup.user_set.all():
                self.send_email(
                    recipient=admin,
                    subject=_(
                        "PeeringDB: %(user_name)s's Outdated Pending Requests Deleted"
                    )
                    % {"user_name": request.user.full_name},
                    template_name="email/notify-org-admin-old-pending-uoar-deleted.txt",
                    context={"user": request.user, "days_old": days_old},
                )

        self.send_email(
            recipient=request.user,
            subject=_("PeeringDB: %(org_name)s Outdated Pending Requests Deleted")
            % {"org_name": org_name},
            template_name="email/notify-user-old-pending-uoar-deleted.txt",
            context={"org": org_name, "days_old": days_old},
        )

    def send_email(self, recipient, subject, template_name, context):
        message = loader.get_template(template_name).render(context)
        recipient.email_user(subject, message)

    def delete_requests(self, requests):
        for request in requests:
            request.delete()
        success_message = f"Successfully deleted {len(requests)} old pending requests."
        self.stdout.write(self.style.SUCCESS(success_message))
