"""
Regen the api cache files.
"""

import datetime
import os
import shutil
import tempfile
import time
import traceback

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.management.base import BaseCommand
from rest_framework.test import APIRequestFactory

import peeringdb_server.models as pdbm
import peeringdb_server.rest as pdbr
from peeringdb_server.export_kmz import fac_export_kmz
from peeringdb_server.renderers import MetaJSONRenderer

MODELS = [
    pdbm.Organization,
    pdbm.Network,
    pdbm.InternetExchange,
    pdbm.Facility,
    pdbm.NetworkContact,
    pdbm.NetworkFacility,
    pdbm.IXLan,
    pdbm.IXLanPrefix,
    pdbm.NetworkIXLan,
]

VIEWSETS = {
    "org": pdbr.OrganizationViewSet,
    "net": pdbr.NetworkViewSet,
    "ix": pdbr.InternetExchangeViewSet,
    "fac": pdbr.FacilityViewSet,
    "carrier": pdbr.CarrierViewSet,
    "ixlan": pdbr.IXLanViewSet,
    "ixfac": pdbr.InternetExchangeFacilityViewSet,
    "ixpfx": pdbr.IXLanPrefixViewSet,
    "netfac": pdbr.NetworkFacilityViewSet,
    "netixlan": pdbr.NetworkIXLanViewSet,
    "poc": pdbr.NetworkContactViewSet,
    "carrierfac": pdbr.CarrierFacilityViewSet,
    "campus": pdbr.CampusViewSet,
}

MONODEPTH = {
    "carrierfac",
    "fac",
    "ixfac",
    "ixpfx",
    "netfac",
    "netixlan",
    "poc",
}

settings.DEBUG = False


class Command(BaseCommand):
    help = "Regen the api cache files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only", action="store", default=False, help="only run specified type"
        )
        parser.add_argument(
            "--gen-kmz",
            action="store_true",
            help="will generate kmz file in from the api-cache data",
        )
        parser.add_argument(
            "--gen-kmz-only",
            action="store_true",
            help="generate kmz file from api-cache data, output to output dir, and exit",
        )
        parser.add_argument(
            "--date",
            action="store",
            default=None,
            help="generate cache for objects create before or at the specified date (YYYYMMDD)",
        )
        parser.add_argument(
            "--depths",
            action="store",
            default="0,1,2,3",
            help="comma separated list of depths to generate",
        )
        parser.add_argument(
            "--output-dir",
            action="store",
            default=settings.API_CACHE_ROOT,
            help=f"output files to this directory (default: {settings.API_CACHE_ROOT})",
        )
        parser.add_argument(
            "--public-data",
            action="store_true",
            default=False,
            help="dump public data only as anonymous user",
        )

    def log(self, id, msg):
        if self.log_file:
            self.log_file.write(f"{id}: {msg}")
            self.log_file.flush()
        print(f"{id}: {msg}")

    def row_datetime(self, row, field="created"):
        return datetime.datetime.strptime(row.get(field), "%Y-%m-%dT%H:%M:%SZ")

    def handle(self, *args, **options):
        only = options.get("only", None)
        date = options.get("date", None)
        output_dir = options.get("output_dir")
        depths = list(map(int, options.get("depths").split(",")))

        if options.get("public_data"):
            request_user = AnonymousUser()

        else:
            request_user = pdbm.User.objects.filter(is_superuser=True).first()
            # temporary setting to indicate api-cache is being generated
            # this forced api responses to be generated without permission
            # checks
            settings.GENERATING_API_CACHE = True

        if options.get("gen_kmz_only"):
            print("Generating kmz file")
            fac_export_kmz(output_dir=output_dir)
            return

        if only:
            only = only.split(",")

        if date:
            last_updated = datetime.datetime.strptime(date, "%Y%m%d")
        else:
            last_updated = datetime.datetime.now()

        meta = {"generated": last_updated.timestamp()}
        self.log_file = open(settings.API_CACHE_LOG, "w+")
        self.log("info", f"Regnerating cache files to '{output_dir}'")
        self.log(
            "info",
            f"Caching depths {depths} for timestamp: {last_updated}",
        )
        request_factory = APIRequestFactory()
        renderer = MetaJSONRenderer()

        settings.API_DEPTH_ROW_LIMIT = 0

        # will be using RequestFactory to spawn requests to generate api-cache
        # CSRF_USE_SESSIONS needs to be disabled as these are not session-enabled requests

        settings.CSRF_USE_SESSIONS = False

        start_time = time.time()

        try:
            cache = {}
            # make a temp dir to create the cache files for an atomic swap
            tmpdir = tempfile.TemporaryDirectory()

            for tag, viewset in list(VIEWSETS.items()):
                if only and tag not in only:
                    continue

                for depth in depths:
                    if depth >= 1 and tag in MONODEPTH:
                        break

                    self.log(tag, f"generating depth {depth} to {tmpdir.name}...")
                    if depth:
                        request = request_factory.get(
                            f"/api/{tag}?depth={depth}&updated__lte={last_updated}Z&_ctf"
                        )
                    else:
                        request = request_factory.get(
                            f"/api/{tag}?updated__lte={last_updated}Z&_ctf"
                        )
                    request.user = request_user
                    vs = viewset.as_view({"get": "list"})
                    response = vs(request)

                    id = f"{tag}-{depth}"
                    file_name = os.path.join(tmpdir.name, f"{tag}-{depth}.json")
                    cache[id] = file_name
                    renderer.render(
                        response.data,
                        renderer_context={"response": response},
                        file_name=file_name,
                        default_meta=meta,
                    )

                    del response
                    del vs

            # move the tmp files to the cache dir
            for id, src_file in list(cache.items()):
                print(f"output_dir: {output_dir}")
                file_name = os.path.join(output_dir, "%s.json" % (id))
                shutil.move(src_file, file_name)

            # copy the monodepth files to the other depths
            for tag in MONODEPTH:
                if only and tag not in only:
                    continue

                for depth in [1, 2, 3]:
                    id = f"{tag}-{depth}"
                    src_file = os.path.join(output_dir, f"{tag}-0.json")
                    file_name = os.path.join(output_dir, f"{id}.json")
                    self.log("info", f"copying {src_file} to {file_name}")
                    shutil.copyfile(src_file, file_name)

        except Exception:
            self.log("error", traceback.format_exc())
            raise

        finally:
            tmpdir.cleanup()
            self.log_file.close()

        if options.get("gen_kmz"):
            print("Generating kmz file")
            # uses path here so it's using the newly generated cache files
            fac_export_kmz(path=output_dir)

        end_time = time.time()

        print("Finished after %.2f seconds" % (end_time - start_time))
