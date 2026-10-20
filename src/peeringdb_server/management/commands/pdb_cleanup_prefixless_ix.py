"""
One time cleanup of exchanges that are listed without a peering LAN prefix.

#1717 stops new ones from appearing by taking the exchange with its last
prefix, but exchanges that reached that state before the change are not
touched by it. The product committee asked for a one time script to clean
those up on deploy.

The exchange is forced past its own facility-connection and peer guards, the
same as a confirmed last-prefix delete does -- a prefix-less exchange does not
meet the listing criteria regardless of what else is still attached to it.
Everything is soft-deleted and restorable.

Usage:
    # Preview only -- lists what would be deleted, no changes made
    python manage.py pdb_cleanup_prefixless_ix

    # Apply -- soft-deletes the exchanges
    python manage.py pdb_cleanup_prefixless_ix --commit
"""

import reversion
from django.db import transaction

from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import InternetExchange, IXLanPrefix


class Command(PeeringDBBaseCommand):
    help = "Soft-delete listed exchanges that have no active or pending prefix"

    def handle(self, *args, **options):
        super().handle(*args, **options)

        exchanges = self.prefixless_exchanges()

        if not exchanges:
            self.log("No prefix-less exchanges found")
            return

        self.log(f"Found {len(exchanges)} prefix-less exchange(s)")

        for ix in exchanges:
            self.log(
                f"Deleting ix-{ix.id} {ix.name} (org-{ix.org_id}): "
                f"{ix.derived_network_count} active peer(s), "
                f"{ix.ixfac_set_active.count()} active facility connection(s)"
            )

            if self.commit:
                self.delete_exchange(ix)

        self.log(f"Total exchanges deleted: {len(exchanges)}")

    def prefixless_exchanges(self):
        """
        Returns the listed exchanges that have no active or pending prefix
        under any of their ixlans.

        Matching on any ixlan rather than only the exchange's current one
        keeps this conservative: an exchange whose prefix hangs off a stale
        ixlan is left alone for the admin committee rather than deleted here.
        """

        with_prefix = set(
            IXLanPrefix.objects.filter(status__in=["ok", "pending"]).values_list(
                "ixlan__ix_id", flat=True
            )
        )

        return [
            ix
            for ix in InternetExchange.objects.filter(status="ok").order_by("id")
            if ix.id not in with_prefix
        ]

    @reversion.create_revision()
    @transaction.atomic()
    def delete_exchange(self, ix):
        reversion.set_comment(
            "Exchange has no peering LAN prefix (pdb_cleanup_prefixless_ix)"
        )
        ix.delete(force=True)
