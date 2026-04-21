"""
Fix orphaned objects where a child has status="ok" but its parent FK
has status="deleted". This can happen when cascade deletes were not
properly triggered historically (e.g., missing delete_cascade entries
or a ProtectedAction blocking the cascade mid-way).

Usage:
    # Preview only — shows what would be fixed, no changes made
    python manage.py pdb_fix_orphaned_objects

    # Apply fixes — soft-deletes all orphaned records
    python manage.py pdb_fix_orphaned_objects --commit
"""

import reversion
from django.db import transaction
from django.db.models import Q

from peeringdb_server.context import forced_ixlan_deletion
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import (
    Carrier,
    CarrierFacility,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLan,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
)

# Each entry: (Model, [(parent_filter_field, "deleted"), ...], force_delete)
# force_delete=True is needed for models with ProtectedMixin.
#
# Campus is intentionally excluded: campus objects may be referenced while
# in pending status, which is expected behavior and not an orphan condition.
ORPHAN_CHECKS = [
    # Org-level children
    (Network, [("org__status", "deleted")], False),
    (Facility, [("org__status", "deleted")], True),
    (InternetExchange, [("org__status", "deleted")], True),
    (Carrier, [("org__status", "deleted")], True),
    # Network-level children
    (NetworkContact, [("network__status", "deleted")], True),
    # IX-level children
    (IXLan, [("ix__status", "deleted")], False),
    # IXLan-level children
    (IXLanPrefix, [("ixlan__status", "deleted")], True),
    (NetworkIXLan, [("ixlan__status", "deleted"), ("network__status", "deleted")], False),
    # Facility-level children
    (InternetExchangeFacility, [("ix__status", "deleted"), ("facility__status", "deleted")], False),
    (NetworkFacility, [("network__status", "deleted"), ("facility__status", "deleted")], False),
    (CarrierFacility, [("carrier__status", "deleted"), ("facility__status", "deleted")], False),
]


class Command(PeeringDBBaseCommand):
    help = "Fix orphaned objects whose parent FK is deleted but the child is still status=ok"

    def handle(self, *args, **options):
        super().handle(*args, **options)

        total = 0

        for model, parent_filters, force in ORPHAN_CHECKS:
            total += self.fix_orphans(model, parent_filters, force)

        self.log(f"Total orphaned objects fixed: {total}")

    def fix_orphans(self, model, parent_filters, force):
        tag = model._handleref.tag

        query = Q()
        for field, value in parent_filters:
            query |= Q(**{field: value})

        orphans = model.objects.filter(status="ok").filter(query)
        count = orphans.count()

        if not count:
            return 0

        self.log(f"[{tag}] Found {count} orphaned object(s)")

        for obj in orphans:
            parents = self._deleted_parents(obj, parent_filters)
            self.log(f"[{tag}] Fixing orphaned {tag}-{obj.id} (deleted parent: {parents})")
            if self.commit:
                self._delete(obj, force=force, use_forced_ixlan_deletion=isinstance(obj, IXLan))

        return count

    def _deleted_parents(self, obj, parent_filters):
        """Return a string listing which parent FKs are deleted, e.g. 'fac-471, carrier-403'"""
        deleted = []
        for field_path, _ in parent_filters:
            field_name = field_path.split("__")[0]
            parent = getattr(obj, field_name, None)
            if parent and parent.status == "deleted":
                parent_tag = parent._handleref.tag
                deleted.append(f"{parent_tag}-{parent.id}")
        return ", ".join(deleted) if deleted else "unknown"

    @reversion.create_revision()
    @transaction.atomic()
    def _delete(self, obj, force=False, use_forced_ixlan_deletion=False):
        reversion.set_comment(
            "Fixing orphaned object with deleted parent (pdb_fix_orphaned_objects)"
        )
        if use_forced_ixlan_deletion:
            with forced_ixlan_deletion():
                obj.delete()
        elif force:
            obj.delete(force=True)
        else:
            obj.delete()
