"""
Update the cache of the RDAP cache from IANA.
"""

from django.core.management.base import BaseCommand

from peeringdb_server.inet import RdapLookup


class Command(BaseCommand):
    help = "Updates the cache of the RDAP cache from IANA"

    def log(self, msg):
        print(msg)

    def handle(self, *args, **options):
        RdapLookup().write_bootstrap_data("asn")
