"""
Check and update the RIR status of networks against RIR allocation data, and
remove networks whose ASN has been reclaimed by the RIR/NIR (GH #1942).

Each run compares every network's ASN to the RIR data and:

- flags a network whose status went good -> bad (e.g. "missing"/"reserved"),
  notifying its contacts and starting the deletion countdown,
- deletes a still-unassigned network once it has been notified and
  KEEP_RIR_STATUS days have elapsed,
- clears the flag if the assignment recovers (bad -> good).

Typically run from cron. Without --commit it runs in pretend mode (logs only,
no DB changes or emails).

Usage:
    # dry run (no changes, no emails)
    ./Ctl/dev/run.sh manage pdb_rir_status

    # apply changes / send notifications
    ./Ctl/dev/run.sh manage pdb_rir_status --commit

    # only a single ASN
    ./Ctl/dev/run.sh manage pdb_rir_status --asn 63311 --commit

    # cap the per-run notification burst (e.g. draining a first-deploy backlog)
    ./Ctl/dev/run.sh manage pdb_rir_status --commit --max-notifications 100

    # reset all RIR status / deletion timers (no notifications)
    ./Ctl/dev/run.sh manage pdb_rir_status --reset --commit

Options:
    --commit                 Apply changes and send notifications. Without it the
                             command runs in pretend mode (logs only).
    --asn ASN                Only check this single ASN.
    --limit N                Only process the first N networks (ordered by ASN).
    --max-age HOURS          Skip networks whose rir_status was updated less than
                             HOURS ago (avoids rechecking recently-checked nets).
    --reset                  Reset every network's rir_status / rir_status_updated
                             to the current RIR data and clear the notification
                             marker, resetting all deletion timers. Sends no
                             notifications.
    -o, --output FILE        With --reset, write all networks with a bad RIR
                             status to FILE.
    -M, --max-changes N      Abort (CommandError) if more than N networks flip
                             good<->bad in one run, guarding against mass flagging
                             from bad RIR data. Default 100.
    -N, --max-notifications N  Cap how many removal notifications are sent per run.
                             Networks beyond the cap keep rir_status_notified unset
                             and are handled on later runs, bounding the burst
                             (e.g. a first-deploy backlog, which --max-changes does
                             not cover). Default 100.
"""

import logging

import reversion
from django.conf import settings as pdb_settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from rdap.assignment import RIRAssignmentLookup

from peeringdb_server.deskpro import ticket_queue_rir_status_updates
from peeringdb_server.inet import rir_status_is_ok
from peeringdb_server.mail import mail_network_rir_status_flagged
from peeringdb_server.models import Network

logger = logging.getLogger(__name__)


def _send_rir_status_notifications(networks, days_until_deletion):
    """
    Send RIR-status removal warnings to each network's contacts (GH #1942).

    Run via transaction.on_commit so emails are only sent once changes are
    committed, stay out of the open transaction, and a single failed send
    neither rolls back the run nor blocks the rest.
    """
    for net in networks:
        recipients = net.rir_status_notify_contacts
        if not recipients:
            continue
        try:
            mail_network_rir_status_flagged(net, recipients, days_until_deletion)
        except Exception:
            logger.exception(
                "Failed to send RIR removal notification for AS%s", net.asn
            )


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
        parser.add_argument(
            "-M",
            "--max-changes",
            type=int,
            default=100,
            help="Maximum amount of networks having a RIR status change from good to bad or vice versa. If exceeded, script will exit with error and a human should look at. This is to help prevent mass flagging of networks because of bad RIR data. Default to 100.",
        )
        parser.add_argument(
            "-N",
            "--max-notifications",
            type=int,
            default=100,
            help="Maximum number of RIR-status removal notifications to send per run (GH #1942). Flagged networks beyond this limit keep rir_status_notified unset and are picked up on subsequent runs, bounding the notification burst -- e.g. the first run after deploy against an existing backlog of already-flagged networks, which is not covered by --max-changes. Default to 100.",
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def reset(self):
        """
        Reset RIR status for all networks, setting their
        rir_status to the value read from the RIR allocation data.

        This will also set the rir_status_updated field to now.

        Running this essentially resets the rir status state, resetting
        timelines for stale network deletion.

        This will NOT send any deskpro notifications.

        If the --output option is provided, all networks with a bad
        RIR status will be written to the file.
        """

        # reset all rir status
        rir = RIRAssignmentLookup()
        rir.load_data(
            pdb_settings.RIR_ALLOCATION_DATA_PATH,
            pdb_settings.RIR_ALLOCATION_DATA_CACHE_DAYS,
        )
        self.log("Resetting all RIR status")

        qset = Network.objects.filter(status="ok")
        now = timezone.now()

        bad_networks = []

        batch_save = []
        for net in qset:
            net.rir_status = rir.get_status(net.asn)
            net.rir_status_updated = now
            # GH #1942: resetting timelines also resets the notification cycle
            net.rir_status_notified = None

            if not rir_status_is_ok(net.rir_status):
                bad_networks.append(net)

            batch_save.append(net)

        self.log(f"Saving {len(batch_save)} networks")
        if self.commit:
            Network.objects.bulk_update(
                batch_save,
                ["rir_status", "rir_status_updated", "rir_status_notified"],
            )

        if self.output:
            with open(self.output, "w") as f:
                for net in bad_networks:
                    f.write(f"AS{net.asn} {net.rir_status}\n")
            self.log(
                f"{len(bad_networks)} unassigned networks written to {self.output}"
            )

    @transaction.atomic()
    @reversion.create_revision()
    def handle(self, *args, **options):
        try:
            self.commit = options.get("commit")
            self.asn = options.get("asn")
            self.max_age = options.get("max_age")
            self.limit = options.get("limit")
            self.output = options.get("output")
            self.max_changes = options.get("max_changes")
            self.max_notifications = options.get("max_notifications")

            reset = options.get("reset")
            if reset:
                self.reset()
                return

            now = timezone.now()
            networks = None

            if self.commit:
                # dont update network `updated` field on rir status changes
                Network._meta.get_field("updated").auto_now = False

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

            # tracks networks going from ok rir status to not ok
            # rir status, networks in this list will be notified to the AC via
            # deskpro API
            networks_from_good_to_bad = []
            networks_from_bad_to_good = []

            # GH #1942: networks to warn about pending RIR-status removal.
            # Notified after commit (see _send_rir_status_notifications), so a
            # rollback never warns about a deletion that wasn't recorded.
            networks_to_notify = []

            num_pending_deletion = 0

            for net in networks:
                new_rir_status = rir.get_status(net.asn)
                old_rir_status = net.rir_status

                if not new_rir_status:
                    # missing from rir data, we use None to indicate
                    # never checked, so we set this to missing to
                    # indicate that we have checked and it is missing

                    new_rir_status = "missing"

                if rir_status_is_ok(old_rir_status):
                    # old status was ok (assigned) or never set

                    if not rir_status_is_ok(new_rir_status):
                        # new status is not ok (!assigned) or old status was never set

                        self.log(f"{net.name} ({net.asn}) RIR status: {new_rir_status}")
                        net.rir_status_updated = now
                        net.rir_status = new_rir_status
                        networks_from_good_to_bad.append(net)

                        # GH #1942: queue a warning and set rir_status_notified
                        # (which gates deletion). Past the per-run cap, leave it
                        # unset so the network is warned on a later run before it
                        # can be deleted.
                        if len(networks_to_notify) < self.max_notifications:
                            net.rir_status_notified = now
                            networks_to_notify.append(net)
                            self.log(f"AS{net.asn} flagged, will notify contacts")
                        else:
                            self.log(
                                f"AS{net.asn} flagged, notification deferred (per-run cap reached)"
                            )

                        if self.commit:
                            batch_save.append(net)

                    elif old_rir_status != new_rir_status:
                        # both old and new status are ok (assigned), but they are different
                        net.rir_status_updated = now
                        net.rir_status = new_rir_status

                        if self.commit:
                            batch_save.append(net)

                elif not rir_status_is_ok(new_rir_status):
                    # new status is not ok

                    if not rir_status_is_ok(old_rir_status):
                        # old status was not ok (!assigned)
                        # the network is flagged for deletion

                        if not net.rir_status_notified:
                            # GH #1942: flagged but not yet warned (e.g. flagged
                            # before notifications existed). Warn now and restart
                            # the window from the notification. This path isn't
                            # bounded by --max-changes (the whole backlog lands
                            # here on first deploy), so honour the per-run cap:
                            # past it, leave the network untouched for a later run.
                            if len(networks_to_notify) >= self.max_notifications:
                                self.log(
                                    f"AS{net.asn} flagged for RIR removal, notification deferred (per-run cap reached)"
                                )
                                num_pending_deletion += 1
                                continue

                            self.log(
                                f"AS{net.asn} flagged for RIR removal but not yet notified, notifying and deferring deletion"
                            )
                            net.rir_status_updated = now
                            net.rir_status_notified = now
                            networks_to_notify.append(net)
                            num_pending_deletion += 1

                            if self.commit:
                                batch_save.append(net)

                            continue

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
                                # networks cannot be deleted while they have
                                # active netixlans in them, so we delete those first
                                net.netixlan_set_active.delete()

                                # then we delete the network
                                net.delete()
                        else:
                            days = pdb_settings.KEEP_RIR_STATUS - notok_since.days
                            self.log(
                                f"AS{net.asn} still unassigned, {days} days left to deletion"
                            )
                            num_pending_deletion += 1

                elif rir_status_is_ok(new_rir_status):
                    # new status is ok (assigned)

                    if not rir_status_is_ok(old_rir_status):
                        # old status was not ok (!assigned)
                        # but new status is ok (assigned)
                        net.rir_status_updated = now
                        net.rir_status = new_rir_status
                        # GH #1942: assignment restored, clear the marker so a
                        # future flagging starts a fresh warning cycle.
                        net.rir_status_notified = None
                        if self.commit:
                            batch_save.append(net)

                        networks_from_bad_to_good.append(net)

            if networks_from_good_to_bad:
                # if we have too many networks going from good to bad
                # we exit with an error to prevent mass flagging of networks due to bad
                # RIR data

                num_networks_from_good_to_bad = len(networks_from_good_to_bad)
                self.log(
                    f"Found {num_networks_from_good_to_bad} networks going from assigned to unassigned"
                )
                if num_networks_from_good_to_bad > self.max_changes:
                    raise CommandError(
                        f"Too many networks going from good to bad ({num_networks_from_good_to_bad}), exiting to prevent mass flagging of networks. Please check manually. You can specify a threshold for this via the -M option."
                    )

            if networks_from_bad_to_good:
                num_networks_from_good_to_bad = len(networks_from_bad_to_good)
                self.log(
                    f"Found {num_networks_from_good_to_bad} networks going from unassigned to assigned"
                )

            if num_pending_deletion:
                self.log(
                    f"{num_pending_deletion} networks are pending deletion due to RIR unassignment"
                )

            # batch update

            if self.commit:
                # GH #1942: send notifications only after the transaction
                # commits (see _send_rir_status_notifications).
                if networks_to_notify:
                    self.log(
                        f"Scheduling RIR removal notifications for {len(networks_to_notify)} networks"
                    )
                    notify = list(networks_to_notify)
                    transaction.on_commit(
                        lambda: _send_rir_status_notifications(
                            notify, pdb_settings.KEEP_RIR_STATUS
                        )
                    )

                if networks_from_bad_to_good:
                    # notify admin comittee on networks changed from bad RIR status to ok RIR status

                    ticket_queue_rir_status_updates(
                        networks_from_bad_to_good,
                        self.max_changes,
                        now,
                    )

                self.log(f"Applying rir status updates for {len(batch_save)} networks")
                Network.objects.bulk_update(
                    batch_save,
                    ["rir_status", "rir_status_updated", "rir_status_notified"],
                )
        finally:
            Network._meta.get_field("updated").auto_now = True
