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
    def test_export_asn_connectivity_facilities_json(self, mock_generate):
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
            self.expected_data("asn-connectivity-facilities", "json")
        )

    @patch(
        "peeringdb_server.export_views.AdvancedSearchExportView.generate_asn_connectivity"
    )
    def test_export_asn_connectivity_facilities_csv(self, mock_generate):
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
        ).rstrip() == self.expected_data("asn-connectivity-facilities", "csv")

    @patch(
        "peeringdb_server.export_views.AdvancedSearchExportView.generate_asn_connectivity"
    )
    def test_export_asn_connectivity_exchanges_json(self, mock_generate):
        """test JSON export of ASN connectivity"""
        expected_results = [
            {
                "Exchange ID": 1,
                "Exchange Name": "Equinix Ashburn",
                "City": "Ashburn",
                "AS394749": True,
            },
            {
                "Exchange ID": 9,
                "Exchange Name": "Equinix Atlanta",
                "City": "Atlanta",
                "AS394749": True,
            },
            {
                "Exchange ID": 2,
                "Exchange Name": "Equinix Chicago",
                "City": "Chicago",
                "AS394749": True,
            },
        ]

        mock_generate.return_value = expected_results

        client = Client()
        response = client.get(
            "/export/advanced-search/asn_connectivity/json?asn_list=394749"
        )
        assert json.loads(response.content) == json.loads(
            self.expected_data("asn-connectivity-exchanges", "json")
        )

    @patch(
        "peeringdb_server.export_views.AdvancedSearchExportView.generate_asn_connectivity"
    )
    def test_export_asn_connectivity_exchanges_csv(self, mock_generate):
        """test CSV export of ASN connectivity"""
        expected_results = [
            {
                "Exchange ID": 1,
                "Exchange Name": "Equinix Ashburn",
                "City": "Ashburn",
                "AS394749": True,
            },
            {
                "Exchange ID": 9,
                "Exchange Name": "Equinix Atlanta",
                "City": "Atlanta",
                "AS394749": True,
            },
            {
                "Exchange ID": 2,
                "Exchange Name": "Equinix Chicago",
                "City": "Chicago",
                "AS394749": True,
            },
        ]

        mock_generate.return_value = expected_results

        client = Client()
        response = client.get(
            "/export/advanced-search/asn_connectivity/csv?asn_list=394749"
        )
        assert response.content.decode("utf-8").replace(
            "\r\n", "\n"
        ).rstrip() == self.expected_data("asn-connectivity-exchanges", "csv")

    def test_export_asn_connectivity_facilities_filter_any_json(self):
        """test JSON export of ASN connectivity with match_filter=any-match"""
        # Create additional facilities and network relationships to test filtering
        # Facility 1 has ASN 1 and 2 (partial match - "any") - ASN 1 from original setup
        # Facility 2 has all ASNs: 1, 2, 3 (all match - "all") - ASN 2 from original setup
        # Facility 3 has only ASN 3 (no match - less than 2) - ASN 3 from original setup

        # Add ASN 2 to facility 1 (now has 1 and 2)
        with reversion.create_revision():
            NetworkFacility.objects.create(
                network=self.net[1], facility=self.fac[0], status="ok"
            )

        # Add ASN 1 and 3 to facility 2 (now has 2 (from setup), 1, and 3)
        with reversion.create_revision():
            NetworkFacility.objects.create(
                network=self.net[0], facility=self.fac[1], status="ok"
            )

            NetworkFacility.objects.create(
                network=self.net[2], facility=self.fac[1], status="ok"
            )

        client = Client()
        # Test with match_filter=any-match - should only return facilities with partial matches (2+ but not all ASNs)
        response = client.get(
            "/export/advanced-search/asn_connectivity/json?asn_list=1,2,3&connectivity_type=facilities&match_filter=any-match"
        )

        data = json.loads(response.content)
        results = data.get("results", [])

        # Should only include facilities with partial matches
        # Facility 1 has ASN 1 and 2 (2 out of 3) - partial match, should be included
        facility_names = [r["Facility Name"] for r in results]
        self.assertIn("Facility 1", facility_names)

        # Facility 2 has all ASNs (3 out of 3) - all match, should be excluded
        self.assertNotIn("Facility 2", facility_names)

        # Facility 3 has only ASN 3 (1 out of 3) - not a partial match, should be excluded
        self.assertNotIn("Facility 3", facility_names)

    def test_export_asn_connectivity_facilities_filter_all_match_json(self):
        """test JSON export of ASN connectivity with match_filter=all-match"""
        # Create a scenario where one facility has all ASNs and others don't

        # Add all ASNs to facility 1
        with reversion.create_revision():
            NetworkFacility.objects.create(
                network=self.net[1], facility=self.fac[0], status="ok"
            )
            NetworkFacility.objects.create(
                network=self.net[2], facility=self.fac[0], status="ok"
            )

        client = Client()
        # Test with match_filter=all-match - should only return facilities with all ASNs
        response = client.get(
            "/export/advanced-search/asn_connectivity/json?asn_list=1,2,3&connectivity_type=facilities&match_filter=all-match"
        )

        data = json.loads(response.content)
        results = data.get("results", [])

        # Should only include facilities with all 3 ASNs
        facility_names = [r["Facility Name"] for r in results]
        self.assertIn("Facility 1", facility_names)

        # Facility 2 and 3 don't have all ASNs, should be excluded
        self.assertNotIn("Facility 2", facility_names)
        self.assertNotIn("Facility 3", facility_names)

    def test_export_asn_connectivity_facilities_hide_unmatched_json(self):
        """test JSON export of ASN connectivity with hide_unmatched=1"""
        # Create a scenario with facilities having different match levels

        # Facility 1 already has ASN 1
        # Add ASN 2 to facility 1 (now has 1 and 4 - partial match)
        with reversion.create_revision():
            NetworkFacility.objects.create(
                network=self.net[1], facility=self.fac[0], status="ok"
            )

        # Facility 2 and 3 remain with only their original ASN (no match - single ASN)

        client = Client()
        # Test with hide_unmatched=1 - should exclude facilities with no matches
        response = client.get(
            "/export/advanced-search/asn_connectivity/json?asn_list=1,2,3&connectivity_type=facilities&hide_unmatched=1"
        )

        data = json.loads(response.content)
        results = data.get("results", [])

        # Facility 1 has ASN 1 and 4 - should be included
        facility_names = [r["Facility Name"] for r in results]
        self.assertIn("Facility 1", facility_names)

        # Facility 2 has only ASN 2 (not in list) and Facility 3 has only ASN 3 (not in list)
        # These are "no match" cases and should be excluded
        self.assertNotIn("Facility 2", facility_names)
        self.assertNotIn("Facility 3", facility_names)

    def test_export_asn_connectivity_facilities_combined_filters_json(self):
        """test JSON export of ASN connectivity with both match_filter=any-match and hide_unmatched=1"""
        # Create a comprehensive test scenario

        # Facility 1: ASN 1, 2 (partial match - 2 out of 3)
        with reversion.create_revision():
            NetworkFacility.objects.create(
                network=self.net[1], facility=self.fac[0], status="ok"
            )

        # Facility 2: Add ASN 1 and 3 to facility 2 (now has 2, 1, 3 - all match - all 3)
        with reversion.create_revision():
            NetworkFacility.objects.create(
                network=self.net[0], facility=self.fac[1], status="ok"
            )
            NetworkFacility.objects.create(
                network=self.net[2], facility=self.fac[1], status="ok"
            )

        # Facility 3 remains with only ASN 3 (no match)

        client = Client()
        # Test with match_filter=any-match AND hide_unmatched=1
        # Should only return facilities with partial matches (not all, not no match)
        response = client.get(
            "/export/advanced-search/asn_connectivity/json?asn_list=1,2,3&connectivity_type=facilities&match_filter=any-match&hide_unmatched=1"
        )

        data = json.loads(response.content)
        results = data.get("results", [])

        # Facility 1 has partial match (2 out of 3: ASN 1, 2) - should be included
        facility_names = [r["Facility Name"] for r in results]
        self.assertIn("Facility 1", facility_names)

        # Facility 2 has all match (all 3: ASN 1, 2, 3) - excluded by match_filter=any
        self.assertNotIn("Facility 2", facility_names)

        # Facility 3 has no match - excluded by hide_unmatched=1
        self.assertNotIn("Facility 3", facility_names)

    def test_export_asn_connectivity_exchanges_filter_any_json(self):
        """test JSON export of ASN connectivity for exchanges with match_filter=any-match"""
        # Create additional networks and exchange relationships

        # Add ASN 2 to exchange 1 (now has ASN 1 and 2 - partial match)
        with reversion.create_revision():
            NetworkIXLan.objects.create(
                ixlan=self.ixlan[0],
                network=self.net[1],
                asn=2,
                speed=0,
                status="ok",
            )

        # Add ASN 1 and 3 to exchange 2 (now has ASN 2, 1, 3 - all match)
        with reversion.create_revision():
            NetworkIXLan.objects.create(
                ixlan=self.ixlan[1],
                network=self.net[0],
                asn=1,
                speed=0,
                status="ok",
            )

            NetworkIXLan.objects.create(
                ixlan=self.ixlan[1],
                network=self.net[2],
                asn=3,
                speed=0,
                status="ok",
            )

        client = Client()
        # Test with match_filter=any-match - should only return exchanges with partial matches
        response = client.get(
            "/export/advanced-search/asn_connectivity/json?asn_list=1,2,3&connectivity_type=exchanges&match_filter=any-match"
        )

        data = json.loads(response.content)
        results = data.get("results", [])

        exchange_names = [r["Exchange Name"] for r in results]

        # Exchange 1 has ASN 1 and 2 (2 out of 3) - partial match, should be included
        self.assertIn("Exchange 1", exchange_names)

        # Exchange 2 has all ASNs (3 out of 3) - all match, should be excluded
        self.assertNotIn("Exchange 2", exchange_names)

        # Exchange 3 has only ASN 3 (1 out of 3) - not a partial match, should be excluded
        self.assertNotIn("Exchange 3", exchange_names)

    def test_export_asn_connectivity_exchanges_hide_unmatched_json(self):
        """test JSON export of ASN connectivity for exchanges with hide_unmatched=1"""
        # Create a scenario with exchanges having different match levels

        # Exchange 1 already has ASN 1
        # Add ASN 2 to exchange 1 (now has 1 and 2 - partial match)
        with reversion.create_revision():
            NetworkIXLan.objects.create(
                ixlan=self.ixlan[0],
                network=self.net[1],
                asn=2,
                speed=0,
                status="ok",
            )

        # Exchange 2 and 3 remain with only their original ASN (no match - single ASN)

        client = Client()
        # Test with hide_unmatched=1 - should exclude exchanges with no matches
        response = client.get(
            "/export/advanced-search/asn_connectivity/json?asn_list=1,2,3&connectivity_type=exchanges&hide_unmatched=1"
        )

        data = json.loads(response.content)
        results = data.get("results", [])

        # Exchange 1 has ASN 1 and 2 - should be included
        exchange_names = [r["Exchange Name"] for r in results]
        self.assertIn("Exchange 1", exchange_names)

        # Exchange 2 has only ASN 2 (not in list) and Exchange 3 has only ASN 3 (not in list)
        # These are "no match" cases and should be excluded
        self.assertNotIn("Exchange 2", exchange_names)
        self.assertNotIn("Exchange 3", exchange_names)

    def test_export_asn_connectivity_exchanges_combined_filters_csv(self):
        """test CSV export of ASN connectivity for exchanges with both filters"""
        # Create a comprehensive test scenario

        # Exchange 1: ASN 1, 2 (partial match - 2 out of 3)
        with reversion.create_revision():
            NetworkIXLan.objects.create(
                ixlan=self.ixlan[0],
                network=self.net[1],
                asn=2,
                speed=0,
                status="ok",
            )

        # Exchange 2: ASN 1, 2, 3 (all match - all 3)
        with reversion.create_revision():
            NetworkIXLan.objects.create(
                ixlan=self.ixlan[1],
                network=self.net[0],
                asn=1,
                speed=0,
                status="ok",
            )
            NetworkIXLan.objects.create(
                ixlan=self.ixlan[1],
                network=self.net[2],
                asn=3,
                speed=0,
                status="ok",
            )

        # Exchange 3 remains with only ASN 3 (no match)

        client = Client()
        # Test with match_filter=all-match AND hide_unmatched=1
        response = client.get(
            "/export/advanced-search/asn_connectivity/csv?asn_list=1,2,3&connectivity_type=exchanges&match_filter=all-match&hide_unmatched=1"
        )

        csv_content = response.content.decode("utf-8")

        # Exchange 2 has all match (all 3) - should be included
        self.assertIn("Exchange 2", csv_content)

        # Exchange 1 has partial match - excluded by match_filter=all-match
        self.assertNotIn("Exchange 1", csv_content)

        # Exchange 3 has no match - excluded by hide_unmatched=1
        self.assertNotIn("Exchange 3", csv_content)
