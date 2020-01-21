"""
Test peeringdb data export views
"""
import os
import pytest
import json
import difflib
import re

from django.test import Client

from .util import ClientCase

from peeringdb_server.models import (
    Organization,
    Network,
    InternetExchange,
    Facility,
    NetworkFacility,
    NetworkIXLan,
    IXLan,
)


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
                name="Organization {}".format(i),
                country=countries[i - 1],
                city="City {}".format(i),
                status="ok",
            )
            for i in entity_count
        ]

        # create networks
        cls.net = [
            Network.objects.create(
                name="Network {}".format(i),
                status="ok",
                aka="AKA {}".format(i),
                policy_general="Open",
                info_traffic="0-20 Mbps",
                asn=i,
                org=cls.org[i - 1],
            )
            for i in entity_count
        ]

        # create exchanges
        cls.ix = [
            InternetExchange.objects.create(
                name="Exchange {}".format(i),
                media="Ethernet",
                country=countries[i - 1],
                city="City {}".format(i),
                status="ok",
                org=cls.org[i - 1],
            )
            for i in entity_count
        ]

        # create facilities
        cls.fac = [
            Facility.objects.create(
                name="Facility {}".format(i),
                status="ok",
                city="City {}".format(i),
                clli="CLLI{}".format(i),
                state="State {}".format(i),
                npanxx="{}-{}".format(i, i),
                country=countries[i - 1],
                zipcode=i,
                org=cls.org[i - 1],
            )
            for i in entity_count
        ]

        # create network facility relationships
        cls.netfac = [
            NetworkFacility.objects.create(
                network=cls.net[i - 1], facility=cls.fac[i - 1], status="ok"
            )
            for i in entity_count
        ]

        # create ixlans
        cls.ixlan = [
            IXLan.objects.create(ix=cls.ix[i - 1], status="ok") for i in entity_count
        ]

        # create netixlans
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

    def expected_data(self, tag, fmt):
        path = os.path.join(
            os.path.dirname(__file__),
            "data",
            "export",
            "advancedsearch",
            "{}.{}".format(tag, fmt),
        )
        with open(path, "r") as fh:
            data = fh.read().rstrip()
        return data

    def test_export_net_json(self):
        """ test json export of network search """
        client = Client()
        response = client.get("/export/advanced-search/net/json?name_search=Network")
        assert json.loads(response.content) == json.loads(
            self.expected_data("net", "json")
        )

    def test_export_net_json_pretty(self):
        """ test pretty json export of network search """
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
        """ test csv export of network search """
        client = Client()
        response = client.get("/export/advanced-search/net/csv?name_search=Network")
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("net", "csv")

    def test_export_fac_json(self):
        """ test json export of facility search """
        client = Client()
        response = client.get(
            "/export/advanced-search/fac/json?name__contains=Facility"
        )
        assert json.loads(response.content) == json.loads(
            self.expected_data("fac", "json")
        )

    def test_export_fac_json_pretty(self):
        """ test pretty json export of facility search """
        client = Client()
        response = client.get(
            "/export/advanced-search/fac/json-pretty?name__contains=Facility"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("fac", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    def test_export_fac_csv(self):
        """ test csv export of facility search """
        client = Client()
        response = client.get("/export/advanced-search/fac/csv?name__contains=Facility")

        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("fac", "csv")

    def test_export_ix_json(self):
        """ test json export of exchange search """
        client = Client()
        response = client.get("/export/advanced-search/ix/json?name__contains=Exchange")
        self.assertEqual(
            json.loads(response.content), json.loads(self.expected_data("ix", "json"))
        )

    def test_export_ix_json_pretty(self):
        """ test pretty json export of exchange search """
        client = Client()
        response = client.get(
            "/export/advanced-search/ix/json-pretty?name__contains=Exchange"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("ix", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    def test_export_ix_csv(self):
        """ test csv export of exchange search """
        client = Client()
        response = client.get("/export/advanced-search/ix/csv?name__contains=Exchange")
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("ix", "csv")

    def test_export_org_json(self):
        """ test json export of organization search """
        client = Client()
        response = client.get(
            "/export/advanced-search/org/json?name_search=Organization"
        )
        self.assertEqual(
            json.loads(response.content), json.loads(self.expected_data("org", "json"))
        )

    def test_export_org_json_pretty(self):
        """ test pretty json export of organization search """
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
        """ test csv export of organization search """
        client = Client()
        response = client.get(
            "/export/advanced-search/org/csv?name_search=Organization"
        )
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("org", "csv")
