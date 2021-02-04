import googlemaps
import reversion
import csv
import os
from pprint import pprint
import re
import datetime

from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError
from django.conf import settings

from peeringdb_server import models
from peeringdb_server.serializers import AddressSerializer

API_KEY = settings.GOOGLE_GEOLOC_API_KEY
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
        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.floor_and_ste_parse_only = options.get("floor_and_suite_only", False)
        self.pprint = options.get("pprint", False)
        self.csv_file = options.get("csv")

        reftag = options.get("reftag")
        limit = options.get("limit")

        if reftag is None:
            raise ValueError("No reftag provided")

        if reftag.find(".") > -1:
            reftag, _id = reftag.split(".")
        else:
            _id = 0

        self.gmaps = googlemaps.Client(API_KEY, timeout=5)
        output_list = self.normalize(reftag, _id, limit=limit)

        if self.csv_file:
            self.log(f"writing csv to {self.csv_file}")
            self.write_csv(output_list)

        if self.pprint:
            for entry in output_list:
                self.log("{} ({})".format(entry.pop("name"), entry.pop("id")))
                pprint(entry)
                self.log("\n")

    def parse_suite(self, instance):

        # Case: "Suite 1" or "Suite B"
        pattern = r"(?<=\b[Ss]uite\s)(\w+)"
        suite = re.findall(pattern, instance.address1) + re.findall(
            pattern, instance.address2
        )
        return suite

    def parse_floor(self, instance):
        # Case "5th floor"
        pattern_before = r"(\d+)(?:st|nd|th)(?=\s[Ff]loor\b)"
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

    @reversion.create_revision()
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

            self.log(
                "Normalizing {} [{} {}/{} ID:{}]".format(
                    entity.name, reftag, i, count, entity.id
                )
            )

            try:
                self._normalize(entity, output_dict, self.commit)

            except ValidationError as exc:
                self.log(str(exc))
            output_list.append(output_dict)

        return output_list

    def _normalize(self, instance, output_dict, save):

        gmaps = self.gmaps

        suite = self.parse_suite(instance)
        floor = self.parse_floor(instance)

        if len(suite) > 0:
            instance.suite = ", ".join(suite)

        if len(floor) > 0:
            instance.floor = ", ".join(floor)

        if self.floor_and_ste_parse_only:
            self.log_floor_and_ste_changes(instance)

            if save:
                instance.save()
            return

        # The forward geocode gets the lat,long
        # and returns formatted results for address1
        # if (instance.latitude is None) or (instance.longitude is None):
        forward_result = instance.geocode(gmaps)

        loc = forward_result[0].get("geometry").get("location")
        instance.latitude = loc.get("lat")
        instance.longitude = loc.get("lng")
        # only change address1, keep address2 the same
        address1 = instance.get_address1_from_geocode(forward_result)
        if address1 is not None:
            instance.address1 = address1
        # The reverse result normalizes the administrative levels
        # (city, state, zip) and translates them into English
        reverse_result = instance.reverse_geocode(gmaps)
        data = instance.parse_reverse_geocode(reverse_result)

        if data.get("locality"):
            instance.city = data["locality"]["long_name"]
        if data.get("administrative_area_level_1"):
            instance.state = data["administrative_area_level_1"]["long_name"]
        if data.get("postal_code"):
            instance.zipcode = data["postal_code"]["long_name"]

        # Set status to True to indicate we've normalized the data
        instance.geocode_status = True
        instance.geocode_date = datetime.datetime.now(datetime.timezone.utc)

        if save:
            instance.save()

        self.snapshot_model(instance, "_after", output_dict)
