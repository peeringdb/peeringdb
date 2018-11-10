from django.core.management.base import BaseCommand
import os
import traceback
import peeringdb_server.models as pdbm
import peeringdb_server.rest as pdbr
import datetime
import time
from peeringdb_server.renderers import MetaJSONRenderer
from django.conf import settings
from optparse import make_option
from rest_framework.test import APIRequestFactory

MODELS = [
    pdbm.Organization, pdbm.Network, pdbm.InternetExchange, pdbm.Facility,
    pdbm.NetworkContact, pdbm.NetworkFacility, pdbm.IXLan, pdbm.IXLanPrefix,
    pdbm.NetworkIXLan
]

VIEWSETS = {
    "org": pdbr.OrganizationViewSet,
    "net": pdbr.NetworkViewSet,
    "ix": pdbr.InternetExchangeViewSet,
    "fac": pdbr.FacilityViewSet,
    "ixlan": pdbr.IXLanViewSet,
    "ixfac": pdbr.InternetExchangeFacilityViewSet,
    "ixpfx": pdbr.IXLanPrefixViewSet,
    "netfac": pdbr.NetworkFacilityViewSet,
    "netixlan": pdbr.NetworkIXLanViewSet,
    "poc": pdbr.NetworkContactViewSet
}

settings.DEBUG = False


class Command(BaseCommand):
    help = "Regen the api cache files"

    def add_arguments(self, parser):
        parser.add_argument("--only", action="store", default=False,
                            help="only run specified type")
        parser.add_argument(
            "--date", action="store", default=None, help=
            "generate cache for objects create before or at the specified date (YYYYMMDD)"
        )

    def log(self, id, msg):
        if self.log_file:
            self.log_file.write("%s: %s" % (id, msg))
            self.log_file.flush()
        print "%s: %s" % (id, msg)

    def row_datetime(self, row, field="created"):
        return datetime.datetime.strptime(row.get(field), "%Y-%m-%dT%H:%M:%SZ")

    def handle(self, *args, **options):
        only = options.get('only', None)
        date = options.get('date', None)

        if only:
            only = only.split(",")

        if date:
            dt = datetime.datetime.strptime(date, "%Y%m%d")
        else:
            dt = datetime.datetime.now()
        dtstr = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.log_file = open(settings.API_CACHE_LOG, "w+")
        self.log("info",
                 "Regnerating cache files to '%s'" % settings.API_CACHE_ROOT)
        self.log("info", "Caching data for timestamp: %s" % dtstr)
        rf = APIRequestFactory()
        renderer = MetaJSONRenderer()

        t = time.time()

        su = pdbm.User.objects.filter(is_superuser=True).first()

        settings.API_DEPTH_ROW_LIMIT = 0

        try:
            cache = {}

            for tag, viewset in VIEWSETS.items():
                if only and tag not in only:
                    continue

                for depth in [0, 1, 2, 3]:
                    self.log(tag, "generating depth %d" % depth)
                    if depth:
                        req = rf.get('/api/%s?depth=%d&updated__lte=%s&_ctf' %
                                     (tag, depth, dtstr))
                    else:
                        req = rf.get('/api/%s?updated__lte=%s&_ctf' % (tag,
                                                                       dtstr))
                    req.user = su
                    vs = viewset.as_view({'get': 'list'})
                    res = vs(req)
                    cache["%s-%s" % (tag, depth)] = renderer.render(
                        res.data, renderer_context={
                            "response": res
                        })
                    del res
                    del vs

            for id, data in cache.items():
                self.log(id, "saving file")
                with open(
                        os.path.join(settings.API_CACHE_ROOT,
                                     "%s.json" % (id)), "w+") as output:
                    output.write(data)

        except Exception:
            self.log("error", traceback.format_exc())
            raise

        t2 = time.time()

        print "Finished after %.2f seconds" % (t2 - t)
