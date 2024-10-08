import sys
from pprint import pprint

import pycountry
import reversion
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from peeringdb_server import models


class Command(BaseCommand):
    help = "Normalize existing state fields to alpha code"

    def add_arguments(self, parser):
        parser.add_argument(
            "reftag",
            nargs="?",
            help="can be reftag only such as 'fac' or reftag with id to only sync that specific entity such as 'fac.1'",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="limit how many rows are synced, useful for testing",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="commit changes, otherwise run in pretend mode",
        )
        parser.add_argument(
            "--pprint",
            action="store_true",
            help="pretty print changes at end of run",
        )

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.pprint = options.get("pprint", False)
        self.validation_errors = {}

        reftag = options.get("reftag")
        limit = options.get("limit")

        self.country = ["US", "CA", "AU"]

        if reftag is None:
            raise ValueError("No reftag provided")

        _id = None
        if reftag.find(".") > -1:
            reftag, _id = reftag.split(".")

        output_list = self.normalize(reftag, _id, limit=limit)

        if self.pprint:
            for entry in output_list:
                self.log("{} ({})".format(entry.pop("name"), entry.pop("id")))
                pprint(entry)
                self.log("\n")

        if self.validation_errors:
            self.log("Some objects had validation errors:")
            for entity_id, err in self.validation_errors.items():
                self.log(f"Object #{entity_id}: {err}")
            sys.exit(1)

    def log(self, msg):
        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def snapshot_model(self, instance, suffix, data):
        data["state" + suffix] = getattr(instance, "state")
        return data

    def normalize(self, reftag, _id, limit=0):
        model = models.REFTAG_MAP.get(reftag)
        try:
            # Set auto_now to False to avoid updating the updated field when
            model._meta.get_field("updated").auto_now = False
            if not model:
                raise ValueError(f"Unknown reftag: {reftag}")
            if not hasattr(model, "state"):
                raise TypeError("Can only geosync models containing GeocodeBaseMixin")

            q = model.handleref.undeleted()

            q = q.filter(country__in=self.country)

            # Exclude if state is null / blank
            q = q.exclude(state__exact="").exclude(state__isnull=True)

            if _id:
                q = q.filter(id=_id)
            count = q.count()

            if limit > 0:
                q = q[:limit]

            output_list = []
            i = 0
            for entity in q:
                i += 1
                output_dict = {"id": entity.id, "name": entity.name}
                output_dict["country"] = entity.country.code
                self.snapshot_model(entity, "_before", output_dict)
                self.log(
                    f"Normalizing {entity.name} [{reftag} {i}/{count} ID:{entity.id} State: {entity.state} Country: {entity.country}]"
                )
                try:
                    self._normalize(entity, output_dict, self.commit)

                except ValidationError as exc:
                    self.log(f"Validation error: {exc}")
                    self.validation_errors[entity.id] = exc

                output_list.append(output_dict)

            return output_list
        finally:
            model._meta.get_field("updated").auto_now = True

    @reversion.create_revision()
    @transaction.atomic()
    def _normalize(self, instance, output_dict, save):
        state = instance.state
        ok = pycountry.subdivisions.get(code=f"{instance.country}-{state}")
        if not ok:
            try:
                results = pycountry.subdivisions.search_fuzzy(state)
            except LookupError:
                output_dict["status"] = f"State not found in {instance.country}"
                return
            for result in results:
                if result.country_code == instance.country:
                    code = result.code
                    state = code.split("-")[1]
                    break
        else:
            output_dict["status"] = "skipped"
            return
        if instance.state != state:
            instance.state = state
            if save:
                instance.save()
                output_dict["status"] = "updated"
            self.snapshot_model(instance, "_after", output_dict)
