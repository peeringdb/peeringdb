"""
Backfill: remove emoji from entity name fields (#2018).

Removes emoji from the name fields of existing rows, along with the spaces
around them. A change that can't be applied - the new value would collide with
another row's (unique=True), a required field held nothing but emoji, or the
row's parent organization has a status that blocks saving it - is skipped and
reported; the rest of the run still applies. --report writes every
change and skip to a CSV.

Nothing is mailed by default. --notify with --commit emails each affected
organization's admins the changes made to its objects once the run has
committed; --notify without --commit only lists who would be mailed. Skipped
rows are not mailed.

™ © ® count as emoji only when the EMOJI_INCLUDE_TRADEMARK_SIGNS setting is
on (default off), both here and in the API, admin and web validators.

--limit N only changes the objects of the first N organizations that have
something to change, so each run mails at most N organizations. Changed rows
no longer match, so running again continues with the next ones.

Usage:

    ./Ctl/dev/run.sh pdb_strip_name_emoji                            # preview
    ./Ctl/dev/run.sh pdb_strip_name_emoji --report /tmp/emoji.csv    # preview + CSV
    ./Ctl/dev/run.sh pdb_strip_name_emoji --commit --report <path>   # apply
    ./Ctl/dev/run.sh pdb_strip_name_emoji --commit --notify          # apply + email
    ./Ctl/dev/run.sh pdb_strip_name_emoji --commit --notify --limit 10   # batch
"""

import csv
import logging
from collections import defaultdict

import reversion
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction

from peeringdb_server.emoji import EMOJI_FREE_TAGS, emoji_free_fields, emoji_regex
from peeringdb_server.mail import mail_org_admins_emoji_removed
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.models import (
    REFTAG_MAP,
    Organization,
    ParentStatusCheckMixin,
    ParentStatusException,
)
from peeringdb_server.validators import normalize_name, strip_emoji

logger = logging.getLogger(__name__)

REPORT_COLUMNS = ["ref_tag", "id", "org_id", "field", "current", "proposed", "result"]


def org_of(obj):
    """
    The id of the organization that owns `obj`; an org is its own owner.
    """
    return getattr(obj, "org_id", obj.id)


class Command(PeeringDBBaseCommand):
    help = "Remove emoji from entity name fields (#2018)."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--report",
            help="Write every change and skipped change to this CSV file.",
        )
        parser.add_argument(
            "--notify",
            action="store_true",
            help="Email each affected organization's admins the changes made "
            "to its objects, after the run commits.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Only change the objects of the first N organizations that "
            "have changes (0 = no limit). Run again to continue.",
        )

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        self.notify = options.get("notify")
        self.limit = options.get("limit")
        if self.limit < 0:
            raise CommandError("--limit must be zero or greater.")
        # orgs with changes in this run, counted against --limit
        self.orgs_changed = set()
        self.rows = []
        self.skipped = 0
        # applied changes per org id, for --notify
        self.changes_by_org = defaultdict(list)
        # unique values already taken by earlier rows of this run, so a dry
        # run reports the same collisions a commit would hit
        self.claimed = {}

        # open the report before touching any row, so a bad path fails the
        # run up front instead of rolling back a finished one
        report = None
        if options.get("report"):
            report = open(options["report"], "w", newline="", encoding="utf-8")
        try:
            self.strip_all()
            if report:
                writer = csv.DictWriter(report, fieldnames=REPORT_COLUMNS)
                writer.writeheader()
                writer.writerows(self.rows)
        finally:
            if report:
                report.close()

        changed = len(self.rows) - self.skipped
        self.log(
            f"{changed} field(s) changed, {self.skipped} skipped (need manual cleanup)."
        )

    @reversion.create_revision()
    @transaction.atomic
    def strip_all(self):
        reversion.set_comment("remove emoji from name fields (#2018)")

        for tag in EMOJI_FREE_TAGS:
            model = REFTAG_MAP[tag]
            fields = emoji_free_fields(model)
            for obj in model.objects.exclude(status="deleted").iterator():
                self.strip_object(model, obj, fields)

        if self.notify and self.commit:
            # after commit: a rollback never mails about changes that weren't
            # made, and SMTP stays out of the open transaction
            changes_by_org = dict(self.changes_by_org)
            transaction.on_commit(lambda: self.send_notifications(changes_by_org))
        elif self.notify:
            self.preview_notifications()

    def preview_notifications(self):
        for org_id, changes in self.changes_by_org.items():
            admins = Organization.objects.get(id=org_id).admin_usergroup
            self.log(
                f"would notify org id:{org_id} admins "
                f"({admins.user_set.count()} user(s)) of {len(changes)} change(s)"
            )

    def send_notifications(self, changes_by_org):
        for org_id, changes in changes_by_org.items():
            try:
                org = Organization.objects.get(id=org_id)
                mail_org_admins_emoji_removed(org, changes)
                self.log(f"notified org id:{org_id} admins of {len(changes)} change(s)")
            except Exception:
                # one failed send must not stop the others
                logger.exception("Failed to send emoji notification to org %s", org_id)

    def strip_object(self, model, obj, fields):
        org_id = org_of(obj)
        if (
            self.limit
            and org_id not in self.orgs_changed
            and len(self.orgs_changed) >= self.limit
        ):
            return

        changes = {}
        for field in fields:
            current = getattr(obj, field)
            if not current or not emoji_regex().search(current):
                continue

            proposed = strip_emoji(current)
            if field == "name":
                # name must also pass validate_name (#1984), e.g. no-break
                # spaces left on both sides of a removed emoji
                proposed = normalize_name(proposed)
            reason = self.skip_reason(model, obj, field, proposed)
            if reason:
                self.record(
                    obj, field, current, proposed, f"skipped: {reason}", skipped=True
                )
            else:
                changes[field] = (current, proposed)

        if not changes:
            return

        if isinstance(obj, ParentStatusCheckMixin):
            # save() would refuse this row; checking before the commit branch
            # lets a dry run report the same skip
            try:
                obj.validate_parent_status()
            except ParentStatusException:
                self.skip_row(obj, changes, "parent status")
                return

        if self.commit:
            for field, (_, proposed) in changes.items():
                setattr(obj, field, proposed)
            try:
                # per-row savepoint: a missed UNIQUE clash skips this row
                # instead of aborting the whole run
                with transaction.atomic():
                    obj.save()
            except IntegrityError:
                self.skip_row(obj, changes, "integrity error")
                return

        # only an applied row claims its new values and uses up its org's
        # --limit slot, so a skipped row neither blocks later rows nor the batch
        self.orgs_changed.add(org_id)
        for field, (_, proposed) in changes.items():
            if model._meta.get_field(field).unique:
                # casefold approximates the case-insensitive collation of the
                # UNIQUE index; the per-row savepoint catches the rest
                self.claimed[(model, field, proposed.casefold())] = obj.id

        result = "changed" if self.commit else "would change"
        for field, (current, proposed) in changes.items():
            self.record(obj, field, current, proposed, result)

    def skip_row(self, obj, changes, reason):
        for field, (current, proposed) in changes.items():
            self.record(
                obj, field, current, proposed, f"skipped: {reason}", skipped=True
            )

    def skip_reason(self, model, obj, field, proposed):
        model_field = model._meta.get_field(field)

        if not proposed and not model_field.blank:
            return "nothing left after removing emoji"

        if model_field.unique and proposed:
            claimed_by = self.claimed.get((model, field, proposed.casefold()))
            if claimed_by:
                return (
                    f"collides with {obj.ref_tag} id:{claimed_by} (changed in this run)"
                )

            # check deleted rows too: the UNIQUE index spans all statuses
            # (soft-delete never renames). Flag, never auto-merge.
            other = (
                model.objects.exclude(id=obj.id)
                .filter(**{field: proposed})
                .values_list("id", flat=True)
                .first()
            )
            if other:
                return f"collides with {obj.ref_tag} id:{other}"

        return None

    def record(self, obj, field, current, proposed, result, skipped=False):
        if skipped:
            self.skipped += 1
        else:
            self.changes_by_org[org_of(obj)].append(
                {
                    "entity_type": obj._meta.verbose_name.capitalize(),
                    "ref_tag": obj.ref_tag,
                    "id": obj.id,
                    "field": obj._meta.get_field(field).verbose_name,
                    "current": current,
                    "proposed": proposed,
                }
            )
        self.rows.append(
            {
                "ref_tag": obj.ref_tag,
                "id": obj.id,
                "org_id": org_of(obj),
                "field": field,
                "current": current,
                "proposed": proposed,
                "result": result,
            }
        )
        self.log(
            f"{result} {obj.ref_tag} id:{obj.id} {field}: {current!r} -> {proposed!r}"
        )
