"""
Django management command
Will fetch api cache files from PEERINGDB_SYNC_CACHE_URL to API_CACHE_ROOT
"""

import json
import os
import sys
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from peeringdb_server.models import REFTAG_MAP


class Command(BaseCommand):
    help = "Fetch api cache files from PEERINGDB_SYNC_CACHE_URL to API_CACHE_ROOT"

    def handle(self, *args, **options):
        """
        Fetch api cache files from PEERINGDB_SYNC_CACHE_URL to API_CACHE_ROOT
        """
        tags = REFTAG_MAP.keys()

        for tag in tags:
            url = urljoin(f"{settings.PEERINGDB_SYNC_CACHE_URL}/", tag) + "-0.json"
            response = requests.get(url)

            # Make sure the request was successful
            if response.status_code == 200:
                data = response.json()

                # store the json data to a file in data/cache directory
                cache_file_path = os.path.join(settings.API_CACHE_ROOT, f"{tag}-0.json")
                with open(cache_file_path, "w") as file:
                    json.dump(data, file, indent=4)
                self.stdout.write(f"Successfully fetched data for {tag} from {url}")
            else:
                self.stdout.write(
                    f"Error fetching data for {tag} from {url}: HTTP {response.status_code}"
                )
                sys.exit(1)
