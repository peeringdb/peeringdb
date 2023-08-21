"""
Load initial data from another peeringdb instance using the REST API.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template import loader
from django.urls import reverse
from django.utils import timezone

from peeringdb_server.models import Organization


class Command(BaseCommand):
    help = "Notify the organization user admins if the member of the organization that required 2fa has a member without 2fa enabled"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

        parser.add_argument("--limit", type=int, default=10)

    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(days=settings.NOTIFY_MISSING_2FA_DAYS)

        orgs_require_2fa = Organization.objects.filter(
            require_2fa=True,
            last_notified__lt=threshold,
            status="ok",
        ) | Organization.objects.filter(
            require_2fa=True,
            last_notified=None,
            status="ok",
        )

        if options.get("limit"):
            limit = options.get("limit")
            orgs_require_2fa = orgs_require_2fa[:limit]

        if any(
            not user.has_2fa
            for org in Organization.objects.all()
            for user in org.all_users
        ):
            for org in orgs_require_2fa:
                users_without_2fa = []
                if org.all_users:
                    org_users_without_2fa = [
                        user for user in org.all_users if not user.has_2fa
                    ]
                    users_without_2fa.extend(org_users_without_2fa)
                if users_without_2fa:
                    if not options.get("commit"):
                        self.stdout.write(f"{org} would get emailed")
                        continue
                    self.notify_org(org, users_without_2fa)

            if not options.get("commit"):
                self.stdout.write(
                    "Run the command with `--commit` if you are sure you want "
                    "to send notification to the organization admins.".format(**options)
                )

    def notify_org(self, org, users):
        users_without_2fa = []

        for user in users:
            users_without_2fa = []
            action_url = f"{settings.BASE_URL}{reverse('handle-2fa')}?org={org.id}&member={user.id}"

            message = loader.get_template(
                "email/notify-org-member-disable-2fa.txt"
            ).render(
                {
                    "org": org.name,
                    "member": user,
                    "drop_member_url": f"{action_url}&action=drop",
                    "leave_member_affiliate_url": f"{action_url}&action=leave",
                    "cancel_2fa_url": f"{action_url}&action=disable",
                    "org_url": f"{settings.BASE_URL}/org/{org.id}#users",
                    "support_email": settings.DEFAULT_FROM_EMAIL,
                }
            )
            users_without_2fa.append(message)

        for admin_user in org.admin_usergroup.user_set.all():
            admin_user.email_user(
                subject=f"The following users affiliated with {org.name} organization do not have 2FA turned on",
                message=loader.get_template(
                    "email/notify-org-user-admin-2fa.txt"
                ).render(
                    {
                        "org_name": org.name,
                        "users_without_2fa": users_without_2fa,
                        "org_url": f"{settings.BASE_URL}/org/{org.id}#users",
                        "support_email": settings.DEFAULT_FROM_EMAIL,
                    }
                ),
            )
        org.last_notified = (
            timezone.now()
        )  # Update last_notified field to the current time
        org.save()
