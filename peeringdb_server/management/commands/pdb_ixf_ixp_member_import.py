import traceback
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from peeringdb_server.models import (
    IXLan,
    NetworkIXLan,
    Network,
)
from peeringdb_server import ixf


class Command(BaseCommand):
    help = "Updates netixlan instances for all ixlans that have their ixf_ixp_member_list_url specified"
    commit = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit changes to the database"
        )
        parser.add_argument("--asn", type=int, default=0, help="Only process this ASN")
        parser.add_argument(
            "--ixlan", type=int, nargs="*", help="Only process these ixlans"
        )
        parser.add_argument("--debug", action="store_true", help="Show debug output")
        parser.add_argument(
            "--preview", action="store_true", help="Run in preview mode"
        )
        parser.add_argument(
            "--cache", action="store_true", help="Only use locally cached IX-F data"
        )
        parser.add_argument(
            "--skip-import",
            action="store_true",
            help="Just update IX-F cache, do NOT perform any import logic",
        )

    def log(self, msg, debug=False):
        if self.preview:
            return
        if debug and not self.debug:
            return
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write("[Pretend] {}".format(msg))

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.debug = options.get("debug", False)
        self.preview = options.get("preview", False)
        self.cache = options.get("cache", False)
        self.skip_import = options.get("skip_import", False)

        if self.preview and self.commit:
            self.commit = False

        ixlan_ids = options.get("ixlan")
        asn = options.get("asn", 0)

        if asn and not ixlan_ids:
            # if asn is specified, retrieve queryset for ixlans from
            # the network object
            net = Network.objects.get(asn=asn)
            qset = net.ixlan_set_ixf_enabled
        else:
            # otherwise build ixlan queryset
            qset = IXLan.objects.filter(status="ok", ixf_ixp_import_enabled=True)
            qset = qset.exclude(ixf_ixp_member_list_url__isnull=True)

            # filter by ids if ixlan ids were specified
            if ixlan_ids:
                qset = qset.filter(id__in=ixlan_ids)

        total_log = {"data": [], "errors": []}

        for ixlan in qset:
            self.log(
                "Fetching data for -ixlan{} from {}".format(
                    ixlan.id, ixlan.ixf_ixp_member_list_url
                )
            )
            try:
                importer = ixf.Importer()
                importer.skip_import = self.skip_import
                importer.cache_only = self.cache
                self.log("Updating {}".format(ixlan))
                with transaction.atomic():
                    success, netixlans, netixlans_deleted, log = importer.update(
                        ixlan, save=self.commit, asn=asn
                    )
                self.log(json.dumps(log), debug=True)
                self.log(
                    "Done: {} updated: {} deleted: {}".format(
                        success, len(netixlans), len(netixlans_deleted)
                    )
                )
                total_log["data"].extend(log["data"])
                total_log["errors"].extend(
                    [
                        "{}({}): {}".format(ixlan.ix.name, ixlan.id, err)
                        for err in log["errors"]
                    ]
                )

            except Exception as inst:
                self.log("ERROR: {}".format(inst))
                self.log(traceback.format_exc())

        if self.preview:
            self.stdout.write(json.dumps(total_log, indent=2))
