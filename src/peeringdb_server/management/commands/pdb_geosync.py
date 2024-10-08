"""
DEPRECATED
Sync latitude and longitude on all geocoding enabled entities.
"""

import googlemaps
import reversion
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from peeringdb_server import models

API_KEY = settings.GOOGLE_GEOLOC_API_KEY


class Command(BaseCommand):
    help = "Sync latitude and longitude on all geocoding enabled entities"

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

    def log(self, msg):
        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        reftag = options.get("reftag")
        limit = options.get("limit")
        if reftag.find(".") > -1:
            reftag, _id = reftag.split(".")
        else:
            _id = 0
        self.gmaps = googlemaps.Client(API_KEY, timeout=5)
        self.sync(reftag, _id, limit=limit)

    @reversion.create_revision()
    @transaction.atomic()
    def sync(self, reftag, _id, limit=0):
        model = models.REFTAG_MAP.get(reftag)
        if not model:
            raise ValueError(f"Unknown reftag: {reftag}")
        if not hasattr(model, "geocode_status"):
            raise TypeError("Can only geosync models containing GeocodeBaseMixin")
        q = model.handleref.undeleted().filter(geocode_status=False)
        if _id:
            q = q.filter(id=_id)
        count = q.count()
        if limit > 0:
            q = q[:limit]
        i = 0
        for entity in q:
            if entity.geocode_status:
                continue
            i += 1
            self.log(f"Syncing {entity.name} [{reftag} {i}/{count} ID:{entity.id}]")

            if self.commit:
                entity.geocode(self.gmaps)
