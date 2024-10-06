"""
DEPRECATED
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
    pdbm.Facility,
    pdbm.NetworkContact,
    pdbm.NetworkFacility,
    pdbm.IXLan,
    pdbm.IXLanPrefix,
    pdbm.NetworkIXLan,
]


class DBCommand(BaseCommand):
    def log(self, id, msg):
        print(f"{id}: {msg}")

    def print_line(self):
        print("".join(["-" for i in range(0, 80)]))

    def handle(self, *args, **options):
        args = list(args)

        try:
            ref_tag = args.pop(0)
        except IndexError:
            print("Please specify object reftag (eg 'net') and at least one id")
            return

        if len(args) == 0:
            print("Please specify at least one id")
            return

        ids = [int(i) for i in args]

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
                content_type=content_type, object_id_int=id
            )
            print("%s - %d:" % (ref_tag, id))
            self.print_line()
            prev = {}
            n = 0
            for version in versions:
                data = json.loads(version.serialized_data)[0].get("fields")
                n += 1
                print(
                    "VERSION: %d - %s - User: %s"
                    % (
                        n,
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
                    if prev[k] != v:
                        print(f"{k}: '{prev[k]}' => '{v}'")

                prev = data
                self.print_line()
