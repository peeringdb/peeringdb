"""
Merge facilities.
"""

import re

import reversion
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import peeringdb_server.models as pdbm
from peeringdb_server.mail import mail_users_entity_merge


def soft_delete(fac, cmd):
    # overriding

    for k in fac._handleref.delete_cascade:
        q = getattr(fac, k).exclude(status="deleted")
        for c in q:
            if c not in cmd.moved:
                soft_delete(c, cmd)

    cmd.log("soft deleting %s" % fac)
    if cmd.commit:
        fac.status = "deleted"
        fac.save()


class Command(BaseCommand):
    help = "merge facilities"
    pretend = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the fac merge"
        )
        parser.add_argument("--target", help="target of the merge (facility id)")
        parser.add_argument("--ids", help="comma separated list of facility ids")
        parser.add_argument(
            "--match", help="all facs with matching names will be merged (regex)"
        )

    def log(self, msg):
        if not self.commit:
            self.stdout.write("%s [pretend]" % msg)
        else:
            self.stdout.write(msg)

    @reversion.create_revision()
    @transaction.atomic()
    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.moved = []

        self.target = options.get("target", 0)
        if not self.target:
            msg = "Target ID required (--target)"
            self.log(msg)
            raise CommandError(msg)

        self.match = options.get("match", None)
        self.ids = options.get("ids", "")

        facs = []
        moved = self.moved

        if self.match:
            if self.ids:
                msg = "ids and match are mutually exclusive"
                self.log(msg)
                raise CommandError(msg)

            self.log("Merging all facilities matching '%s'" % self.match)
            for fac in pdbm.Facility.objects.exclude(status="deleted"):
                if re.match(self.match, fac.name, re.IGNORECASE):
                    facs.append(fac)

        elif self.ids:
            self.ids = self.ids.split(",")
            self.log(
                "Merging facilities {} -> {}".format(", ".join(self.ids), self.target)
            )
            for fac in pdbm.Facility.objects.filter(id__in=self.ids):
                facs.append(fac)

        else:
            msg = "IDs or match is required"
            self.log(msg)
            raise CommandError(msg)

        self.target = pdbm.Facility.objects.get(id=self.target)

        if self.target.status == "deleted":
            self.target.status = "ok"
            if self.commit:
                self.target.save()

        for fac in facs:
            if fac.id == self.target.id:
                continue
            self.log("Merging %s (%d) .." % (fac, fac.id))
            for netfac in pdbm.NetworkFacility.objects.filter(facility=fac).exclude(
                status="deleted"
            ):
                netfac_other = pdbm.NetworkFacility.objects.filter(
                    facility=self.target, network_id=netfac.network_id
                )
                # we check if the target fac already has a netfac to the same network (that is currently undeleted), if it does we skip it
                if netfac_other.exclude(status="deleted").exists():
                    self.log(
                        "  - netfac %s : connection already exists at target, skipping."
                        % netfac
                    )
                    continue
                # if it exists but is currently delete, we simply undelete it
                elif netfac_other.exists():
                    netfac_other = netfac_other.first()
                    netfac_other.local_asn = netfac.local_asn
                    netfac_other.avail_sonet = netfac.avail_sonet
                    netfac_other.avail_ethernet = netfac.avail_ethernet
                    netfac_other.avail_atm = netfac.avail_atm
                    netfac_other.status = "ok"
                    self.log("  - netfac %s (undeleting and updating)" % netfac_other)
                    moved.append(netfac_other)
                    if self.commit:
                        netfac_other.save()
                # if it doesnt exist, we update the facility to the target facility and save
                else:
                    self.log("  - netfac %s" % netfac)
                    netfac.facility = self.target
                    moved.append(netfac)
                    if self.commit:
                        netfac.save()

            for ixfac in pdbm.InternetExchangeFacility.objects.filter(
                facility=fac
            ).exclude(status="deleted"):
                ixfac_other = pdbm.InternetExchangeFacility.objects.filter(
                    facility=self.target, ix=ixfac.ix
                )
                # we check if the target fac already has an ixfac to the same exchange (that is currently undeleted), if it does, we skip it
                if ixfac_other.exclude(status="deleted").exists():
                    self.log(
                        "  - ixfac %s : connection already exists at target, skipping."
                        % ixfac
                    )
                    continue
                # if it exists but is currently deleted, we undelete and copy
                elif ixfac_other.exists():
                    ixfac_other = ixfac_other.first()
                    ixfac_other.status = "ok"
                    moved.append(ixfac_other)
                    self.log("  - ixfac %s (undeleting and updating)" % ixfac_other)
                    if self.commit:
                        ixfac_other.save()
                # if it doesnt exist, we update the facility to the target facility and save
                else:
                    self.log("  - ixfac %s" % ixfac)
                    ixfac.facility = self.target
                    moved.append(ixfac)
                    if self.commit:
                        ixfac.save()

            soft_delete(fac, self)
            if self.commit:
                mail_users_entity_merge(
                    fac.org.admin_usergroup.user_set.all(),
                    self.target.org.admin_usergroup.user_set.all(),
                    fac,
                    self.target,
                )
