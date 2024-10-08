"""
Run the IX-F Importer.
"""

import json
import sys
import traceback

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from peeringdb_server import ixf
from peeringdb_server.models import (
    DeskProTicket,
    InternetExchange,
    IXFImportEmail,
    IXFMemberData,
    IXLan,
    Network,
)


class Command(BaseCommand):
    help = "Updates netixlan instances for all ixlans that have their ixf_ixp_member_list_url specified"
    commit = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit changes to the database"
        )
        parser.add_argument("--asn", type=int, default=0, help="Only process this ASN")
        parser.add_argument(
            "--ixlan", type=int, nargs="*", help="Only process these ixlans"
        )
        parser.add_argument(
            "--process-requested",
            "-P",
            type=int,
            nargs="?",
            help="Process manually requested imports. Specify a number to limit amount of requests to be processed.",
            default=None,
            dest="process_requested",
        )
        parser.add_argument("--debug", action="store_true", help="Show debug output")
        parser.add_argument(
            "--preview", action="store_true", help="Run in preview mode"
        )
        parser.add_argument(
            "--cache", action="store_true", help="Only use locally cached IX-F data"
        )
        parser.add_argument(
            "--skip-import",
            action="store_true",
            help="Just update IX-F cache, do NOT perform any import logic",
        )
        parser.add_argument(
            "--reset-hints",
            action="store_true",
            help="This removes all IXFMemberData objects",
        )
        parser.add_argument(
            "--reset-dismisses",
            action="store_true",
            help="This resets all dismissed IXFMemberData objects",
        )
        parser.add_argument(
            "--reset-tickets",
            action="store_true",
            help="This removes DeskProTicket objects where subject contains '[IX-F]'",
        )
        parser.add_argument(
            "--reset-email",
            action="store_true",
            help="This empties the IXFImportEmail table",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="This removes all IXFMemberData objects",
        )

    def log(self, msg, debug=False):
        if self.preview:
            return
        if debug and not self.debug:
            return
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[Pretend] {msg}")

    def store_runtime_error(self, error, ixlan=None, ixf_member_data=None):
        if ixf_member_data:
            ixlan = ixf_member_data.ixlan
        error_str = ""
        if ixlan:
            error_str += f"Ixlan {ixlan.ix.name} (id={ixlan.id})" + "\n"
            if hasattr(ixlan, "ixf_ixp_member_list_url"):
                error_str += f"IX-F url: {ixlan.ixf_ixp_member_list_url}" + "\n"
        if ixf_member_data:
            error_str += f"Proposal: {ixf_member_data} (id={ixf_member_data.id})\n"

        error_str += f"ERROR: {error}" + "\n"
        error_str += traceback.format_exc()
        self.runtime_errors.append(error_str)

    def write_runtime_errors(self):
        for error in self.runtime_errors:
            self.stderr.write(error)

    def initiate_reset_flags(self, **options):
        flags = [
            "reset",
            "reset_hints",
            "reset_dismisses",
            "reset_tickets",
            "reset_email",
        ]
        self.active_flags = []
        for flag in flags:
            setattr(self, flag, options.get(flag, False))
            if options.get(flag, False):
                self.active_flags.append(flag)

        self.release_env_check(self.active_flags)
        return self.active_flags

    def release_env_check(self, active_flags):
        if settings.RELEASE_ENV == "prod":
            if len(active_flags) == 1:
                raise PermissionError(
                    f"Cannot use flag '{active_flags[0]}'' in production"
                )
            elif len(active_flags) >= 1:
                raise PermissionError(
                    "Cannot use flags '{}' in production".format(
                        ", ".join(active_flags)
                    )
                )
        return True

    def reset_all_hints(self):
        self.log("Resetting hints: deleting IXFMemberData instances")
        if self.commit:
            IXFMemberData.objects.all().delete()

            # also reset and protocol conflict hints (#771)
            IXLan.objects.filter(ixf_ixp_import_protocol_conflict__gt=0).update(
                ixf_ixp_import_protocol_conflict=0
            )

    def reset_all_dismisses(self):
        self.log(
            "Resetting dismisses: setting IXFMemberData.dismissed=False on all IXFMemberData instances"
        )
        if self.commit:
            for ixfmemberdata in IXFMemberData.objects.all():
                ixfmemberdata.dismissed = False
                ixfmemberdata.save()

    def reset_all_email(self):
        self.log("Resetting email: emptying the IXFImportEmail table")
        if self.commit:
            IXFImportEmail.objects.all().delete()
            IXLan.objects.filter(ixf_ixp_import_error_notified__isnull=False).update(
                ixf_ixp_import_error_notified=None
            )

    def reset_all_tickets(self):
        self.log(
            "Resetting tickets: removing DeskProTicket objects where subject contains '[IX-F]'"
        )
        if self.commit:
            DeskProTicket.objects.filter(subject__contains="[IX-F]").delete()

    def create_reset_ticket(self):
        self.log(
            "Creating deskproticket for the following resets: {}".format(
                ", ".join(self.active_flags)
            )
        )
        if self.commit:
            DeskProTicket.objects.create(
                user=ixf.Importer().ticket_user,
                subject="[IX-F] command-line reset",
                body="Applied the following resets to the IX-F data: {}".format(
                    ", ".join(self.active_flags)
                ),
            )

    def resend_emails(self, importer):
        num_emails_to_resend = len(importer.emails_to_resend)
        self.log(f"Attemping to resend {num_emails_to_resend} emails.")
        resent_emails = importer.resend_emails()
        self.log(f"RE-SENT EMAILS: {len(resent_emails)}.")

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.debug = options.get("debug", False)
        self.preview = options.get("preview", False)
        self.cache = options.get("cache", False)
        self.skip_import = options.get("skip_import", False)
        process_requested = options.get("process_requested", None)
        ixlan_ids = options.get("ixlan")
        asn = options.get("asn", 0)

        # err and out should go to the same buffer (#967)
        if not self.preview:
            self.stderr = self.stdout

        if process_requested is not None:
            ixlan_ids = []
            for ix in InternetExchange.ixf_import_request_queue(
                limit=process_requested
            ):
                if ix.id not in ixlan_ids:
                    ixlan_ids.append(ix.id)

            if not ixlan_ids:
                self.log("No manual import requests")
                return

            self.log(f"Processing manual requests for: {ixlan_ids}")

        self.active_reset_flags = self.initiate_reset_flags(**options)

        self.runtime_errors = []

        if self.reset or self.reset_hints:
            self.reset_all_hints()
        if self.reset or self.reset_dismisses:
            self.reset_all_dismisses()
        if self.reset or self.reset_email:
            self.reset_all_email()
        if self.reset or self.reset_tickets:
            self.reset_all_tickets()

        if len(self.active_reset_flags) >= 1:
            self.create_reset_ticket()

        if self.preview and self.commit:
            self.commit = False

        if asn and not ixlan_ids:
            # if asn is specified, retrieve queryset for ixlans from
            # the network object
            net = Network.objects.get(asn=asn)
            qset = net.ixlan_set_ixf_enabled
        else:
            # otherwise build ixlan queryset

            if process_requested is None:
                qset = IXLan.objects.filter(status="ok", ixf_ixp_import_enabled=True)
            else:
                qset = IXLan.objects.filter(status="ok")

            qset = qset.exclude(ixf_ixp_member_list_url__isnull=True)

            # filter by ids if ixlan ids were specified
            if ixlan_ids:
                qset = qset.filter(id__in=ixlan_ids)

        total_log = {"data": [], "errors": []}
        total_notifications = []
        for ixlan in qset:
            self.log(
                f"Fetching data for -ixlan{ixlan.id} from {ixlan.ixf_ixp_member_list_url}"
            )
            try:
                importer = ixf.Importer()
                importer.skip_import = self.skip_import
                importer.cache_only = self.cache
                self.log(f"Processing {ixlan.ix.name} ({ixlan.id})")
                success = None
                with transaction.atomic():
                    success = importer.update(
                        ixlan,
                        save=self.commit,
                        asn=asn,
                        timeout=settings.IXF_FETCH_TIMEOUT,
                    )
                self.log(json.dumps(importer.log), debug=True)
                self.log(
                    "Success: {}, added: {}, updated: {}, deleted: {}".format(
                        success,
                        len(importer.actions_taken["add"]),
                        len(importer.actions_taken["modify"]),
                        len(importer.actions_taken["delete"]),
                    )
                )
                total_log["data"].extend(importer.log["data"])
                total_log["errors"].extend(
                    [
                        f"{ixlan.ix.name}({ixlan.id}): {err}"
                        for err in importer.log["errors"]
                    ]
                )
                total_notifications += importer.notifications

            except Exception as inst:
                self.store_runtime_error(inst, ixlan=ixlan)
            finally:
                if process_requested is not None:
                    if success:
                        ixlan.ix.ixf_import_request_status = "finished"
                    else:
                        ixlan.ix.ixf_import_request_status = "error"
                    ixlan.ix.save_without_timestamp()

        if self.preview:
            self.stdout.write(json.dumps(total_log, indent=2))

        # send cosolidated notifications to ix and net for
        # new proposals (#771)

        importer = ixf.Importer()
        importer.reset(save=self.commit)
        importer.notifications = total_notifications
        importer.notify_proposals(error_handler=self.store_runtime_error)

        self.stdout.write(f"New Emails: {importer.emails}")

        num_errors = len(self.runtime_errors)

        if num_errors > 0:
            self.stdout.write(f"Errors: {num_errors}\n\n")
            self.write_runtime_errors()
            sys.exit(1)

        if self.commit:
            self.resend_emails(importer)
