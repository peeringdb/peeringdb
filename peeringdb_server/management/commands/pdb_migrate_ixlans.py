"""
DEPRECATED
Used during ixlan migrations for #21.
"""

import csv
import datetime

import reversion
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from peeringdb_server.models import (
    UTC,
    InternetExchange,
    InternetExchangeFacility,
    IXLan,
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    IXLanPrefix,
    NetworkIXLan,
)


class Command(BaseCommand):
    help = "migrate ixlans to one ixlan per ix (#21)"

    # foreign key relationships that need to have
    # ixlan_id migrated

    fk_relations = [
        NetworkIXLan,
        IXLanPrefix,
        IXLanIXFMemberImportAttempt,
        IXLanIXFMemberImportLog,
    ]

    # generic relationships that need to have
    # ixlan object_id migrated

    generic_relations = [
        reversion.models.Version,
        LogEntry,
    ]

    @property
    def tmp_id(self):
        """
        Provide a temporary ixlan id for case were migration
        needs to happen between two ixlan ids that collide with
        each other
        """

        if not hasattr(self, "_tmp_id"):
            self._tmp_id = 9000000
        self._tmp_id += 1
        return self._tmp_id

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="commit changes, otherwise run in pretend mode",
        )

        parser.add_argument(
            "--stop", help="stop after specified phase (1,2 or 3)", type=int, default=99
        )

    def log(self, msg):
        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options):
        self.stats = {
            "created_ok": 0,
            "created_deleted": 0,
            "created_pending": 0,
            "reparented_ok": 0,
            "reparented_deleted": 0,
            "reparented_pending": 0,
            "migrated_ok": 0,
            "migrated_deleted": 0,
            "migrated_pending": 0,
        }

        # migration report will be stored here

        self.report = {}

        self.commit = options.get("commit", False)
        self.stop = options.get("stop")

        # obtain the content type id for the ixlan model
        # we will use it update generic realtion ship ids
        # during id migration

        self.ixlan_content_type_id = ContentType.objects.get(
            app_label="peeringdb_server", model="ixlan"
        ).id

        # Phase 1: create ixlans for exchanges that don't have any

        self.create_missing_ixlans()

        # Phase 2: find exchanges with more than one ixlan and
        # reparent those ixlans to a new exchange

        if self.stop > 1:
            self.reparent_extra_ixlans()

        # Phase 3: Migrate ixlan ids to match their parent exchange
        # id

        if self.stop > 2:
            self.migrate_ixlan_ids()

        # Write migration report to `migrated_ixlans.csv`

        self.write_report()

        # Output migration stats

        stats = sorted(list(self.stats.items()), key=lambda x: x[0])

        for stat, count in stats:
            self.log(f"{stat}: {count}")

    def get_primary_ixlan(self, ix):
        """
        When an ix has multiple ixlans, try to obtain the primary ixlan
        that should stay with it

        - first check for matching status and id
        - then check for matching status and return first ordered by id
        - then return first ordered by id
        """
        ixlan = ix.ixlan_set.filter(status=ix.status, id=ix.id).first()

        if not ixlan:
            ixlan = ix.ixlan_set.filter(status=ix.status).order_by("id").first()
        if not ixlan:
            ixlan = ix.ixlan_set.all().order_by("id").first()

        return ixlan

    def create_missing_ixlans(self):
        """
        Create an ixlan object for exchanges that don't currently have
        an ixlan object
        """

        self.log("Phase 1: Creating ixlans for exchanges without them")

        for ix in InternetExchange.objects.all():
            if ix.ixlan_set.filter(status=ix.status).count() == 0:
                self.create_missing_ixlan(ix)

        self.log("Phase 1: Done")

    @reversion.create_revision()
    @transaction.atomic()
    def create_missing_ixlan(self, ix):
        """
        Creates an ixlan for an ix that doesn't have one
        """

        # ixlan for ix already exists, nothing else to do here

        if ix.ixlan:
            return

        reversion.set_comment("Created ixlan for ix (script, #21)")

        if self.commit:
            next_id = IXLan.objects.all().order_by("-id").first().id + 1
            IXLan.objects.create(ix=ix, status=ix.status, mtu=0, id=next_id)

            # on deleted exchanges
            # we also need to save the ix and the org, so they will
            # available in the api's incremental update response
            if ix.status == "deleted":
                ix.save()
                ix.org.save()

        self.log(f"Created [{ix.status}] ixlan for {ix.name} ({ix.id})")
        self.stats[f"created_{ix.status}"] += 1

    def reparent_extra_ixlans(self):
        """
        Finds exchanges with more than one ixlan under them and
        re-parents those extra ixlans under a new exchange
        """

        self.log("Phase 2: Reparenting extra ixlans to new exchanges")
        self.log(
            "This will reparent any ixlans for exchanges that have more "
            "than one ixlan to a new exchange"
        )

        for ix in InternetExchange.objects.all():
            if ix.ixlan_set.all().count() > 1:
                # we obtain the primary ixlan for the ix
                # then reparent all the other ixlans to a new
                # exchange

                primary_ixlan = self.get_primary_ixlan(ix)

                for ixlan in ix.ixlan_set.exclude(id=primary_ixlan.id):
                    self.reparent_ixlan(ixlan)

        self.log("Phase 2: Done")

    @reversion.create_revision()
    @transaction.atomic()
    def reparent_ixlan(self, ixlan):
        """
        Reparent an ixlan to a new exchange
        """

        ix = ixlan.ix

        reversion.set_comment("Reparented ixlan to new ix (script, #21)")

        # try to set a reasonable name for the new exchange
        # combining the original exchange name with the ixlan name
        #
        # if ixlan name is not set suffix ixlan{ixlan.id} instead
        #

        if ixlan.name:
            suffix = ixlan.name
            if InternetExchange.objects.filter(name=f"{ix.name} {suffix}").exists():
                suffix = f"{ixlan.name} ixlan{ixlan.id}"
        else:
            suffix = f"ixlan{ixlan.id}"

        # create new exchange

        new_ix = InternetExchange(
            name=f"{ix.name} {suffix}",
            org=ix.org,
            status=ixlan.status,
            city=ix.city,
            media=ix.media,
            region_continent=ix.region_continent,
            country=ix.country,
        )

        # we call save() with create_ixlan=False because we will
        # be moving an ixlans to the exchange instead

        if self.commit:
            new_ix.full_clean()
            new_ix.save(create_ixlan=False)

        # update migration report

        self.report_reparenting(ix, new_ix, ixlan)

        # copy netfac connections to the new exchange

        for ixfac in ix.ixfac_set_active:
            ixfac_copy = InternetExchangeFacility(
                ix=new_ix, facility=ixfac.facility, status=new_ix.status
            )
            if self.commit:
                ixfac_copy.save()

        # reparent the ixlan to the new ix

        ixlan.ix = new_ix
        if self.commit:
            ixlan.save()

        self.log(
            f"Reparented [{ixlan.status}] ixlan {ixlan.id} from ix {ix.name} ({ix.id}) to new ix {new_ix.name} ({new_ix.id})"
        )

        self.stats[f"reparented_{ixlan.status}"] += 1

    def migrate_ixlan_ids(self):
        """
        Migrates all ixlan ids so that the id matches that of the parent
        exchange
        """

        self.log("Phase 3: Migrate ixlan ids to match parent ix")

        ixlans = {ixlan.id: ixlan for ixlan in IXLan.objects.all()}

        loop = True

        while loop:
            loop = False

            try:
                for ixlan in ixlans.values():
                    if ixlan.id != ixlan.ix.id:
                        loop = True
                        self.migrate_ixlan_id(ixlan, ixlans)
            except RuntimeError:
                # ixlan `dict` size change, start over
                loop = True

        self.log("Phase 3: Done")

        self.post_migration_checks()

    @transaction.atomic()
    def migrate_ixlan_id(self, ixlan, ixlans, trigger=None, tmp_id=False):
        """
        Migrate an ixlan id so it matches the parent exchange id
        """

        # ids already match, nothind to do here

        if ixlan.id == ixlan.ix.id:
            return

        ix = ixlan.ix
        new_id = ix.id
        old_id = ixlan.id

        # indicates that we want to migrate this ixlan to a temporary
        # id for now, so we override new_id with a temporary id

        if tmp_id:
            new_id = self.tmp_id

        # targeted ixlan id currently claimed by another ixlan (that is not this ixlan)

        if ixlans.get(new_id) and ixlans.get(new_id) != ixlan:
            # migrate conflicting ixlan id

            if not trigger or trigger.id != new_id:
                self.migrate_ixlan_id(ixlans[new_id], ixlans, trigger=ixlan)
            else:
                # this ixlan id migration was triggered by the same ixlan
                # we are trying to resolve the conflict for, so to avoid
                # and endless loop we migrate to a temporary id

                self.migrate_ixlan_id(
                    ixlans[new_id], ixlans, trigger=ixlan, tmp_id=True
                )

        # migrate ixlan id (in memory)

        ixlan.id = new_id

        if not tmp_id:
            ixlans[new_id] = ixlan

        if ixlans.get(old_id) == ixlan:
            del ixlans[old_id]

        # if ixlan was migrated to a temporary id during conflict
        # resolving above: old_id needs to be updated to temporary id

        if hasattr(ixlan, "tmp_id"):
            old_id = ixlan.tmp_id
        elif tmp_id:
            ixlan.tmp_id = new_id

        # update migration report

        if not tmp_id:
            self.report_migration(old_id, new_id, ixlan)

        self.log(
            f"Migrated [{ixlan.status}] ixlan id {old_id} -> {new_id} - Exchange: {ix.name}"
        )

        # migrate ixlan id (database)

        self.migrate_ixlan_id_sql(old_id, ixlan.id)

        # create reversion revision for all updated entities

        if self.commit:
            # on deleted exchanges we also need to save the ix
            # and the org so it will be available in the api's incrememental
            # update response

            if ixlan.ix.status == "deleted":
                ixlan.ix.save()
                ixlan.ix.org.save()

            with reversion.create_revision():
                reversion.set_comment(
                    f"Migrated to new ixlan id: {old_id} -> {ixlan.id} (script, #21)"
                )
                reversion.add_to_revision(ixlan)
                for netixlan in ixlan.netixlan_set.all():
                    reversion.add_to_revision(netixlan)

                    # on deleted netixlan networks
                    # we also need to save the netixlan's network and org
                    # so they will be available in api's incremental update
                    # responses

                    if netixlan.network.status == "deleted":
                        netixlan.network.save()
                        netixlan.network.org.save()
                for ixpfx in ixlan.ixpfx_set.all():
                    reversion.add_to_revision(ixpfx)

        # if old_id still points to this ixlan in our ixlans collection
        # delete it so we know the old id is now available

        if ixlans.get(old_id) == ixlan:
            del ixlans[old_id]

        # update migration stats

        self.stats[f"migrated_{ixlan.status}"] += 1

    def migrate_ixlan_id_sql(self, old_id, new_id):
        """
        Migrate ixlan id so it matches its parent id

        This is called automatically during `migrate_ixlan_id` and should not be
        called manually

        This executes raw sql queries

        Foreign key checks will be temporarily disabled
        """

        now = datetime.datetime.now().replace(tzinfo=UTC())

        # query that updates the ixlan table

        queries = [
            (
                f"update {IXLan._meta.db_table} set id=%s, updated=%s where id=%s",
                [new_id, now, old_id],
            ),
        ]

        # queries that update fk relations

        for model in self.fk_relations:
            queries.append(
                (
                    f"update {model._meta.db_table} set ixlan_id=%s, updated=%s where ixlan_id=%s",
                    [new_id, now, old_id],
                )
            )

        # queries that updated generic relations

        for model in self.generic_relations:
            queries.append(
                (
                    f"update {model._meta.db_table} set object_id=%s where object_id=%s and content_type_id=%s",
                    [new_id, old_id, self.ixlan_content_type_id],
                )
            )

        if not self.commit:
            return

        # execute queries

        with connection.cursor() as cursor:
            # since we are updated primary keys that are referenced
            # by foreign key constraints we need to temporarily turn
            # OFF foreign key checks

            cursor.execute("set foreign_key_checks=0")
            for query in queries:
                cursor.execute(query[0], query[1])

            cursor.execute("set foreign_key_checks=1")

    def post_migration_checks(self):
        """
        Will check that foreign key relations are in tact

        Will check that all ixlan ids match their parent ix id

        Will check that each ix only has one ixlan
        """

        if not self.commit:
            return

        for model in self.fk_relations:
            self.log(f"ForeignKey sanity check: {model.__name__}")
            for obj in model.objects.all():
                assert obj.ixlan

        self.log("Checking that all ixlans now match ids with the parent exchange")
        for ixlan in IXLan.objects.all():
            assert ixlan.id == ixlan.ix.id

        self.log("Checking that all exchanges have one ixlan")
        for ix in InternetExchange.objects.all():
            assert ix.ixlan_set.count() == 1

    def report_update(self, key, **data):
        """
        Update the migration report

        Argument(s):

        - key (`int`): original ixlan id

        Keyword Argument(s):

        Will be passed to report dict for the specified ixlan

        - old_id (`int`): original ixlan id
        - old_ix (`InternetExchange`): ix at the beginning of migraiton
        - id (`int`): ixlan id now
        - ix (`InternetExchange`): ix now
        - reparented (`bool`): has the ixlan be reparented to a new ix
        - migrated (`bool`): has the ixlan been migrated to a new id
        """

        if key not in self.report:
            self.report[key] = data
        else:
            self.report[key].update(data)

    def report_reparenting(self, old_ix, new_ix, ixlan):
        self.report_update(
            ixlan.id,
            old_ix=old_ix,
            ix=new_ix,
            id=ixlan.id,
            reparented=True,
            status=ixlan.status,
        )

    def report_migration(self, old_id, new_id, ixlan):
        self.report_update(
            old_id,
            old_id=old_id,
            id=new_id,
            ix=ixlan.ix,
            migrated=True,
            status=ixlan.status,
        )

    def write_report(self):
        """
        Writes a csv report of migrated ixlans to `migrated_ixlans.csv`
        """

        self.log("Writing migration report to migrated_ixlans.csv")
        headers = [
            "old_id",
            "old_ix_id",
            "old_ix_name",
            "id",
            "ix_id",
            "ix_name",
            "reparented",
            "migrated",
        ]
        with open("migrated_ixlans.csv", "w+") as csvfile:
            csvwriter = csv.writer(csvfile, lineterminator="\n")
            csvwriter.writerow(headers)
            for ixlan_id, report in sorted(
                list(self.report.items()), key=lambda x: x[0]
            ):
                if report.get("status") == "deleted":
                    continue
                ix = report.get("ix")
                id = report.get("id")
                csvwriter.writerow(
                    [
                        report.get("old_id", ixlan_id),
                        report.get("old_ix", ix).id,
                        report.get("old_ix", ix).name,
                        id,
                        ix.id or "<pretend>",
                        ix.name,
                        report.get("reparented", False),
                        report.get("migrated", False),
                    ]
                )
