from io import StringIO

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError

from peeringdb_server import models as pdb_model
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand


class Command(PeeringDBBaseCommand):
    help = "Validates data"

    def add_arguments(self, parser):
        parser.add_argument(
            "object_handleref_tag", type=str, help="Object model handleref tag"
        )
        parser.add_argument("field_name", type=str, help="Handleref field name")
        parser.add_argument(
            "--exclude",
            "-e",
            choices=["valid", "invalid"],
            default=None,
            help="Exclude valid or invalid data",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Display validation results on console",
        )
        parser.add_argument(
            "--display-csv",
            action="store_true",
            help="Display validation results in CSV format on console",
        )
        super().add_arguments(parser)

    def handle(self, *args, **options):
        model = None
        exclude = options.get("exclude")
        self.commit = options.get("commit")
        verbose = options.get("verbose")
        display_csv = options.get("display_csv")
        field_name = options.get("field_name")
        reftag = options.get("object_handleref_tag")

        valid_count = 0
        invalid_count = 0

        model = pdb_model.REFTAG_MAP.get(reftag)

        # model does not exist

        if model is None:
            self.log("[error] Unknown model handleref tag: {reftag}")
            return

        # in preview mode truncate the result set to 20 entries
        # so it can finish quickly

        q = (
            model.handleref.get_queryset().filter(status="ok")
            if self.commit
            else model.handleref.get_queryset().filter(status="ok")[:20]
        )

        results = []

        results.append(["id", "valid"])

        # check that provided field exists on provided model

        try:
            model._meta.get_field(field_name)
        except Exception:
            self.log(f"[error] Unsupported field for validation: {field_name}")
            return

        if self.commit and not display_csv:
            self.log(
                f"Starting validation for {reftag} - {field_name} with {q.count()} total objects"
            )
        if not self.commit and not display_csv:
            self.log(
                f"Starting validation in preview mode for {reftag} - {field_name} with {q.count()} total objects"
            )

        # validate

        for item in q:
            try:
                item.full_clean()

                if exclude == "valid":
                    continue
                results.append([item.pk, True])

            except ValidationError as exc:
                # if the provided field name did not contribute to the validation
                # issues it is counted as valid

                if field_name not in exc.error_dict:
                    results.append((item.pk, True))
                    continue

                # there were some validation issues

                if exclude == "invalid":
                    continue

                results.append((item.pk, False))

        # tally results

        for pk, result in results:
            # first row are header columns

            if pk == "id":
                continue

            if verbose and not display_csv:
                self.log(f"{pk}: {result}")

            if result:
                valid_count += 1
            else:
                invalid_count += 1

        if self.commit:
            # Write the CSV output to django-cache

            result_csv = StringIO()
            result_csv.writelines([f"{r[0]},{r[1]}\n" for r in results])
            cache.delete(f"pdb_validate_data_{reftag}_{field_name}.csv")

            cache.set(
                f"pdb_validate_data_{reftag}_{field_name}.csv",
                result_csv.getvalue(),
                settings.PDB_VALIDATE_DATA_CACHE_TIMEOUT,
            )

        if options.get("display_csv"):
            # write the CSV output to console

            self.log("\n".join([f"{r[0]},{r[1]}" for r in results]))
        if self.commit and not options.get("display_csv"):
            # write completion summary

            self.log(
                f"\nValidation Complete\nValid objects: {valid_count}\nInvalid objects: {invalid_count}"
            )
