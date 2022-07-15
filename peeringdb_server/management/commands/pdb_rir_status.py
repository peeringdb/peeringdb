import reversion
from django.conf import settings as pdb_settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from rdap.assignment import RIRAssignmentLookup

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

        for net in networks:
            status = rir.get_status(net.asn)

            if status in ["assigned", "allocated"]:
                status = "ok"
            else:
                status = None

            self.log(f"{net.name} ({net.asn}) RIR status: {status}")
            if self.commit and (net.rir_status != status or not net.rir_status_updated):
                net.rir_status = status
                net.rir_status_updated = now
                net.save()
