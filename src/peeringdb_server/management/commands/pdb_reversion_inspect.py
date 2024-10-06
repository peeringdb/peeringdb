"""
Inspect an object's history of changes.
"""

import json

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from reversion.models import Version

import peeringdb_server.models as pdbm

MODELS = [
    pdbm.Organization,
    pdbm.Network,
    pdbm.InternetExchange,
    pdbm.InternetExchangeFacility,
    pdbm.Facility,
    pdbm.NetworkContact,
    pdbm.NetworkFacility,
    pdbm.IXLan,
    pdbm.IXLanPrefix,
    pdbm.NetworkIXLan,
]


class Command(BaseCommand):
    args = "<reftag> <id, id, ...>"
    help = "Inspect an object's reversion history"

    def log(self, id, msg):
        print(f"{id}: {msg}")

    def print_line(self):
        print("".join(["-" for i in range(0, 80)]))

    def add_arguments(self, parser):
        parser.add_argument("reftag", nargs="?", type=str)
        parser.add_argument("id", nargs="+", type=int)

    def handle(self, *args, **options):
        ref_tag = options.get("reftag")

        ids = [int(i) for i in options.get("id")]

        print((ref_tag, ids))

        model = None
        for m in MODELS:
            if m.handleref.tag == ref_tag:
                model = m
                break

        if not model:
            print("Unknown ref tag: %s" % ref_tag)
            return

        content_type = ContentType.objects.get_for_model(model)
        for id in ids:
            versions = Version.objects.filter(
                content_type=content_type, object_id=id
            ).order_by("revision_id")
            print("%s - %d:" % (ref_tag, id))
            self.print_line()
            prev = {}
            n = 0
            for version in versions:
                data = json.loads(version.serialized_data)[0].get("fields")
                n += 1
                print(
                    "VERSION: %d (%d) - %s - User: %s"
                    % (
                        n,
                        version.id,
                        data.get("updated"),
                        version.revision.user,
                    )
                )
                if not prev:
                    for k, v in list(data.items()):
                        print(f"{k}: '{v}'")
                    self.print_line()
                    prev = data
                    continue
                for k, v in list(data.items()):
                    if prev.get(k) != v:
                        print(f"{k}: '{prev.get(k)}' => '{v}'")

                prev = data
                self.print_line()
