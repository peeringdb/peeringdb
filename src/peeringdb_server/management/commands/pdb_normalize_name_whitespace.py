"""
Backfill: collapse 2+ consecutive whitespace in entity `name` fields (#1984).

Fixes rows that predate the validate_name validator. Rows whose normalized name
would collide with an existing non-deleted row (unique=True) are skipped and
reported - a collision may be two distinct entities, so it needs human review,
not an automatic merge. Run this at/before the deploy enabling validate_name.

Usage:

    ./Ctl/dev/run.sh manage pdb_normalize_name_whitespace           # preview
    ./Ctl/dev/run.sh manage pdb_normalize_name_whitespace --commit  # apply
"""

import reversion
from django.db import IntegrityError, transaction

from peeringdb_server import models as pdb_models
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.validators import normalize_name

# entity models whose `name` is user-facing, unique and normalized (#1984)
NAME_MODELS = [
    pdb_models.Organization,
    pdb_models.Facility,
    pdb_models.InternetExchange,
    pdb_models.Network,
    pdb_models.Carrier,
    pdb_models.Campus,
]


class Command(PeeringDBBaseCommand):
    help = "Normalize consecutive whitespace in entity name fields (#1984)."

    @reversion.create_revision()
    @transaction.atomic
    def handle(self, *args, **options):
        self.commit = options.get("commit")
        reversion.set_comment("normalize consecutive whitespace (#1984)")

        total = 0
        conflicts = 0

        for model in NAME_MODELS:
            for obj in model.objects.exclude(status="deleted").iterator():
                original = obj.name
                normalized = normalize_name(original)

                if normalized == original:
                    continue

                # check deleted rows too: the name UNIQUE index spans all
                # statuses (soft-delete never renames). Flag, never auto-merge.
                collision = (
                    model.objects.exclude(id=obj.id).filter(name=normalized).exists()
                )
                if collision:
                    conflicts += 1
                    self.log(
                        f"CONFLICT {model.__name__} id:{obj.id} "
                        f"{original!r} -> {normalized!r} collides with an existing "
                        f"{model.__name__}; skipped (needs manual review)"
                    )
                    continue

                if self.commit:
                    obj.name = normalized
                    try:
                        # per-row savepoint: a missed UNIQUE clash skips this row
                        # instead of aborting the whole run
                        with transaction.atomic():
                            obj.save()
                    except IntegrityError:
                        conflicts += 1
                        self.log(
                            f"CONFLICT {model.__name__} id:{obj.id} "
                            f"{original!r} -> {normalized!r} raised IntegrityError; skipped"
                        )
                        continue

                self.log(f"{model.__name__} id:{obj.id} {original!r} -> {normalized!r}")
                total += 1

        self.log(f"{total} object(s) normalized, {conflicts} conflict(s) skipped.")
