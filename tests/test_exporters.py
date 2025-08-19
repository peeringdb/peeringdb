"""
Test peeringdb data export views
"""

import datetime
import json
import os
import re
import tempfile
from unittest.mock import patch

import reversion
from django.core.management import call_command
from django.test import Client

from peeringdb_server.models import (
    Facility,
    InternetExchange,
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

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_net_json(self, mock_search_v2):
        """test json export of network search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "net",
                        "_id": net.id,
                        "_score": 1,
                        "_source": {
                            "name": net.name,
                            "status": net.status,
                            "aka": net.aka,
                            "policy_general": net.policy_general,
                            "info_traffic": net.info_traffic,
                            "info_types": net.info_types,
                            "asn": net.asn,
                            "org": {
                                "id": net.org.id,
                                "name": net.org.name,
                                "country": net.org.country,
                                "city": net.org.city,
                                "status": net.org.status,
                            },
                        },
                    }
                    for net in self.net
                ],
            }
        }

        client = Client()
        response = client.get("/export/advanced-search/net/json?name_search=Network")
        assert json.loads(response.content) == json.loads(
            self.expected_data("net", "json")
        )

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_net_json_pretty(self, mock_search_v2):
        """test pretty json export of network search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "net",
                        "_id": net.id,
                        "_score": 1,
                        "_source": {
                            "name": net.name,
                            "status": net.status,
                            "aka": net.aka,
                            "policy_general": net.policy_general,
                            "info_traffic": net.info_traffic,
                            "info_types": net.info_types,
                            "asn": net.asn,
                            "org": {
                                "id": net.org.id,
                                "name": net.org.name,
                                "country": net.org.country,
                                "city": net.org.city,
                                "status": net.org.status,
                            },
                        },
                    }
                    for net in self.net
                ],
            }
        }
        client = Client()
        response = client.get(
            "/export/advanced-search/net/json-pretty?name_search=Network"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("net", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_net_csv(self, mock_search_v2):
        """test csv export of network search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "net",
                        "_id": net.id,
                        "_score": 1,
                        "_source": {
                            "name": net.name,
                            "status": net.status,
                            "aka": net.aka,
                            "policy_general": net.policy_general,
                            "info_traffic": net.info_traffic,
                            "info_types": net.info_types,
                            "asn": net.asn,
                            "org": {
                                "id": net.org.id,
                                "name": net.org.name,
                                "country": net.org.country,
                                "city": net.org.city,
                                "status": net.org.status,
                            },
                        },
                    }
                    for net in self.net
                ],
            }
        }

        client = Client()
        response = client.get("/export/advanced-search/net/csv?name_search=Network")
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("net", "csv")

    def test_export_net_csv_with_api_cache(self):
        """test csv export of net search while api-cache exists"""

        call_command("pdb_api_cache", date=datetime.datetime.now().strftime("%Y%m%d"))

        self.test_export_net_csv()

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_fac_json(self, mock_search_v2):
        """test json export of facility search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "fac",
                        "_id": fac.id,
                        "_score": 1,
                        "_source": {
                            "name": fac.name,
                            "status": fac.status,
                            "city": fac.city,
                            "clli": fac.clli,
                            "state": fac.state,
                            "npanxx": fac.npanxx,
                            "country": fac.country,
                            "zipcode": fac.zipcode,
                            "latitude": fac.latitude,
                            "longitude": fac.longitude,
                            "org": {
                                "id": fac.org.id,
                                "name": fac.org.name,
                                "country": fac.org.country,
                                "city": fac.org.city,
                                "status": fac.org.status,
                            },
                        },
                    }
                    for fac in self.fac
                ],
            }
        }

        client = Client()
        response = client.get("/export/advanced-search/fac/json?name_search=Facility")
        assert json.loads(response.content) == json.loads(
            self.expected_data("fac", "json")
        )

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_fac_json_pretty(self, mock_search_v2):
        """test pretty json export of facility search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "fac",
                        "_id": fac.id,
                        "_score": 1,
                        "_source": {
                            "name": fac.name,
                            "status": fac.status,
                            "city": fac.city,
                            "clli": fac.clli,
                            "state": fac.state,
                            "npanxx": fac.npanxx,
                            "country": fac.country,
                            "zipcode": fac.zipcode,
                            "latitude": fac.latitude,
                            "longitude": fac.longitude,
                            "org": {
                                "id": fac.org.id,
                                "name": fac.org.name,
                                "country": fac.org.country,
                                "city": fac.org.city,
                                "status": fac.org.status,
                            },
                        },
                    }
                    for fac in self.fac
                ],
            }
        }

        client = Client()
        response = client.get(
            "/export/advanced-search/fac/json-pretty?name_search=Facility"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("fac", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_fac_csv(self, mock_search_v2):
        """test csv export of facility search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "fac",
                        "_id": fac.id,
                        "_score": 1,
                        "_source": {
                            "name": fac.name,
                            "status": fac.status,
                            "city": fac.city,
                            "clli": fac.clli,
                            "state": fac.state,
                            "npanxx": fac.npanxx,
                            "country": fac.country,
                            "zipcode": fac.zipcode,
                            "latitude": fac.latitude,
                            "longitude": fac.longitude,
                            "org": {
                                "id": fac.org.id,
                                "name": fac.org.name,
                                "country": fac.org.country,
                                "city": fac.org.city,
                                "status": fac.org.status,
                            },
                        },
                    }
                    for fac in self.fac
                ],
            }
        }

        client = Client()
        response = client.get("/export/advanced-search/fac/csv?name_search=Facility")

        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("fac", "csv")

    def test_export_fac_csv_with_api_cache(self):
        """test csv export of facility search while api-cache exists"""

        call_command("pdb_api_cache", date=datetime.datetime.now().strftime("%Y%m%d"))

        self.test_export_fac_csv()

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_ix_json(self, mock_search_v2):
        """test json export of exchange search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "ix",
                        "_id": ix.id,
                        "_score": 1,
                        "_source": {
                            "name": ix.name,
                            "status": ix.status,
                            "city": ix.city,
                            "country": ix.country,
                            "media": ix.media,
                            "org": {
                                "id": ix.org.id,
                                "name": ix.org.name,
                                "country": ix.org.country,
                                "city": ix.org.city,
                                "status": ix.org.status,
                            },
                        },
                    }
                    for ix in self.ix
                ],
            }
        }

        client = Client()
        response = client.get("/export/advanced-search/ix/json?name_search=Exchange")
        self.assertEqual(
            json.loads(response.content), json.loads(self.expected_data("ix", "json"))
        )

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_ix_json_pretty(self, mock_search_v2):
        """test pretty json export of exchange search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "ix",
                        "_id": ix.id,
                        "_score": 1,
                        "_source": {
                            "name": ix.name,
                            "status": ix.status,
                            "city": ix.city,
                            "country": ix.country,
                            "media": ix.media,
                            "org": {
                                "id": ix.org.id,
                                "name": ix.org.name,
                                "country": ix.org.country,
                                "city": ix.org.city,
                                "status": ix.org.status,
                            },
                        },
                    }
                    for ix in self.ix
                ],
            }
        }

        client = Client()
        response = client.get(
            "/export/advanced-search/ix/json-pretty?name_search=Exchange"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("ix", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_ix_csv(self, mock_search_v2):
        """test csv export of exchange search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "ix",
                        "_id": ix.id,
                        "_score": 1,
                        "_source": {
                            "name": ix.name,
                            "status": ix.status,
                            "city": ix.city,
                            "country": ix.country,
                            "media": ix.media,
                            "org": {
                                "id": ix.org.id,
                                "name": ix.org.name,
                                "country": ix.org.country,
                                "city": ix.org.city,
                                "status": ix.org.status,
                            },
                        },
                    }
                    for ix in self.ix
                ],
            }
        }

        client = Client()
        response = client.get("/export/advanced-search/ix/csv?name_search=Exchange")
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("ix", "csv")

    def test_export_ix_csv_with_api_cache(self):
        """test csv export of ix search while api-cache exists"""

        call_command("pdb_api_cache", date=datetime.datetime.now().strftime("%Y%m%d"))

        self.test_export_ix_csv()

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_org_json(self, mock_search_v2):
        """test json export of organization search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "org",
                        "_id": org.id,
                        "_score": 1,
                        "_source": {
                            "name": org.name,
                            "status": org.status,
                            "city": org.city,
                            "country": org.country,
                        },
                    }
                    for org in self.org
                ],
            }
        }

        client = Client()
        response = client.get(
            "/export/advanced-search/org/json?name_search=Organization"
        )
        self.assertEqual(
            json.loads(response.content), json.loads(self.expected_data("org", "json"))
        )

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_org_json_pretty(self, mock_search_v2):
        """test pretty json export of organization search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "org",
                        "_id": org.id,
                        "_score": 1,
                        "_source": {
                            "name": org.name,
                            "status": org.status,
                            "city": org.city,
                            "country": org.country,
                        },
                    }
                    for org in self.org
                ],
            }
        }

        client = Client()
        response = client.get(
            "/export/advanced-search/org/json-pretty?name_search=Organization"
        )

        assert json.loads(response.content) == json.loads(
            self.expected_data("org", "jsonpretty")
        )

        # TODO: better check for pretty json formatting

        assert len(re.findall(r"\n  ", response.content.decode("utf-8"))) > 0

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_org_csv(self, mock_search_v2):
        """test csv export of organization search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "org",
                        "_id": org.id,
                        "_score": 1,
                        "_source": {
                            "name": org.name,
                            "status": org.status,
                            "city": org.city,
                            "country": org.country,
                        },
                    }
                    for org in self.org
                ],
            }
        }

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

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_export_fac_kmz(self, mock_search_v2):
        """test kmz export of facility search"""
        mock_es = mock_search_v2.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_index": "fac",
                        "_id": fac.id,
                        "_score": 1,
                        "_source": {
                            "name": fac.name,
                            "status": fac.status,
                            "city": fac.city,
                            "clli": fac.clli,
                            "state": fac.state,
                            "npanxx": fac.npanxx,
                            "country": fac.country,
                            "zipcode": fac.zipcode,
                            "latitude": fac.latitude,
                            "longitude": fac.longitude,
                            "org": {
                                "id": fac.org.id,
                                "name": fac.org.name,
                                "country": fac.org.country,
                                "city": fac.org.city,
                                "status": fac.org.status,
                            },
                        },
                    }
                    for fac in self.fac
                ],
            }
        }

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

    @patch(
        "peeringdb_server.export_views.AdvancedSearchExportView.generate_asn_connectivity"
    )
    def test_export_asn_connectivity_json(self, mock_generate):
        """test JSON export of ASN connectivity"""
        expected_results = [
            {
                "Facility ID": 2361,
                "Facility Name": "Equinix HK3 - Hong Kong",
                "City": "Tsuen Wan",
                "Country": "HK",
                "AS932": True,
                "AS1024": False,
            },
            {
                "Facility ID": 13626,
                "Facility Name": "MEGA Gateway (iAdvantage Hong Kong)",
                "City": "Hong Kong",
                "Country": "HK",
                "AS932": True,
                "AS1024": False,
            },
            {
                "Facility ID": 9693,
                "Facility Name": "TGT Hong Kong Data Centre 1",
                "City": "Hong Kong",
                "Country": "HK",
                "AS932": True,
                "AS1024": False,
            },
        ]

        mock_generate.return_value = expected_results

        client = Client()
        response = client.get(
            "/export/advanced-search/asn_connectivity/json?asn_list=932,1024"
        )
        assert json.loads(response.content) == json.loads(
            self.expected_data("asn-connectivity", "json")
        )

    @patch(
        "peeringdb_server.export_views.AdvancedSearchExportView.generate_asn_connectivity"
    )
    def test_export_asn_connectivity_csv(self, mock_generate):
        """test CSV export of ASN connectivity"""
        expected_results = [
            {
                "Facility ID": 2361,
                "Facility Name": "Equinix HK3 - Hong Kong",
                "City": "Tsuen Wan",
                "Country": "HK",
                "AS932": True,
                "AS1024": False,
            },
            {
                "Facility ID": 13626,
                "Facility Name": "MEGA Gateway (iAdvantage Hong Kong)",
                "City": "Hong Kong",
                "Country": "HK",
                "AS932": True,
                "AS1024": False,
            },
            {
                "Facility ID": 9693,
                "Facility Name": "TGT Hong Kong Data Centre 1",
                "City": "Hong Kong",
                "Country": "HK",
                "AS932": True,
                "AS1024": False,
            },
        ]

        mock_generate.return_value = expected_results

        client = Client()
        response = client.get(
            "/export/advanced-search/asn_connectivity/csv?asn_list=932,1024"
        )
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("asn-connectivity", "csv")
