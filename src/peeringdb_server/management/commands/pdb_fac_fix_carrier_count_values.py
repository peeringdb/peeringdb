"""
Management command to check and fix carrier_count field on Facility objects.

This command verifies and updates the carrier_count field for facilities
based on their active CarrierFacility relationships.

Usage:
    # Check all facilities for wrong carrier_count values (read-only)
    python manage.py pdb_fac_fix_carrier_count_values

    # Check specific facility for wrong carrier_count value
    python manage.py pdb_fac_fix_carrier_count_values --facility-id 2148

    # Fix all facilities with wrong carrier_count values (dry run)
    python manage.py pdb_fac_fix_carrier_count_values --fix-all

    # Fix all facilities with wrong carrier_count values (apply changes)
    python manage.py pdb_fac_fix_carrier_count_values --fix-all --commit

    # Fix specific facility's wrong carrier_count value (apply changes)
    python manage.py pdb_fac_fix_carrier_count_values --facility-id 2148 --commit
"""

from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import Facility
from peeringdb_server.util import disable_auto_now_and_save


class Command(PeeringDBBaseCommand):
    help = "Check and fix carrier_count field for facilities"

    def add_arguments(self, parser):
        parser.add_argument(
            "--facility-id",
            type=int,
            help="Check/fix carrier_count for a specific facility by ID",
        )
        parser.add_argument(
            "--fix-all",
            action="store_true",
            help="Fix all facilities with wrong carrier_count values",
        )
        super().add_arguments(parser)

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        facility_id = options.get("facility_id")
        fix_all = options.get("fix_all", False)

        # Determine which facilities to check
        if facility_id:
            try:
                facilities = [Facility.objects.get(id=facility_id)]
                total_facilities = 1
                mode = f"facility {facility_id}"
            except Facility.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Facility with ID {facility_id} does not exist")
                )
                return
        else:
            facilities = Facility.objects.filter(status="ok")
            total_facilities = facilities.count()
            mode = f"all {total_facilities} facilities"

        # Determine operation mode
        if fix_all or facility_id:
            operation = "Fixing" if self.commit else "Checking (dry run)"
        else:
            operation = "Checking"

        self.stdout.write(f"{operation} carrier_count for {mode}...")
        self.stdout.write("")

        wrong_count = 0
        fixed_count = 0
        correct_count = 0

        for facility in facilities:
            # Calculate the actual carrier count
            actual_carrier_count = facility.carrierfac_set_active.count()

            # Check if carrier_count is wrong
            if facility.carrier_count != actual_carrier_count:
                wrong_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Facility {facility.id} ({facility.name}): "
                        f"carrier_count={facility.carrier_count} but should be {actual_carrier_count}"
                    )
                )

                # Fix if requested
                if fix_all or facility_id:
                    facility.carrier_count = actual_carrier_count
                    if self.commit:
                        disable_auto_now_and_save(facility)
                        self.stdout.write(
                            self.style.SUCCESS(f"  → Fixed to {actual_carrier_count}")
                        )
                    else:
                        self.stdout.write(f"  → Would fix to {actual_carrier_count}")
                    fixed_count += 1
            else:
                correct_count += 1

        # Summary
        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write(f"Total facilities checked: {total_facilities}")
        self.stdout.write(f"Correct carrier_count: {correct_count}")
        self.stdout.write(f"Wrong carrier_count: {wrong_count}")

        if fix_all or facility_id:
            if self.commit:
                self.stdout.write(
                    self.style.SUCCESS(f"Fixed: {fixed_count} facilities")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Would fix: {fixed_count} facilities (use --commit to apply)"
                    )
                )
        elif wrong_count > 0:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Use --fix-all --commit to fix all {wrong_count} facilities with wrong values"
                )
            )
