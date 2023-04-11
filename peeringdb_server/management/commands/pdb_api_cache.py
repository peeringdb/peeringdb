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
from django.core.management.base import BaseCommand
from rest_framework.test import APIRequestFactory

import peeringdb_server.models as pdbm
import peeringdb_server.rest as pdbr
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
        depths = list(map(int, options.get("depths").split(",")))

        # temporary setting to indicate api-cache is being generated
        # this forced api responses to be generated without permission
        # checks
        settings.GENERATING_API_CACHE = True

        if only:
            only = only.split(",")

        if date:
            dt = datetime.datetime.strptime(date, "%Y%m%d")
        else:
            dt = datetime.datetime.now()
        dtstr = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.log_file = open(settings.API_CACHE_LOG, "w+")
        self.log("info", "Regnerating cache files to '%s'" % settings.API_CACHE_ROOT)
        self.log(
            "info",
            f"Caching depths {str(depths)} for timestamp: {str(dtstr)}",
        )
        rf = APIRequestFactory()
        renderer = MetaJSONRenderer()

        t = time.time()

        su = pdbm.User.objects.filter(is_superuser=True).first()

        settings.API_DEPTH_ROW_LIMIT = 0

        # will be using RequestFactory to spawn requests to generate api-cache
        # CSRF_USE_SESSIONS needs to be disabled as these are not session-enabled requests

        settings.CSRF_USE_SESSIONS = False

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

                    self.log(tag, "generating depth %d" % depth)
                    if depth:
                        req = rf.get(
                            "/api/%s?depth=%d&updated__lte=%s&_ctf"
                            % (tag, depth, dtstr)
                        )
                    else:
                        req = rf.get(f"/api/{tag}?updated__lte={dtstr}&_ctf")
                    req.user = su
                    vs = viewset.as_view({"get": "list"})
                    res = vs(req)

                    id = f"{tag}-{depth}"
                    file_name = os.path.join(tmpdir.name, f"{tag}-{depth}.json")
                    cache[id] = file_name
                    renderer.render(
                        res.data,
                        renderer_context={"response": res},
                        file_name=file_name,
                    )

                    del res
                    del vs

            # move the tmp files to the cache dir
            for id, src_file in list(cache.items()):
                file_name = os.path.join(settings.API_CACHE_ROOT, "%s.json" % (id))
                shutil.move(src_file, file_name)

            # copy the monodepth files to the other depths
            for tag in MONODEPTH:
                if only and tag not in only:
                    continue

                for depth in [1, 2, 3]:
                    id = f"{tag}-{depth}"
                    src_file = os.path.join(settings.API_CACHE_ROOT, f"{tag}-0.json")
                    file_name = os.path.join(settings.API_CACHE_ROOT, f"{id}.json")
                    self.log("info", f"copying {src_file} to {file_name}")
                    shutil.copyfile(src_file, file_name)

        except Exception:
            self.log("error", traceback.format_exc())
            raise

        finally:
            tmpdir.cleanup()
            self.log_file.close()

        t2 = time.time()

        print("Finished after %.2f seconds" % (t2 - t))
