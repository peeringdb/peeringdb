import traceback
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings
from peeringdb_server.models import (
    IXLan,
    NetworkIXLan,
    Network,
    IXFMemberData,
    DeskProTicket,
    IXFImportEmail,
)
from peeringdb_server import ixf


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
            self.stdout.write("[Pretend] {}".format(msg))

    def release_env_check(self, flag):
        if settings.RELEASE_ENV != "prod":
            return True
        else:
            raise PermissionError("Flag {} is not permitted to be used in production.")

    def initiate_reset_flags(self, **options):
        flags = ["reset", "reset_hints", "reset_dismisses", "reset_tickets", "reset_email"]
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
                    "Cannot use flag '{}'' in production".format(active_flags[0]))
            elif len(active_flags) >= 1:
                raise PermissionError(
                    "Cannot use flags '{}' in production".format(", ".join(active_flags)))
        return True

    def reset_all_hints(self):
        self.log("Resetting hints: deleting IXFMemberData instances")
        if self.commit:
            IXFMemberData.objects.all().delete()

            # also reset and protocol conflict hints (#771)
            IXLan.objects.filter(ixf_ixp_import_protocol_conflict__gt=0).update(ixf_ixp_import_protocol_conflict=0)

    def reset_all_dismisses(self):
        self.log("Resetting dismisses: setting IXFMemberData.dismissed=False on all IXFMemberData instances")
        if self.commit:
            for ixfmemberdata in IXFMemberData.objects.all():
                ixfmemberdata.dismissed = False
                ixfmemberdata.save()

    def reset_all_email(self):
        self.log("Resetting email: emptying the IXFImportEmail table")
        if self.commit:
            IXFImportEmail.objects.all().delete()
            IXLan.objects.filter(ixf_ixp_import_error_notified__isnull=False).update(ixf_ixp_import_error_notified=None)

    def reset_all_tickets(self):
        self.log("Resetting tickets: removing DeskProTicket objects where subject contains '[IX-F]'")
        if self.commit:
            DeskProTicket.objects.filter(subject__contains="[IX-F]").delete()

    def create_reset_ticket(self):
        self.log("Creating deskproticket for the following resets: {}".format(
            ", ".join(self.active_flags)
        ))
        if self.commit:
            DeskProTicket.objects.create(
                user=ixf.Importer().ticket_user,
                subject="[IX-F] command-line reset",
                body="Applied the following resets to the IX-F data: {}".format(
                    ", ".join(self.active_flags)),
            )

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.debug = options.get("debug", False)
        self.preview = options.get("preview", False)
        self.cache = options.get("cache", False)
        self.skip_import = options.get("skip_import", False)

        self.active_reset_flags = self.initiate_reset_flags(**options)

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

        ixlan_ids = options.get("ixlan")
        asn = options.get("asn", 0)

        if asn and not ixlan_ids:
            # if asn is specified, retrieve queryset for ixlans from
            # the network object
            net = Network.objects.get(asn=asn)
            qset = net.ixlan_set_ixf_enabled
        else:
            # otherwise build ixlan queryset
            qset = IXLan.objects.filter(status="ok", ixf_ixp_import_enabled=True)
            qset = qset.exclude(ixf_ixp_member_list_url__isnull=True)

            # filter by ids if ixlan ids were specified
            if ixlan_ids:
                qset = qset.filter(id__in=ixlan_ids)

        total_log = {"data": [], "errors": []}
        total_notifications = []

        for ixlan in qset:
            self.log(
                "Fetching data for -ixlan{} from {}".format(
                    ixlan.id, ixlan.ixf_ixp_member_list_url
                )
            )
            try:
                importer = ixf.Importer()
                importer.skip_import = self.skip_import
                importer.cache_only = self.cache
                self.log(f"Processing {ixlan.ix.name} ({ixlan.id})")
                with transaction.atomic():
                    success = importer.update(ixlan, save=self.commit, asn=asn)
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
                        "{}({}): {}".format(ixlan.ix.name, ixlan.id, err)
                        for err in importer.log["errors"]
                    ]
                )
                total_notifications += importer.notifications

            except Exception as inst:
                self.log("ERROR: {}".format(inst))
                self.log(traceback.format_exc())

        if self.preview:
            self.stdout.write(json.dumps(total_log, indent=2))

        # send cosolidated notifications to ix and net for
        # new proposals (#771)

        importer = ixf.Importer()
        importer.reset(save=self.commit)
        importer.notifications = total_notifications
        importer.notify_proposals()

        self.stdout.write(f"Emails: {importer.emails}")
