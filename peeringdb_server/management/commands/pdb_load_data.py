"""
Load initial data from another peeringdb instance using the REST API.
"""
from confu.schema import apply_defaults
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models.signals import pre_save
from django_peeringdb import models as djpdb_models

import peeringdb._fetch
from peeringdb import SUPPORTED_BACKENDS, resource
from peeringdb.client import Client
from peeringdb.config import ClientSchema
from peeringdb_server import models as pdb_models
from peeringdb_server import signals

_fetch_all_latest = peeringdb._fetch.Fetcher.fetch_all_latest


def fetch_all_latest(self, R, depth, params={}, since=None):
    """
    Some foreign keys differ in peeringdb_server from how they
    are exposed in the api, these need to be adjusted before
    returning the retrieved data to the sync process

    Affected fields

        `net_id` -> `network_id`
        `fac_id` -> `facility_id`

    We do this by monkey patching the `fetch_all_latest` function
    of the peeringdb `Fetcher` class

    Additionally we fix some common validation issues
    """

    result = _fetch_all_latest(self, R, depth, params=params, since=since)

    for row in result[0]:
        for k, v in list(row.items()):
            if k in ["latitude", "longitude"] and v:
                row[k] = f"{float(v):3.6f}"
            elif k == "fac_id":
                row["facility_id"] = v
                del row["fac_id"]
            elif k == "net_id":
                row["network_id"] = v
                del row["net_id"]

    return result


peeringdb._fetch.Fetcher.fetch_all_latest = fetch_all_latest


class Command(BaseCommand):
    help = "Load initial data from another peeringdb instance"

    def add_arguments(self, parser):
        parser.add_argument("--url", default="https://www.peeringdb.com/api/", type=str)

        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )

        parser.add_argument(
            "--no-cache", action="store_true", help="will not use the sync cache"
        )

    def handle(self, *args, **options):
        if settings.RELEASE_ENV != "dev" and not settings.TUTORIAL_MODE:
            self.stdout.write(
                "Command can only be run on dev instances and instances "
                "with tutorial mode enabled"
            )
            return

        if not options.get("commit"):
            self.stdout.write(
                "This will sync data from {url} to this instance, and will take "
                "roughly 20 minutes to complete on a fresh db. "
                "Run the command with `--commit` if you are sure you want "
                "to do this.".format(**options)
            )
            return

        # settings.USE_TZ = True
        db_settings = settings.DATABASES.get("default")

        sync_options = {
            "url": options.get("url"),
            "cache_url": settings.PEERINGDB_SYNC_CACHE_URL,
            "cache_dir": settings.PEERINGDB_SYNC_CACHE_DIR,
        }

        if options.get("no_cache"):
            sync_options["cache_url"] = ""

        # allow authentication for the sync (set as env vars)
        if settings.PEERINGDB_SYNC_API_KEY:
            sync_options["api_key"] = settings.PEERINGDB_SYNC_API_KEY
        elif settings.PEERINGDB_SYNC_USERNAME and settings.PEERINGDB_SYNC_PASSWORD:
            sync_options["user"] = settings.PEERINGDB_SYNC_USERNAME
            sync_options["password"] = settings.PEERINGDB_SYNC_PASSWORD
        else:
            print(
                "No authentication configured for sync, using anonymous access - this may cause rate limiting issues. Set PEERINGDB_SYNC_API_KEY or PEERINGDB_SYNC_USERNAME and PEERINGDB_SYNC_PASSWORD to configure authentication."
            )

        print("Syncing data from {url}".format(**sync_options))

        config = {
            "sync": sync_options,
            "orm": {
                "secret_key": settings.SECRET_KEY,
                "backend": "peeringdb_server",
                "migrate": False,
                "database": {k.lower(): v for k, v in db_settings.items()},
            },
        }

        apply_defaults(ClientSchema(), config)

        pre_save.disconnect(signals.addressmodel_save, sender=pdb_models.Facility)

        djpdb_models.all_models = [
            pdb_models.Organization,
            pdb_models.Facility,
            pdb_models.Network,
            pdb_models.InternetExchange,
            pdb_models.InternetExchangeFacility,
            pdb_models.IXLan,
            pdb_models.IXLanPrefix,
            pdb_models.NetworkContact,
            pdb_models.NetworkFacility,
            pdb_models.NetworkIXLan,
        ]

        SUPPORTED_BACKENDS["peeringdb_server"] = "peeringdb_server.client_adaptor"

        # disable validation of parent status during sync
        settings.DATA_QUALITY_VALIDATE_PARENT_STATUS = False

        # disable elasticsearch auto indexing if there are zero records
        if pdb_models.Organization.objects.count() == 0:
            settings.ELASTICSEARCH_DSL_AUTOSYNC = False
            settings.ELASTICSEARCH_DSL_AUTO_REFRESH = False

        client = Client(config)
        client.update_all(resource.all_resources(), since=None)
