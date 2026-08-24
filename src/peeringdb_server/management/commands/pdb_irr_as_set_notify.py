"""
Soft-window nudge for the #1974 single-set IRR as-set cap.

While the cap (IRR_AS_SET_MAX_SETS) is announced but not yet enforced — i.e.
IRR_AS_SET_CAP_SOFT_START has passed and IRR_AS_SET_CAP_HARD_START has not — this
warns each status=ok network that still lists more than the cap, citing the
hard-start deadline, so operators can consolidate before enforcement kicks in.
It reuses the irr_as_set outreach mail (reason "multi_set").

Scheduled for the length of the soft window, so it must not re-mail on every run:
irr_as_set_cap_notified records who was warned and --renotify-after-days sets the
reminder cadence (default 30 days). --max-notifications bounds the per-run burst;
networks beyond it keep the marker unset and are picked up by a later run. As in
the sibling commands, --commit refuses --max-notifications 0: 0 is not "no cap"
anywhere in this family, so a cron entry copied from one command cannot quietly
mean the opposite in another.

Dry-run by default; --commit stamps the marker and sends the mail on commit of
that same transaction, so a network is never recorded as warned without the send
having been attempted. Once the hard-start date is reached the cap is enforced by
the save-path validator and this nudge stops (the Phase 3 checker sweeps the
rest).

Usage:
  manage pdb_irr_as_set_notify [--commit] [--max-notifications N]
                               [--renotify-after-days N]
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from peeringdb_server import models as pdb_models
from peeringdb_server.mail import mail_network_irr_as_set_flagged
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.settings_util import get_setting_time
from peeringdb_server.validators import tokenize_irr_as_set

logger = logging.getLogger(__name__)


class Command(PeeringDBBaseCommand):
    help = "Warn networks listing more than the #1974 IRR as-set cap (soft window)."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--max-notifications",
            type=int,
            default=100,
            help=(
                "Cap the warning mail per run (pass a large value to warn the "
                "whole set). Bounds the dry-run report too, so what it lists is "
                "what --commit would send; --commit refuses 0, a dry run accepts "
                "it as uncapped. Networks beyond the cap keep "
                "irr_as_set_cap_notified unset and are picked up on subsequent "
                "runs."
            ),
        )
        parser.add_argument(
            "--renotify-after-days",
            type=int,
            default=30,
            help=(
                "Re-warn a network this many days after its last cap nudge "
                "(0 = warn only once)."
            ),
        )

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        max_notifications = options.get("max_notifications") or 0
        renotify_after_days = options.get("renotify_after_days") or 0

        if max_notifications < 0:
            raise CommandError("--max-notifications must be zero or greater.")
        if renotify_after_days < 0:
            raise CommandError("--renotify-after-days must be zero or greater.")

        # Same rule as pdb_irr_as_set_cleanup and pdb_irr_as_set_status: under
        # --commit, 0 is refused rather than read as "no cap". One meaning for the
        # flag across the command family -- a cron entry written by analogy with a
        # sibling would otherwise send an unbounded mail run here.
        if self.commit and not max_notifications:
            raise CommandError(
                "--commit needs a positive --max-notifications: 0 uncaps the cap "
                "nudge mail (default 100)."
            )

        max_sets = settings.IRR_AS_SET_MAX_SETS
        soft = get_setting_time("IRR_AS_SET_CAP_SOFT_START")
        hard = get_setting_time("IRR_AS_SET_CAP_HARD_START")
        now = timezone.now()

        if not max_sets:
            self.log("IRR_AS_SET_MAX_SETS is 0 (uncapped); nothing to warn.")
            return
        if soft is None or now < soft:
            self.log(
                "Soft window not open (IRR_AS_SET_CAP_SOFT_START); nothing to warn."
            )
            return
        if hard is not None and now >= hard:
            self.log("Hard start reached; cap is enforced, soft-window nudge is done.")
            return

        deadline = hard.strftime("%B %d, %Y") if hard else None
        cutoff = None
        if renotify_after_days:
            cutoff = now - timedelta(days=renotify_after_days)

        networks = (
            pdb_models.Network.objects.filter(status="ok")
            .exclude(irr_as_set="")
            .order_by("asn")
        )

        pending = []  # (net, recipients)
        for net in networks.iterator():
            # count with the validator's own tokenizer, so the nudge and the
            # enforcement can never disagree about what is over the cap
            if len(tokenize_irr_as_set(net.irr_as_set)) <= max_sets:
                continue
            if net.irr_as_set_cap_notified and (
                cutoff is None or net.irr_as_set_cap_notified > cutoff
            ):
                continue  # already warned; not due for a reminder
            recipients = net.irr_as_set_notify_contacts
            if not recipients:
                continue
            pending.append((net, recipients))
            self.log(
                f"[notify:multi_set] id:{net.id} asn:{net.asn} "
                f"-> {len(recipients)} contact(s)"
            )
            if max_notifications and len(pending) >= max_notifications:
                break

        self.log(
            f"{len(pending)} network(s) to warn (cap {max_sets}, deadline {deadline})."
        )

        if not self.commit or not pending:
            return

        def _send():
            for net, recipients in pending:
                try:
                    mail_network_irr_as_set_flagged(
                        net, recipients, "multi_set", deadline=deadline
                    )
                except Exception:
                    logger.exception("irr_as_set cap nudge failed for AS%s", net.asn)

        # marker write and send share one transaction, so a rollback discards both.
        # `update()` on purpose -- an internal marker must not bump `updated`, create
        # a reversion version, or re-validate the row.
        with transaction.atomic():
            pdb_models.Network.objects.filter(
                id__in=[net.id for net, _recipients in pending]
            ).update(irr_as_set_cap_notified=now)
            transaction.on_commit(_send)
