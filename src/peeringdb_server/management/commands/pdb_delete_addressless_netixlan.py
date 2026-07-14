"""
Remove active netixlans that were created by the IX-F importer with neither
an IPv4 nor an IPv6 address.

The IX-F importer used to create address-less netixlans when a network
disabled the only ip protocol its feed advertised (#2005). That has been
fixed at the source, but rows created before the fix remain in the
database - this command cleans them up.

An address-less netixlan is NOT necessarily an import artifact: an admin
can intentionally blank both ip fields via the inline form (#644), and the
importer may have merely modified an entry that was later blanked by hand.
To stay safe this command only deletes a row when the importer itself
CREATED it already address-less - i.e. it has an "add" IX-F import log entry
whose resulting version had neither ip set. Every other address-less row is
only reported, never deleted - handle those by hand.

Rows are soft-deleted (status -> "deleted") so the change is reversible.

Usage:

    # Preview what would be deleted without modifying the database
    ./Ctl/dev/run.sh manage pdb_delete_addressless_netixlan

    # Apply
    ./Ctl/dev/run.sh manage pdb_delete_addressless_netixlan --commit
"""

import reversion
from django.db import transaction

from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import NetworkIXLan


class Command(PeeringDBBaseCommand):
    help = (
        "Soft-delete active netixlans that the IX-F importer created with no "
        "IPv4 or IPv6 address (#2005)."
    )

    def _describe(self, netixlan):
        return (
            f"netixlan id:{netixlan.id} asn:{netixlan.asn} "
            f"ixlan:{netixlan.ixlan_id} ix:{netixlan.ixlan.ix.name}"
        )

    def _ixf_created_blank(self, netixlan):
        """
        Return True only if the IX-F importer created this netixlan already
        address-less (the #2005 artifact): an "add" import-log entry whose
        resulting version had neither ip set. Rows the importer only modified,
        or that once carried an ip, are not matched.
        """
        entries = netixlan.ixf_import_log_entries.filter(
            action="add"
        ).select_related("version_after")
        for entry in entries:
            data = entry.version_after.field_dict
            if not data.get("ipaddr4") and not data.get("ipaddr6"):
                return True
        return False

    @reversion.create_revision()
    @transaction.atomic
    def handle(self, *args, **options):
        self.commit = options.get("commit")

        reversion.set_comment("Removed address-less netixlan (#2005)")

        qset = NetworkIXLan.objects.filter(
            status="ok", ipaddr4__isnull=True, ipaddr6__isnull=True
        ).select_related("ixlan__ix")

        deleted = 0
        skipped = 0

        for netixlan in qset:
            if not self._ixf_created_blank(netixlan):
                skipped += 1
                self.log(
                    f"SKIP (not an IX-F blank-add, review manually): "
                    f"{self._describe(netixlan)}"
                )
                continue

            deleted += 1
            self.log(f"Deleting {self._describe(netixlan)}")
            if self.commit:
                netixlan.delete()

        self.log(
            f"{deleted} IX-F netixlan(s) deleted, "
            f"{skipped} address-less netixlan(s) skipped (not an IX-F blank-add)."
        )
