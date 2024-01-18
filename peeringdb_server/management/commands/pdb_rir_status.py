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

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    @transaction.atomic()
    @reversion.create_revision()
    def handle(self, *args, **options):
        self.commit = options.get("commit")
        self.asn = options.get("asn")
        self.max_age = options.get("max_age")
        self.limit = options.get("limit")

        # dont update network `updated` field on rir status changes

        Network._meta.get_field("updated").auto_now = False

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

            if old_rir_status == new_rir_status:
                continue

            if rir_status_is_ok(old_rir_status):

                # old status was ok

                if not rir_status_is_ok(new_rir_status):

                    # new status not ok

                    # we only update a rir status as changed in the data
                    # if it was previously ok and is now not ok

                    self.log(f"{net.name} ({net.asn}) RIR status: {new_rir_status}")
                    net.rir_status_updated = now

                # store new status regardless of ok/not ok

                net.rir_status = new_rir_status

                if self.commit:
                    batch_save.append(net)
            elif not rir_status_is_ok(old_rir_status):

                # old status not ok

                if rir_status_is_ok(new_rir_status):

                    # new status is ok

                    self.log(f"{net.name} ({net.asn}) RIR status: {new_rir_status}")
                    if self.commit:
                        ticket_queue_rir_status_update(net)
                else:
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

        # batch update

        if self.commit:
            Network.objects.bulk_update(
                batch_save, ["rir_status", "rir_status_updated"]
            )
