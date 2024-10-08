from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from peeringdb_server.models import Facility


class Command(BaseCommand):
    help = "Notifies organization admins about facilities without geocoordinates set"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually send emails and update database entries",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Limit the number of organizations to process",
        )
        parser.add_argument(
            "--min-age", type=int, default=7, help="Minimum age of facilities in days"
        )

    def handle(self, *args, **options):
        # Set auto_now to False to avoid updating the updated field when
        # we mark facilities as notified
        Facility._meta.get_field("updated").auto_now = False

        commit = options["commit"]
        limit = options["limit"]
        min_age = options["min_age"]

        # Dictionary to hold organizations and their facilities without geocoords
        orgs_facilities = {}

        # Select all facilities without geocoordinates set
        facilities_without_geocoords = Facility.objects.filter(
            Q(latitude__isnull=True) | Q(longitude__isnull=True),
            notified_for_geocoords=False,
            status="ok",
        )

        # Exclude facilities with a created date younger than min_age days
        facilities_without_geocoords = facilities_without_geocoords.exclude(
            created__gte=timezone.now() - timedelta(days=min_age)
        )

        # apply limit
        facilities_without_geocoords = facilities_without_geocoords[:limit]

        total_facilities = facilities_without_geocoords.count()

        self.stdout.write(
            f"Found {total_facilities} facilities without geocoordinates..."
        )

        if not total_facilities:
            return

        for facility in facilities_without_geocoords:
            org = facility.org
            # Add facility to its organization's list
            if org not in orgs_facilities:
                orgs_facilities[org] = []
            orgs_facilities[org].append(facility)

        for org, facilities in orgs_facilities.items():
            # Generate the email content
            facilities_list_str = "\n".join([f" - {fac.name}" for fac in facilities])
            message = f"Hello, \n\nThe following facilities belonging to your organization '{org.name}' are missing geocoordinates: \n{facilities_list_str}\nPlease update the geocoordinates to enable your facility for distance search and KMZ inclusion.\n\nBest Regards,\nPeeringDB Team"

            # Retrieve organization admins emails
            # admins_emails = org.admin_usergroup.user_set.values_list('email', flat=True)

            # Retrieve up to 3 organization admin users
            admin_users = org.admin_usergroup.user_set.all()[:3]

            self.stdout.write(
                f"Notifying organization admins of {org.name} about {len(facilities)} facilities without geocoords..."
            )

            if commit:
                # Send email
                for user in admin_users:
                    user.email_user(
                        subject="Facilities without geocoordinates",
                        message=message,
                    )

                # Mark facilities as notified
                for facility in facilities:
                    facility.notified_for_geocoords = True
                    facility.save()

        self.stdout.write(
            f"Processed {total_facilities} facilities without geocoordinates..."
        )
