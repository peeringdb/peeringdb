import googlemaps
import reversion

from django.core.management.base import BaseCommand
from django.conf import settings

from peeringdb_server import models
from peeringdb_server.mock import Mock

from django.contrib.auth.models import Group


class Command(BaseCommand):

    help = "Will create test data. This will wipe all data locally, so use with caution. This command is NOT to be run on production or beta environments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

        parser.add_argument("--limit", type=int, default=2)

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write("[pretend] {}".format(msg))

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        self.limit = options.get("limit")

        if settings.RELEASE_ENV in ["prod", "beta"]:
            self.log("This command is only allowed to run on dev / test instances")
            return

        self.mock = Mock()
        self.generate()

    def wipe(self):
        if not self.commit:
            return

        # we wipe all data by simply deleting all organizations
        # since everything in the end is a child of an organization
        # it will wipe all peeringdb data
        models.Organization.objects.all().delete()

        # delete all org specific user groups
        Group.objects.filter(name__startswith="org.").delete()

    @reversion.create_revision()
    def generate(self):
        self.entities = dict([(k, []) for k in list(models.REFTAG_MAP.keys())])
        queue = [
            "org",
            "net",
            "ix",
            "fac",
            "ixpfx",
            "ixfac",
            "netixlan",
            "netfac",
            "poc",
        ]

        self.log("Wiping current data ...")
        self.wipe()
        self.log(
            "Making {} of each - Use the --limit option to increase or decrease (5 max)".format(
                self.limit
            )
        )

        if not self.commit:
            return

        for i in range(0, self.limit):
            for reftag in queue:
                params = {}

                # create apropriate relations to previously
                # create objects
                if reftag in ["ixpfx", "netixlan"]:
                    params.update(ixlan=self.entities["ixlan"][i])
                if reftag in ["poc", "netfac", "netixlan"]:
                    params.update(network=self.entities["net"][i])
                if reftag in ["netfac", "ixfac"]:
                    params.update(facility=self.entities["fac"][i])
                if reftag in ["ixlan", "ixfac"]:
                    params.update(ix=self.entities["ix"][i])
                if reftag in ["ix", "net", "fac"]:
                    params.update(org=self.entities["org"][i])

                # create object
                entity = self.mock.create(reftag, **params)
                self.entities[reftag].append(entity)

                # for prefixes we also want to create one for the IPv6
                # protocol
                if reftag == "ixpfx":
                    params.update(protocol="IPv6")
                    entity = self.mock.create(reftag, **params)
                    self.entities[reftag].append(entity)
                elif reftag == "ix":
                    self.entities["ixlan"].append(entity.ixlan)

        self.entities["net"].append(self.mock.create("net"))
        self.entities["ix"].append(self.mock.create("ix"))
        self.entities["fac"].append(self.mock.create("fac"))

        self.entities["org"].append(self.mock.create("org"))

        for reftag, entities in list(self.entities.items()):
            self.log("Created {} {}s".format(len(entities), reftag))
