"""
Command line whois.
"""

import logging

from django.contrib.auth.models import AnonymousUser
from django_handleref import util
from peeringdb.whois import WhoisFormat

from peeringdb_server import models, serializers
from peeringdb_server.util import APIPermissionsApplicator

from ._db_command import DBCommand


class Command(DBCommand):
    args = "<customer id>"
    help = "command line whois"

    def add_arguments(self, parser):
        parser.add_argument("ref", nargs="?", type=str)

    def handle(self, *args, **options):
        log = logging.getLogger("pdb.script.whois")

        # FIXME - ignore multiple args for now
        args = options.get("ref")

        try:
            (ref_tag, pk) = util.split_ref(args)
        except ValueError:
            log.error("Unknown query type '%s'" % (args))
            return
            # TODO
            # raise CommandError("unk query")

        model = None

        # TODO needs the client whois typ resolver in a better place for reuse
        #      probably easiest to just map reftag to pk name
        if ref_tag in models.REFTAG_MAP:
            model = models.REFTAG_MAP[ref_tag]
            Serializer = serializers.REFTAG_MAP[ref_tag]
            obj = Serializer.prefetch_related(model.objects, None, depth=2).get(pk=pk)

        elif ref_tag == "as":
            model = models.REFTAG_MAP["net"]
            Serializer = serializers.REFTAG_MAP["net"]
            obj = Serializer.prefetch_related(model.objects, None, depth=2).get(asn=pk)

        #            data = cls(obj).data

        # TODO doesn't work on client
        # elif ref_tag == 'ixnets':

        if not model:
            msg = f"Unknown ref tag: {ref_tag}"
            log.error("Unknown ref tag: %s" % ref_tag)
            raise ValueError(msg)

        data = Serializer(obj, context={"user": AnonymousUser()}).data
        applicator = APIPermissionsApplicator(AnonymousUser())
        data = applicator.apply(data)
        fmt = WhoisFormat()
        fmt.print(obj._handleref.tag, data)
