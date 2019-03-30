import traceback
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from peeringdb_server.models import (
    IXLan, )
from peeringdb_server import ixf


class Command(BaseCommand):
    help = "Updates netixlan instances for all ixlans that have their ixf_ixp_member_list_url specified"
    commit = False

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true',
                            help="will commit changes to the database")
        parser.add_argument('--only', type=int, default=0,
                            help="Only process this ixlan")

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write("[Pretend] {}".format(msg))

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        only_id = options.get("only", 0)
        q = IXLan.objects.filter(status="ok").exclude(
            ixf_ixp_member_list_url__isnull=True)
        if only_id:
            q = q.filter(id=only_id)
        for ixlan in q:

            # if the ixlan has ix-f imports disabled we skip it
            if not ixlan.ixf_ixp_import_enabled:
                self.log("IX-F import disabled on ixlan {}, skippig..".format(ixlan.id))
                continue

            self.log("Fetching data for {} from {}".format(
                ixlan, ixlan.ixf_ixp_member_list_url))
            try:
                importer = ixf.Importer()
                self.log("Updating {}".format(ixlan))
                with transaction.atomic():
                    success, netixlans, netixlans_deleted, log = importer.update(ixlan, save=self.commit)
                self.log(json.dumps(log))
                self.log("Done: {} updated: {} deleted: {}".format(
                    success, len(netixlans), len(netixlans_deleted)))
            except Exception as inst:
                self.log("ERROR: {}".format(inst))
                self.log(traceback.format_exc())
