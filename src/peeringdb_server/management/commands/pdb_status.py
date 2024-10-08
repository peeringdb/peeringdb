"""
Checks entity status integrity (looks for orphaned entities).
"""

from django.core.management.base import BaseCommand

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

STATUS_TYPES = ["ok", "pending", "deleted"]


class Command(BaseCommand):
    help = "Check data status/health"

    def log(self, id, msg):
        print(f"{id}: {msg}")

    def print_line(self):
        print("".join(["-" for i in range(0, 80)]))

    def handle(self, *args, **options):
        # STATUS: handleref status breakdown
        self.print_line()
        self.log("status", "handleref status breakdown")
        self.print_line()
        for model in MODELS:
            counts = {}
            for c in STATUS_TYPES:
                counts[c] = model.objects.filter(status=c).count()
            counts["invalid"] = model.objects.exclude(status__in=STATUS_TYPES).count()

            self.log(
                model.handleref.tag,
                " ".join(["%s(%d)" % (k, v) for k, v in list(counts.items())]),
            )

        # VERSION: print the id of the instances with the highest
        # version for each model - this allows to spot possible import issues
        self.print_line()
        self.log("version", "5 highest version numbers for each handleref type")
        self.print_line()
        for model in MODELS:
            inst = model.objects.order_by("-version")[:5]
            self.log(
                model.handleref.tag,
                ",".join(["%d v=%d" % (o.id, o.version) for o in inst]),
            )

        # Find orphaned elements
        ixlan = (
            pdbm.IXLan.objects.filter(status="ok", ix__status="deleted")
            .select_related("ix")
            .count()
        )
        if ixlan > 0:
            print("%d orphaned ixlans (ix status='deleted')" % ixlan)

        ixfac = (
            pdbm.InternetExchangeFacility.objects.filter(
                status="ok", ix__status="deleted"
            )
            .select_related("ix")
            .count()
        )
        if ixfac > 0:
            print("%d orphaned ixfacs (ix status='deleted')" % ixfac)

        ixfac = (
            pdbm.InternetExchangeFacility.objects.filter(
                status="ok", facility__status="deleted"
            )
            .select_related("facility")
            .count()
        )
        if ixfac > 0:
            print("%d orphaned ixfacs (fac status='deleted')" % ixfac)

        netfac = (
            pdbm.NetworkFacility.objects.filter(status="ok", network__status="deleted")
            .select_related("network")
            .count()
        )
        if netfac > 0:
            print("%d orphaned netfacs (net status='deleted')" % netfac)

        netfac = (
            pdbm.NetworkFacility.objects.filter(status="ok", facility__status="deleted")
            .select_related("facility")
            .count()
        )
        if netfac > 0:
            print("%d orphaned netfacs (fac status='deleted')" % netfac)

        poc = (
            pdbm.NetworkContact.objects.filter(status="ok", network__status="deleted")
            .select_related("network")
            .count()
        )
        if poc > 0:
            print("%d orphaned poc (net status='deleted')" % poc)

        netixlan = (
            pdbm.NetworkIXLan.objects.filter(status="ok", network__status="deleted")
            .select_related("network")
            .count()
        )
        if netixlan > 0:
            print("%d orphaned netixlans (net status='deleted')" % netixlan)

        netixlan = (
            pdbm.NetworkIXLan.objects.filter(status="ok", ixlan__status="deleted")
            .select_related("ixlan")
            .count()
        )
        if netixlan > 0:
            print("%d orphaned netixlans (ixlan status='deleted')" % netixlan)

        ixpfx = (
            pdbm.IXLanPrefix.objects.filter(status="ok", ixlan__status="deleted")
            .select_related("ixlan")
            .count()
        )
        if ixpfx:
            print("%d orphaned ixpfxs (ixlan status='deleted')" % ixpfx)

        for model in [pdbm.Network, pdbm.InternetExchange, pdbm.Facility]:
            count = (
                model.objects.filter(status="ok", org__status="deleted")
                .select_related("org")
                .count()
            )
            if count > 0:
                print(
                    "%d orphaned %ss (org status='deleted')"
                    % (
                        count,
                        model.handleref.tag,
                    )
                )
