"""
Normalize existing address fields based on Google Maps API response.
"""

import csv
import os
import re
import sys
import time
from pprint import pprint

import reversion
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from peeringdb_server import models
from peeringdb_server.geo import Melissa, Timeout
from peeringdb_server.serializers import AddressSerializer

API_KEY = settings.MELISSA_KEY
ADDRESS_FIELDS = AddressSerializer.Meta.fields


class Command(BaseCommand):
    help = "Normalize existing address fields based on Google Maps API response"

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
        parser.add_argument(
            "--floor-and-suite-only",
            action="store_true",
            help="Only parse the floor and suite",
        )
        parser.add_argument(
            "--state-only",
            action="store_true",
            help="Only normalize state/province information",
        )
        parser.add_argument(
            "--csv",
            nargs="?",
            help="""writes a csv displaying changes made by geonormalization.
            Choosing this option without providing a path results
            in a csv being written to the current working directory.
            Users can also choose this option and provide a path.""",
            const=os.path.join(os.getcwd(), "geonormalization.csv"),
            default=False,
        )

    def log(self, msg):
        if self.state_only:
            msg = f"[state-only] {msg}"

        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.floor_and_ste_parse_only = options.get("floor_and_suite_only", False)
        self.state_only = options.get("state_only", False)
        self.pprint = options.get("pprint", False)
        self.csv_file = options.get("csv")
        self.validation_errors = {}

        self.melissa = Melissa(API_KEY)

        reftag = options.get("reftag")
        limit = options.get("limit")

        if reftag is None:
            raise ValueError("No reftag provided")

        if reftag.find(".") > -1:
            reftag, _id = reftag.split(".")
        else:
            _id = 0

        if not limit and _id == 0 and not self.commit:
            raise CommandError("Cannot run in pretend mode without a --limit supplied")

        output_list = self.normalize(reftag, _id, limit=limit)

        if self.csv_file:
            self.log(f"writing csv to {self.csv_file}")
            self.write_csv(output_list)

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

    def parse_suite(self, instance):
        # Case: "Suite 1" or "Suite B"
        pattern = r"(?<=\b[Ss]uite\s)(\w+)"
        suite = re.findall(pattern, instance.address1) + re.findall(
            pattern, instance.address2
        )

        if suite:
            return suite

        # Case: "Ste 1" or "Ste B"

        pattern = r"(?<=\b[Ss]te\s)(\w+)"
        suite = re.findall(pattern, instance.address1) + re.findall(
            pattern, instance.address2
        )

        return suite

    def parse_floor(self, instance):
        # Case "5th floor"
        pattern_before = r"(\d+)(?:st|nd|rd|th)(?=\s[Ff]loor\b)"
        floor = re.findall(pattern_before, instance.address1) + re.findall(
            pattern_before, instance.address2
        )
        # Case: "Floor 2"
        if len(floor) == 0:
            pattern_after = r"(?<=\b[Ff]loor\s)(\d+)"
            floor = re.findall(pattern_after, instance.address1) + re.findall(
                pattern_after, instance.address2
            )
        return floor

    def log_floor_and_ste_changes(self, instance):
        if (instance.floor != "") or (instance.suite != ""):
            self.log(f"{instance.address1}, {instance.address2}")
            self.log(f"Floor: {instance.floor}")
            self.log(f"Suite: {instance.suite}")

    def snapshot_model(self, instance, suffix, data):
        for field in ADDRESS_FIELDS:
            data[field + suffix] = getattr(instance, field)

        return data

    def write_csv(self, output_list):
        keys = ["id", "name"]

        for k in ADDRESS_FIELDS:
            keys.append(k + "_before")
            keys.append(k + "_after")

        with open(self.csv_file, "w") as csvf:
            dict_writer = csv.DictWriter(csvf, keys)
            dict_writer.writeheader()
            dict_writer.writerows(output_list)

    def normalize(self, reftag, _id, limit=0):
        model = models.REFTAG_MAP.get(reftag)

        if not model:
            raise ValueError(f"Unknown reftag: {reftag}")
        if not hasattr(model, "geocode_status"):
            raise TypeError("Can only geosync models containing GeocodeBaseMixin")

        q = model.handleref.undeleted()

        # Exclude if city is null / blank
        q = q.exclude(city__exact="").exclude(city__isnull=True)

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
            self.snapshot_model(entity, "_before", output_dict)

            self.log(f"Normalizing {entity.name} [{reftag} {i}/{count} ID:{entity.id}]")

            proceed_to_next = False

            while not proceed_to_next:
                try:
                    if self.state_only:
                        self._normalize_state(entity, output_dict, self.commit)
                    else:
                        self._normalize(entity, output_dict, self.commit)

                    proceed_to_next = True

                except ValidationError as exc:
                    self.log(f"Validation error: {exc}")
                    self.validation_errors[entity.id] = exc
                    proceed_to_next = True
                except Timeout:
                    self.log("Request has timed out, retrying ...")
                    time.sleep(1.0)

            output_list.append(output_dict)

        return output_list

    @reversion.create_revision()
    @transaction.atomic()
    def _normalize(self, instance, output_dict, save):
        suite = self.parse_suite(instance)
        floor = self.parse_floor(instance)

        if suite or floor:
            instance.address2 = ""

        if len(suite) > 0:
            instance.suite = ", ".join(suite)

        if len(floor) > 0:
            instance.floor = ", ".join(floor)

        if self.floor_and_ste_parse_only:
            self.log_floor_and_ste_changes(instance)

            if save:
                instance.save()
            return

        normalized = instance.process_geo_location(save=False, geocode=False)

        if normalized:
            instance.city = normalized["city"]
            instance.zipcode = normalized["zipcode"]
            instance.address1 = normalized["address1"]
            instance.address2 = normalized["address2"]
            instance.state = normalized["state"]

        if save:
            instance.save()

        self.snapshot_model(instance, "_after", output_dict)

    def _normalize_state(self, instance, output_dict, save):
        if not instance.state:
            self.snapshot_model(instance, "_after", output_dict)
            return

        normalized_state = self.melissa.normalize_state(
            f"{instance.country}", instance.state
        )

        if normalized_state != instance.state and normalized_state:
            instance.state = normalized_state

            if save:
                instance.save()

        self.snapshot_model(instance, "_after", output_dict)
