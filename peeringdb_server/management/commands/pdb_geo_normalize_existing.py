import googlemaps
import reversion
import csv
import json

from django.core.management.base import BaseCommand
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
            "--ignore-geo-status",
            action="store_true",
            help="commit changes, otherwise run in pretend mode",
        )

    def log(self, msg):
        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.ignore_geo_status = options.get("ignore_geo_status", False)
        reftag = options.get("reftag")
        limit = options.get("limit")
        if reftag.find(".") > -1:
            reftag, _id = reftag.split(".")
        else:
            _id = 0
        self.gmaps = googlemaps.Client(API_KEY, timeout=5)
        self.normalize(reftag, _id, limit=limit)

    def parse_and_save_suite(self, instance):
        return

    def parse_and_save_floor(self, instance):
        return

    def snapshot_model(self, instance, suffix, data):
        for field in ADDRESS_FIELDS:
            data[field + suffix] = getattr(instance, field)
        return data

    def write_csv(self, output_list):
        keys = ["id", "name"]

        for k in ADDRESS_FIELDS:
            keys.append(k + "_before")
            keys.append(k + "_after")

        with open('normalized_geolocations.csv', 'w') as csv_file:
            dict_writer = csv.DictWriter(csv_file, keys)
            dict_writer.writeheader()
            dict_writer.writerows(output_list)

    @reversion.create_revision()
    def normalize(self, reftag, _id, limit=0):
        model = models.REFTAG_MAP.get(reftag)
        if not model:
            raise ValueError(f"Unknown reftag: {reftag}")
        if not hasattr(model, "geocode_status"):
            raise TypeError(
                "Can only geosync models containing GeocodeBaseMixin"
            )

        if self.ignore_geo_status:
            q = model.handleref.undeleted()
        else:
            q = model.handleref.undeleted().filter(geocode_status=False)

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
                self.snapshot_model(entity, "_after", output_dict)
            except ValueError as exc:
                self.log(str(exc))
            output_list.append(output_dict)

        self.log("writing csv")
        self.write_csv(output_list)

    def _normalize(self, instance, output_dict, save):

        gmaps = self.gmaps

        self.parse_and_save_suite(instance)
        self.parse_and_save_floor(instance)

        # The forward geocode gets the lat,long
        # and returns formatted results for address 1
        forward_result = instance.geocode(gmaps)
        if len(forward_result) > 0:
            address1 = instance.get_address1_from_geocode(forward_result)

        # The reverse result normalizes the administrative levels
        # (city, state, zip) and translates them into English
        reverse_result = instance.reverse_geocode(gmaps)
        data = instance.parse_reverse_geocode(reverse_result)

        # Only change address1, keep address2 the same
        instance.address1 = address1

        if data.get("locality"):
            instance.city = data["locality"]["long_name"]
        if data.get("administrative_area_level_1"):
            instance.state = data["administrative_area_level_1"]["long_name"]
        if data.get("postal_code"):
            instance.zipcode = data["postal_code"]["long_name"]

        if save:
            instance.save()
