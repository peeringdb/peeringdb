import re
import reversion
from django.core.management.base import BaseCommand

from peeringdb_server.models import (CommandLineTool, Facility,
                                     NetworkFacility, InternetExchangeFacility)


class Command(BaseCommand):
    help = "Undo a facility merge from merge log (either --log or --clt needs to provided)"

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true',
                            help="will commit the fac merge")
        parser.add_argument('--log', help="merge log file")
        parser.add_argument(
            '--clt', help=
            "command line tool instance - this allows you to undo if the command was run from the admin UI"
        )

    def log(self, msg):
        if not self.commit:
            self.stdout.write("[pretend] {}".format(msg))
        else:
            self.stdout.write(msg)

    @reversion.create_revision()
    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.log_file = options.get("log")
        self.clt_id = options.get("clt")

        if self.log_file:
            with open(self.log_file, "r") as fh:
                log = fh.readlines()
        elif self.clt_id:
            clt = CommandLineTool.objects.get(id=self.clt_id,
                                              tool="pdb_fac_merge")
            log = clt.result.split("\n")
        else:
            self.log("[error] no suitable log provided")
            return

        regex_facilities = "Merging facilities (.+) -> (\d+)"
        regex_netfac = "  - netfac NetworkFacility-netfac(\d+)$"
        regex_ixfac = "  - ixfac InternetExchangeFacility-ixfac(\d+)$"
        regex_source = "Merging (.+) \((\d+)\) .."
        regex_delete_netfac = "soft deleting NetworkFacility-netfac(\d+)"
        regex_delete_ixfac = "soft deleting InternetExchangeFacility-ixfac(\d+)"

        sources = {}
        source = None
        for line in log:
            if re.match(regex_facilities, line):
                match = re.match(regex_facilities, line)
                sources = dict([(fac.id, fac)
                                for fac in Facility.objects.filter(
                                    id__in=match.group(1).split(", "))])
                target = Facility.objects.get(id=match.group(2))

                for source in sources.values():
                    if source.org.status != "ok":
                        self.log(
                            "[error] Parent organization {} of facility {} currently has status `{}`, as such the facility cannot be undeleted, please fix the organization and run the script again".
                            format(source.org, source, source.org.status))
                        return

                for source in sources.values():
                    if source.status == "ok" and not self.commit:
                        self.log(
                            "[warning] Looks like this merge has already been undone one way or another, please double check before committing this command"
                        )
                    source.status = "ok"
                    self.log("Undeleting facility {} (#{})".format(
                        source, source.id))
                    if self.commit:
                        source.save()

                source = None

            elif re.match(regex_source, line):
                match = re.match(regex_source, line)
                source = sources[int(match.group(2))]
                self.log("======================")
                self.log("Undoing merge {} (#{})".format(source, source.id))

            elif re.match(regex_netfac, line):
                match = re.match(regex_netfac, line)
                netfac = NetworkFacility.objects.get(id=match.group(1))
                netfac.status = "ok"
                netfac.facility = source
                self.log("Undoing network facility merge (#{})".format(
                    netfac.id))
                if self.commit:
                    netfac.save()

            elif re.match(regex_delete_netfac, line):
                match = re.match(regex_delete_netfac, line)
                netfac = NetworkFacility.objects.get(id=match.group(1))
                netfac.status = "ok"
                self.log("Undoing network facility deletion (#{})".format(
                    netfac.id))
                if self.commit:
                    netfac.save()

            elif re.match(regex_ixfac, line):
                match = re.match(regex_ixfac, line)
                ixfac = InternetExchangeFacility.objects.get(id=match.group(1))
                ixfac.status = "ok"
                ixfac.facility = source
                self.log("Undoing ix facility merge (#{})".format(ixfac.id))
                if self.commit:
                    ixfac.save()

            elif re.match(regex_delete_ixfac, line):
                match = re.match(regex_delete_ixfac, line)
                ixfac = InternetExchangeFacility.objects.get(id=match.group(1))
                ixfac.status = "ok"
                self.log("Undoing ix facility deletion (#{})".format(ixfac.id))
                if self.commit:
                    ixfac.save()
