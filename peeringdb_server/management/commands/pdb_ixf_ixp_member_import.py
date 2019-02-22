from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from peeringdb_server.models import (
    IXLan, )
import traceback


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
            print(msg)
        else:
            print("[Pretend] {}".format(msg))

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        only_id = options.get("only", 0)
        q = IXLan.objects.filter(status="ok").exclude(
            ixf_ixp_member_list_url__isnull=True)
        if only_id:
            q = q.filter(id=only_id)
        for ixlan in q:
            self.log("Fetching data for {} from {}".format(
                ixlan, ixlan.ixf_ixp_member_list_url))
            try:
                json_data = ixlan.fetch_ixf_ixp_members_list()
                self.log("Updating {}".format(ixlan))
                with transaction.atomic():
                    success, netixlans, netixlans_deleted, log = ixlan.update_from_ixf_ixp_member_list(
                        json_data, save=self.commit)
                for line in log:
                    self.log(line)
                self.log("Done: {} updated: {} deleted: {}".format(
                    success, len(netixlans), len(netixlans_deleted)))
            except Exception as inst:
                self.log("ERROR: {}".format(inst))
                self.log(traceback.format_exc())
