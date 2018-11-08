from django.core.management.base import BaseCommand
from peeringdb_server.mail import mail_users_entity_merge

import reversion
import peeringdb_server.models as pdbm


class Command(BaseCommand):
    args = "<from_ixp_id> <to_ixp_id>"
    help = "merge one ixp into another ixp"
    commit = False

    def add_arguments(self, parser):
        parser.add_argument('--target', help="merge into this ixp")
        parser.add_argument(
            '--ids', help=
            "merge these ixps (note: target ixp specified with the --target option)"
        )
        parser.add_argument('--commit', action='store_true',
                            help="commit changes")

    def log(self, msg):
        if not self.commit:
            print "%s [pretend]" % msg
        else:
            print msg

    @reversion.create_revision()
    def handle(self, *args, **options):

        args = list(args)

        self.commit = options.get("commit", False)

        ixp_from = pdbm.InternetExchange.objects.get(id=options.get("ids"))
        ixp_to = pdbm.InternetExchange.objects.get(id=options.get("target"))

        self.log("Merging %s into %s" % (ixp_from.name, ixp_to.name))

        ixlans_from = pdbm.IXLan.objects.filter(ix=ixp_from).exclude(
            status="deleted")
        for ixlan in ixlans_from:
            ixlan.ix = ixp_to
            self.log("Moving IXLAN %s to %s" % (ixlan.id, ixp_to.name))
            if self.commit:
                ixlan.save()
        self.log("Soft Deleting %s" % ixp_from.name)
        if self.commit:
            ixp_from.delete()
            mail_users_entity_merge(
                ixp_from.org.admin_usergroup.user_set.all(),
                ixp_to.org.admin_usergroup.user_set.all(), ixp_from, ixp_to)
