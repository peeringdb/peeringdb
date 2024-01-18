import reversion
from django.conf import settings as pdb_settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from rdap.assignment import RIRAssignmentLookup

from peeringdb_server.deskpro import ticket_queue_rir_status_update
from peeringdb_server.inet import rir_status_is_ok
from peeringdb_server.models import Network


class Command(BaseCommand):
    help = "Checks and updates RIR status of networks"

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Commit the changes")
        parser.add_argument("--asn", type=int, help="Only check this ASN")
        parser.add_argument("--limit", type=int, help="Only process N networks")
        parser.add_argument(
            "--max-age",
            type=int,
            help="Only check networks with a RIR status older than this age",
        )
        parser.add_argument(
            "--reset", action="store_true", help="Reset all RIR status."
        )
        parser.add_argument(
            "-o",
            "--output",
            help="Output file for --reset, will contain all networks with bad RIR status",
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def reset(self):

        # reset all rir status
        rir = RIRAssignmentLookup()
        rir.load_data(
            pdb_settings.RIR_ALLOCATION_DATA_PATH,
            pdb_settings.RIR_ALLOCATION_DATA_CACHE_DAYS,
        )
        self.log("Resetting all RIR status")

        qset = Network.objects.filter(status="ok")

        bad_networks = []

        batch_save = []
        for net in qset:
            net.rir_status = rir.get_status(net.asn)
            net.rir_status_updated = timezone.now()

            if not rir_status_is_ok(net.rir_status):
                bad_networks.append(net)

            batch_save.append(net)

        self.log(f"Saving {len(batch_save)} networks")
        if self.commit:
            Network.objects.bulk_update(
                batch_save, ["rir_status", "rir_status_updated"]
            )

        if self.output:
            with open(self.output, "w") as f:
                for net in bad_networks:
                    f.write(f"AS{net.asn} {net.rir_status}\n")
            self.log(f"{len(bad_networks)} bad networks written to {self.output}")

    @transaction.atomic()
    @reversion.create_revision()
    def handle(self, *args, **options):
        # dont update network `updated` field on rir status changes

        Network._meta.get_field("updated").auto_now = False

        self.commit = options.get("commit")
        self.asn = options.get("asn")
        self.max_age = options.get("max_age")
        self.limit = options.get("limit")
        self.output = options.get("output")

        reset = options.get("reset")
        if reset:
            self.reset()
            return

        now = timezone.now()
        networks = None

        if self.asn:
            networks = Network.objects.filter(asn=self.asn)
        else:
            networks = Network.objects.filter(status="ok")

        if self.max_age:
            # Exclude networks that are updated less than max_age hours ago
            networks = networks.exclude(
                rir_status_updated__gt=now - timezone.timedelta(hours=self.max_age)
            )

        # order by asn
        networks = networks.order_by("asn")

        # if --limit is provided limit max entries to process
        if self.limit:
            networks = networks[: self.limit]

        rir = RIRAssignmentLookup()
        rir.load_data(
            pdb_settings.RIR_ALLOCATION_DATA_PATH,
            pdb_settings.RIR_ALLOCATION_DATA_CACHE_DAYS,
        )

        reversion.set_comment("pdb_rir_status script")

        batch_save = []

        for net in networks:
            new_rir_status = rir.get_status(net.asn)
            old_rir_status = net.rir_status

            if rir_status_is_ok(old_rir_status) or old_rir_status is None:

                # old status was ok (assigned) or never set

                if not rir_status_is_ok(new_rir_status) or old_rir_status is None:

                    # new status is not ok (!assigned) or old status was never set

                    self.log(f"{net.name} ({net.asn}) RIR status: {new_rir_status}")
                    net.rir_status_updated = now
                    net.rir_status = new_rir_status

                    if self.commit:
                        batch_save.append(net)

            elif not rir_status_is_ok(new_rir_status):

                # new status is not ok (!assigned)

                if rir_status_is_ok(old_rir_status) or old_rir_status is None:

                    # old status was ok (assigned) or never set
                    # notify via deskpro api

                    self.log(f"{net.name} ({net.asn}) RIR status: {new_rir_status}")
                    if self.commit:
                        ticket_queue_rir_status_update(net)
                elif not rir_status_is_ok(old_rir_status):

                    # old status was not ok (!assigned)
                    # check if we should delete the network, because
                    # it has been unassigned for too long

                    notok_since = now - net.rir_status_updated
                    if (
                        notok_since.total_seconds()
                        >= pdb_settings.KEEP_RIR_STATUS * 86400
                    ):
                        self.log(
                            f"{net.name} ({net.asn}) has been RIR unassigned for too long, deleting"
                        )
                        if self.commit:
                            net.delete()
                    else:
                        days = pdb_settings.KEEP_RIR_STATUS - notok_since.days
                        self.log(f"Network still unassigned, {days} left to deletion")

        # batch update

        if self.commit:
            self.log(f"Saving {len(batch_save)} networks")
            Network.objects.bulk_update(
                batch_save, ["rir_status", "rir_status_updated"]
            )
