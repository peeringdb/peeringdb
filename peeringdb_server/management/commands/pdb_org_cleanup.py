from django.core.management.base import BaseCommand

from peeringdb_server.models import Organization


class Command(BaseCommand):
    help = "Cleanup deleted Organization objects"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="commit changes, otherwise run in pretend mode",
        )

    def log(self, msg):
        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options):
        self.commit = options.get("commit")

        orgs = Organization.objects.filter(status="deleted")
        # Confirm if user wants to continue via prompt

        for org in orgs:
            self.log(
                f"Cleaning up Organization {org.id} - {org.name} ({org.admin_usergroup.user_set.all().count() + org.usergroup.user_set.all().count()} users)"
            )

            if self.commit:
                # Remove users from user and admin usergroups
                aug = org.admin_usergroup.user_set
                for user in aug.all():
                    aug.remove(user)
                    user.save()

                ug = org.usergroup.user_set

                for user in ug.all():
                    ug.remove(user)
                    user.save()

                # Remove all affiliation requests
                for affiliation in org.affiliation_requests.filter(status="pending"):
                    affiliation.cancel()

            self.log(f"Removed all users from deleted organization {org.id}")
