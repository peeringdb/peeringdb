"""
Test peeringdb data export views
"""

import datetime
import difflib
import json
import os
import re
import tempfile

import pytest
import reversion
from django.core.management import call_command
from django.test import Client

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    IXLan,
    Network,
    NetworkFacility,
    NetworkIXLan,
    Organization,
)

from .util import ClientCase


class AdvancedSearchExportTest(ClientCase):
    """
    Tests advanced search result exports
    """

    @classmethod
    def setUpTestData(cls):
        ClientCase.setUpTestData()

        entity_count = list(range(1, 4))

        countries = ["US", "FI", ""]

        # create orgs

        # create exchanges
        cls.org = [
            Organization.objects.create(
                name=f"Organization {i}",
                country=countries[i - 1],
                city=f"City {i}",
                status="ok",
            )
            for i in entity_count
        ]

        # create networks
        cls.net = [
            Network.objects.create(
                name=f"Network {i}",
                status="ok",
                aka=f"AKA {i}",
                policy_general="Open",
                info_traffic="0-20Mbps",
                info_types=["Content"],
                asn=i,
                org=cls.org[i - 1],
            )
            for i in entity_count
        ]

        # create exchanges
        cls.ix = [
            InternetExchange.objects.create(
                name=f"Exchange {i}",
                media="Ethernet",
                country=countries[i - 1],
                city=f"City {i}",
                status="ok",
                org=cls.org[i - 1],
            )
            for i in entity_count
        ]

        # create facilities
        cls.fac = [
            Facility.objects.create(
                name=f"Facility {i}",
                status="ok",
                city=f"City {i}",
                clli=f"CLLI{i}",
                state=f"State {i}",
                npanxx=f"{i}-{i}",
                country=countries[i - 1],
                zipcode=i,
                org=cls.org[i - 1],
                latitude=-6.591422,
                longitude=106.786656,
            )
            for i in entity_count
        ]

        # create network facility relationships
        with reversion.create_revision():
            cls.netfac = [
                NetworkFacility.objects.create(
                    network=cls.net[i - 1], facility=cls.fac[i - 1], status="ok"
                )
                for i in entity_count
            ]

        # create ixlans
        with reversion.create_revision():
            cls.ixlan = [ix.ixlan for ix in cls.ix]

        # create netixlans
        with reversion.create_revision():
            cls.netixlan = [
                NetworkIXLan.objects.create(
                    ixlan=cls.ixlan[i - 1],
                    network=cls.net[i - 1],
                    asn=i,
                    speed=0,
                    status="ok",
                )
                for i in entity_count
            ]

        call_command("rebuild_index", "--noinput")

    def expected_data(self, tag, fmt):
        path = os.path.join(
            os.path.dirname(__file__),
            "data",
            "export",
            "advancedsearch",
            f"{tag}.{fmt}",
        )
        with open(path) as fh:
            data = fh.read().rstrip()
        return data

    def test_export_net_json(self):
        """test json export of network search"""
        client = Client()
        response = client.get("/export/advanced-search/net/json?name_search=Network")
        assert json.loads(response.content) == json.loads(
            self.expected_data("net", "json")
        )

    def test_export_net_json_pretty(self):
        """test pretty json export of network search"""
        client = Client()
        response = client.get(
            "/export/advanced-search/net/json-pretty?name_search=Network"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("net", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    def test_export_net_csv(self):
        """test csv export of network search"""
        client = Client()
        response = client.get("/export/advanced-search/net/csv?name_search=Network")
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("net", "csv")

    def test_export_net_csv_with_api_cache(self):
        """test csv export of net search while api-cache exists"""

        call_command("pdb_api_cache", date=datetime.datetime.now().strftime("%Y%m%d"))

        self.test_export_net_csv()

    def test_export_fac_json(self):
        """test json export of facility search"""
        client = Client()
        response = client.get("/export/advanced-search/fac/json?name_search=Facility")
        assert json.loads(response.content) == json.loads(
            self.expected_data("fac", "json")
        )

    def test_export_fac_json_pretty(self):
        """test pretty json export of facility search"""
        client = Client()
        response = client.get(
            "/export/advanced-search/fac/json-pretty?name_search=Facility"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("fac", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    def test_export_fac_csv(self):
        """test csv export of facility search"""
        client = Client()
        response = client.get("/export/advanced-search/fac/csv?name_search=Facility")

        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("fac", "csv")

    def test_export_fac_csv_with_api_cache(self):
        """test csv export of facility search while api-cache exists"""

        call_command("pdb_api_cache", date=datetime.datetime.now().strftime("%Y%m%d"))

        self.test_export_fac_csv()

    def test_export_ix_json(self):
        """test json export of exchange search"""
        client = Client()
        response = client.get("/export/advanced-search/ix/json?name_search=Exchange")
        self.assertEqual(
            json.loads(response.content), json.loads(self.expected_data("ix", "json"))
        )

    def test_export_ix_json_pretty(self):
        """test pretty json export of exchange search"""
        client = Client()
        response = client.get(
            "/export/advanced-search/ix/json-pretty?name_search=Exchange"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("ix", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    def test_export_ix_csv(self):
        """test csv export of exchange search"""
        client = Client()
        response = client.get("/export/advanced-search/ix/csv?name_search=Exchange")
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("ix", "csv")

    def test_export_ix_csv_with_api_cache(self):
        """test csv export of ix search while api-cache exists"""

        call_command("pdb_api_cache", date=datetime.datetime.now().strftime("%Y%m%d"))

        self.test_export_ix_csv()

    def test_export_org_json(self):
        """test json export of organization search"""
        client = Client()
        response = client.get(
            "/export/advanced-search/org/json?name_search=Organization"
        )
        self.assertEqual(
            json.loads(response.content), json.loads(self.expected_data("org", "json"))
        )

    def test_export_org_json_pretty(self):
        """test pretty json export of organization search"""
        client = Client()
        response = client.get(
            "/export/advanced-search/org/json-pretty?name_search=Organization"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("org", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    def test_export_org_csv(self):
        """test csv export of organization search"""
        client = Client()
        response = client.get(
            "/export/advanced-search/org/csv?name_search=Organization"
        )
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("org", "csv")

    def test_export_org_csv_with_api_cache(self):
        """test csv export of org search while api-cache exists"""

        call_command("pdb_api_cache", date=datetime.datetime.now().strftime("%Y%m%d"))

        self.test_export_org_csv()

    def test_export_fac_kmz(self):
        """test kmz export of facility search"""

        with tempfile.TemporaryDirectory() as output_dir:
            output_file = os.path.join(output_dir, "advanced_search_export.kmz")

            # Use a Django test client to send a GET request to the export kmz download endpoint
            client = Client()
            response = client.get(
                "/export/advanced-search/fac/kmz?name_search=Facility"
            )

            # Check the response
            assert response.status_code == 200
            assert response["Content-Type"] == "application/vnd.google-earth.kmz"

            assert (
                response["Content-Disposition"]
                == f'attachment; filename="{os.path.basename(output_file)}"'
            )
