"""
Undo a facility merge.
"""

import re

import reversion
from django.core.management.base import BaseCommand
from django.db import transaction

from peeringdb_server.models import (
    CommandLineTool,
    Facility,
    InternetExchangeFacility,
    NetworkFacility,
)


class Command(BaseCommand):
    help = (
        "Undo a facility merge from merge log (either --log or --clt needs to provided)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the fac merge"
        )
        parser.add_argument("--log", help="merge log file")
        parser.add_argument(
            "--clt",
            help="command line tool instance - this allows you to undo if the command was run from the admin UI",
        )

    def log(self, msg):
        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    @reversion.create_revision()
    @transaction.atomic()
    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.log_file = options.get("log")
        self.clt_id = options.get("clt")

        if self.log_file:
            with open(self.log_file) as fh:
                log = fh.readlines()
        elif self.clt_id:
            clt = CommandLineTool.objects.get(id=self.clt_id, tool="pdb_fac_merge")
            log = clt.result.split("\n")
        else:
            self.log("[error] no suitable log provided")
            return

        regex_facilities = r"Merging facilities (.+) -> (\d+)"
        regex_netfac = r"  - netfac NetworkFacility object \((\d+)\)$"
        regex_ixfac = r"  - ixfac InternetExchangeFacility object \((\d+)\)$"
        regex_source = r"Merging (.+) \((\d+)\) .."
        regex_delete_netfac = r"soft deleting NetworkFacility object \((\d+)\)"
        regex_delete_ixfac = r"soft deleting InternetExchangeFacility object \((\d+)\)"

        sources = {}
        source = None
        for line in log:
            if re.match(regex_facilities, line):
                match = re.match(regex_facilities, line)
                sources = {
                    fac.id: fac
                    for fac in Facility.objects.filter(
                        id__in=match.group(1).split(", ")
                    )
                }
                Facility.objects.get(id=match.group(2))

                for source in list(sources.values()):
                    if source.org.status != "ok":
                        self.log(
                            f"[error] Parent organization {source.org} of facility {source} currently has status `{source.org.status}`, as such the facility cannot be undeleted, please fix the organization and run the script again"
                        )
                        return

                for source in list(sources.values()):
                    if source.status == "ok" and not self.commit:
                        self.log(
                            "[warning] Looks like this merge has already been undone one way or another, please double check before committing this command"
                        )
                    source.status = "ok"
                    self.log(f"Undeleting facility {source} (#{source.id})")
                    if self.commit:
                        source.save()

                source = None

            elif re.match(regex_source, line):
                match = re.match(regex_source, line)
                source = sources[int(match.group(2))]
                self.log("======================")
                self.log(f"Undoing merge {source} (#{source.id})")

            elif re.match(regex_netfac, line):
                match = re.match(regex_netfac, line)
                netfac = NetworkFacility.objects.get(id=match.group(1))
                netfac.status = "ok"
                netfac.facility = source
                self.log(f"Undoing network facility merge (#{netfac.id})")
                if self.commit:
                    netfac.save()

            elif re.match(regex_delete_netfac, line):
                match = re.match(regex_delete_netfac, line)
                netfac = NetworkFacility.objects.get(id=match.group(1))
                netfac.status = "ok"
                self.log(f"Undoing network facility deletion (#{netfac.id})")
                if self.commit:
                    netfac.save()

            elif re.match(regex_ixfac, line):
                match = re.match(regex_ixfac, line)
                ixfac = InternetExchangeFacility.objects.get(id=match.group(1))
                ixfac.status = "ok"
                ixfac.facility = source
                self.log(f"Undoing ix facility merge (#{ixfac.id})")
                if self.commit:
                    ixfac.save()

            elif re.match(regex_delete_ixfac, line):
                match = re.match(regex_delete_ixfac, line)
                ixfac = InternetExchangeFacility.objects.get(id=match.group(1))
                ixfac.status = "ok"
                self.log(f"Undoing ix facility deletion (#{ixfac.id})")
                if self.commit:
                    ixfac.save()
