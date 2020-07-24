import ipaddress

from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError
import reversion

from peeringdb_server.models import IXLanPrefix, NetworkIXLan
from peeringdb_server.inet import renumber_ipaddress


class Command(BaseCommand):
    help = "Renumber addresses, by providing the first three octects of a current ip4 address and the first three octets to change to."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="commit changes, otherwise run in pretend mode",
        )
        parser.add_argument(
            "--ixlan",
            default=0,
            help="ixlan id, if set only renumber matches in this specific ixlan",
        )
        parser.add_argument("ix", nargs="?", type=int)
        parser.add_argument("old", nargs="?", type=str)
        parser.add_argument("new", nargs="?", type=str)

    def log(self, msg):
        if not self.commit:
            self.stdout.write("[pretend] {}".format(msg))
        else:
            self.stdout.write(msg)

    @reversion.create_revision()
    def renumber_lans(self, old, new):
        """
        Renumber prefix and netixlan's that fall into that prefix
        """

        old_prefix = ipaddress.ip_network(old)
        new_prefix = ipaddress.ip_network(new)

        if old_prefix.version != new_prefix.version:
            self.log(
                "[error] {}".format(
                    "New prefix needs to be of same " "protocol as old prefix"
                )
            )

        prefixes = IXLanPrefix.objects.filter(
            prefix=old, ixlan__ix_id=self.ix, status="ok"
        )
        netixlans = NetworkIXLan.objects.filter(ixlan__ix_id=self.ix, status="ok")

        if self.ixlan:
            self.log("Only replacing in ixlan {}".format(self.ixlan.descriptive_name))
            prefixes = prefixes.filter(ixlan=ixlan)
            netixlans = netixlans.filter(ixlan=ixlan)

        for prefix in prefixes:
            self.log("Renumbering {} -> {}".format(prefix.descriptive_name, new_prefix))
            prefix.prefix = new_prefix
            prefix.full_clean()
            if self.commit:
                prefix.save()

        for netixlan in netixlans:
            old_addr = netixlan.ipaddr(old_prefix.version)

            try:
                new_addr = renumber_ipaddress(old_addr, old_prefix, new_prefix)
            except Exception as exc:
                self.log("[error] {}: {}".format(old_addr, exc))
                continue

            self.log(
                "Renumbering {} -> {}".format(
                    netixlan.descriptive_name_ipv(new_addr.version), new_addr
                )
            )

            if new_addr.version == 4:
                netixlan.ipaddr4 = new_addr
            else:
                netixlan.ipaddr6 = new_addr

            try:
                netixlan.full_clean()
            except ValidationError as exc:
                if not self.commit and str(exc).find("outside of prefix") > -1:
                    continue
                else:
                    self.log("[error] could not renumber {}: {}".format(old_addr, exc))
                    continue
            except Exception as exc:
                self.log("[error] could not renumber {}: {}".format(old_addr, exc))
                continue

            if self.commit:
                netixlan.save()

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.ixlan = int(options.get("ixlan", 0))
        self.ix = int(options.get("ix", 0))
        old = "{}".format(options.get("old"))
        new = "{}".format(options.get("new"))

        self.renumber_lans(old, new)
