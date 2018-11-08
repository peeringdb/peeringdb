from django.core.management.base import BaseCommand
from peeringdb_server.models import IXLanPrefix, NetworkIXLan
import reversion


class Command(BaseCommand):
    help = "Renumber addresses, by providing the first three octects of a current ip4 address and the first three octets to change to."

    def add_arguments(self, parser):
        parser.add_argument(
            '--commit', action='store_true',
            help="commit changes, otherwise run in pretend mode")
        parser.add_argument(
            '--ix', default=0, help=
            "exchange id, if set only renumber matches in ixlans owned by the specified exchange"
        )
        parser.add_argument(
            '--ixlan', default=0,
            help="ixlan id, if set only renumber matches in this specific ixlan"
        )
        parser.add_argument("old", nargs="+", type=str)
        parser.add_argument("new", nargs="+", type=str)

    def log(self, id, msg):
        if not self.commit:
            self.stdout.write("[pretend] %s: %s" % (id, msg))
        else:
            self.stdout.write("%s: %s" % (id, msg))

    @reversion.create_revision()
    def renumber_lans(self, old, new):
        """
        Renumber ixlan and netixlan ip4 addresses, changing the first
        three octets but keep the final octact in tact

        193.232.245.* -> 195.208.209.*
        """

        if len(old.split(".")) != 3:
            raise ValueError(
                "'Old Prefix' needs to be the first three octets of a IPv4 ip address - such as 195.232.245"
            )

        if len(new.split(".")) != 3:
            raise ValueError(
                "'New Prefix' needs to be the first three octets of a IPv4 ip address - such as 195.232.245"
            )

        if self.ixlan:
            self.log("init", "Renumbering only in ixlan #ID:{}".format(
                self.ixlan))
            prefixes = IXLanPrefix.objects.filter(
                protocol="IPv4", prefix__startswith="%s." % old,
                ixlan_id=self.ixlan)
            netixlans = NetworkIXLan.objects.filter(
                ipaddr4__startswith="%s." % old, ixlan_id=self.ixlan)
        elif self.ix:
            self.log("init", "Renumbering only in exchange #ID:{}".format(
                self.ix))
            prefixes = IXLanPrefix.objects.filter(
                protocol="IPv4", prefix__startswith="%s." % old,
                ixlan__ix_id=self.ix)
            netixlans = NetworkIXLan.objects.filter(
                ipaddr4__startswith="%s." % old, ixlan__ix_id=self.ix)
        else:
            prefixes = IXLanPrefix.objects.filter(
                protocol="IPv4", prefix__startswith="%s." % old)
            netixlans = NetworkIXLan.objects.filter(
                ipaddr4__startswith="%s." % old)

        for prefix in prefixes:
            new_prefix = unicode(".".join(
                new.split(".")[:3] + [str(prefix.prefix).split(".")[-1]]))
            self.log(IXLanPrefix._handleref.tag, "%s <IXLAN:%d> %s -> %s" %
                     (prefix.ixlan.ix, prefix.ixlan_id, prefix.prefix,
                      new_prefix))

            if self.commit:
                prefix.prefix = new_prefix
                prefix.save()

        for netixlan in netixlans:
            new_addr = unicode(".".join(
                new.split(".")[:3] + [str(netixlan.ipaddr4).split(".")[-1]]))

            other = NetworkIXLan.objects.filter(ipaddr4=new_addr, status="ok")

            if other.exists():
                other = other.first()
                self.log(
                    NetworkIXLan._handleref.tag,
                    "[error] {} (IXLAN:{}) {} -> {}: Address {} already exists in IXLAN:{} under IX:{}".
                    format(netixlan.ixlan.ix, netixlan.ixlan_id,
                           netixlan.ipaddr4, new_addr, new_addr,
                           other.ixlan_id, other.ixlan.ix_id))
                continue
            else:
                self.log(
                    NetworkIXLan._handleref.tag, "%s (IXLAN:%d) %s -> %s" %
                    (netixlan.ixlan.ix, netixlan.ixlan_id, netixlan.ipaddr4,
                     new_addr))

            if self.commit:
                netixlan.ipaddr4 = new_addr
                netixlan.save()

    def p_usage(self):
        print "USAGE: <old> <new> [options]"
        print "EXAMPLE: pdb_renumber_lans 193.232.245 195.208.209"

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.ixlan = int(options.get("ixlan", 0))
        self.ix = int(options.get("ix", 0))
        old = options.get("old")[0]
        new = options.get("new")[0]

        if not old or not new:
            return self.p_usage()
        self.renumber_lans(old, new)
