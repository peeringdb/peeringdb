import csv

from django.core.management.base import BaseCommand

from peeringdb_server import models


class Command(BaseCommand):
    help = "Will export address information into a CSV file for all organizations and facilities."

    csv_fields = [
        "reftag",
        "id",
        "name",
        "address1",
        "address2",
        "suite",
        "floor",
        "city",
        "state",
        "zipcode",
        "country",
    ]

    def add_arguments(self, parser):
        # csv file location
        parser.add_argument(
            "--output",
            type=str,
            default="address_info.csv",
            help="Output file location",
        )

    def write_csv_row(self, csv_writer, reftag, entity):
        csv_writer.writerow(
            [
                reftag,
                entity.id,
                entity.name,
                entity.address1,
                entity.address2,
                entity.suite,
                entity.floor,
                entity.city,
                entity.state,
                entity.zipcode,
                entity.country,
            ]
        )

    def handle(self, *args, **options):
        output_file = options["output"]

        # Get all organizations and facilities

        organizations = models.Organization.objects.filter(status="ok")
        facilities = models.Facility.objects.filter(status="ok")

        # CSV fields

        with open(output_file, "w", newline="") as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow(self.csv_fields)

            for organization in organizations:
                self.write_csv_row(csv_writer, "org", organization)

            for facility in facilities:
                self.write_csv_row(csv_writer, "fac", facility)

        self.stdout.write(
            self.style.SUCCESS(f"Exported address information to {output_file}")
        )
