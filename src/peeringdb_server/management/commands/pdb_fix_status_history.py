"""
Fix object status in reversion archived data (#558).
"""

import json

import reversion
from django.core.management.base import BaseCommand
from django.db import transaction

from peeringdb_server.models import REFTAG_MAP


class Command(BaseCommand):
    help = "Fix object status in reversion archived data (#558)"

    tags = ["fac", "net", "ix"]

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="commit changes, otherwise run in pretend mode",
        )

    def log(self, msg):
        if not self.commit:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        for tag in self.tags:
            self.process(tag)

    def process(self, tag):
        """
        check model for instances where current object status
        diverges from the status in the most recent archived
        version of the object.

        Then fix those instances by creating a new revision
        with the correct status
        """

        model = REFTAG_MAP[tag]
        self.log(f"Processing {model.__name__} ...")

        # no data is getting updated but object versions will be bumped
        # by one because of the revision fix - in order to not spam "recently updated"
        # lists with hundreds of empty updates we take out the automatic
        # update for the `updated` field

        model._meta.get_field("updated").auto_now = False

        fixed = 0
        for entity in model.objects.filter(status="ok"):
            versions = reversion.models.Version.objects.get_for_object(entity)
            version = versions.order_by("-revision_id").first()

            if not version:
                continue

            # see what status is stored in the most recent archived version

            archived_data = json.loads(version.serialized_data)
            archived_status = archived_data[0].get("fields").get("status")

            # if archived status is different than current object status
            # create a new revision for the correct status

            if archived_status != entity.status:
                fixed += 1
                self.log(
                    f"Fixing {tag}-{entity.id} {version.id} archived status: {entity.status}"
                )
                if self.commit:
                    self.process_entity(entity, version)

        self.log(f"{fixed} revisions fixed for {model.__name__}")

    @reversion.create_revision()
    @transaction.atomic()
    def process_entity(self, entity, most_recent_version):
        # force revision date to be same as that of the most recent version
        # so status change is archived at the correct date

        reversion.set_date_created(most_recent_version.revision.date_created)

        # note in comment why this revision was created

        reversion.set_comment("Fixing status in object archives (script, #558)")

        # add entity to revision

        reversion.add_to_revision(entity)
