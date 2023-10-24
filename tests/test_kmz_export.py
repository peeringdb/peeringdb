import os

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client


@pytest.mark.django_db
def test_kmz_generation_and_download():
    """
    This test function tests the generation of the kmz file and then its download.
    It first generates some test data and runs the cache gen command with the --gen-kmz param.
    Then it checks if the kmz file was created.
    Finally, it uses a Django test client to send a GET request to the kmz download endpoint and checks the response.
    """

    # Generate some test data and run the cache gen command with the --gen-kmz param
    call_command("pdb_generate_test_data", limit=2, commit=True)
    call_command("pdb_api_cache", gen_kmz=True)
    settings.GENERATING_API_CACHE = False

    # Check if the kmz file was created
    assert os.path.exists(settings.KMZ_EXPORT_FILE)

    # Use a Django test client to send a GET request to the kmz download endpoint
    client = Client()
    response = client.get("/export/kmz/")

    # Check the response
    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.google-earth.kmz"
    assert (
        response["Content-Disposition"]
        == f'attachment; filename="{os.path.basename(settings.KMZ_EXPORT_FILE)}"'
    )
