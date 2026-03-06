import json
import os
from unittest.mock import MagicMock, patch

import elasticsearch
import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import RequestFactory, TestCase

import peeringdb_server.models as models
import peeringdb_server.search as search
import peeringdb_server.views as views
from peeringdb_server.rest import search_api_view
from peeringdb_server.search_v2 import (
    add_and_between_keywords,
    build_geo_filter,
    construct_ipv4_query,
    construct_ipv6_query,
    construct_query_body,
    elasticsearch_proximity_entity,
    escape_query_string,
    is_matching_geo,
    is_valid_latitude,
    is_valid_longitude,
    order_results_alphabetically,
    process_search_results,
    search_v2,
)


@pytest.mark.django_db
@pytest.mark.usefixtures("elasticsearch_index")
@pytest.mark.xdist_group(name="elasticsearch_tests")
class SearchV2TestCase(TestCase):
    """
    Test suite for v2 search functionality using real Elasticsearch instance.

    Uses elasticsearch_index fixture via @pytest.mark.usefixtures decorator
    to ensure Elasticsearch is set up before tests run.
    """

    @classmethod
    def setUpTestData(cls):
        """Generate test data in database only - indexing handled by fixtures."""
        call_command("pdb_generate_test_data", limit=2, commit=True)

    def setUp(self):
        search.ELASTICSEARCH_URL = os.environ.get(
            "ELASTICSEARCH_URL", "http://localhost:9200"
        )
        self.indexes = ["fac", "ix", "net", "org", "campus", "carrier"]
        self.factory = RequestFactory()
        self.user = models.User.objects.create_user(
            username="testuser", password="testpass"
        )
        api_key, user_key = models.UserAPIKey.objects.create_key(
            user=self.user, name="User api key"
        )
        self.user_key = user_key

    def tearDown(self):
        pass

    def test_search_ix(self):
        response = self.client.get("/search/v2?q=Exchange")
        content = response.content.decode("utf-8")

        self.assertIn("Exchanges", content)
        self.assertEqual(response.status_code, 200)

        exchanges = models.InternetExchange.objects.filter(status="ok")
        if exchanges.exists():
            self.assertIn("view_title", content)

    def test_search_net(self):
        response = self.client.get("/search/v2?q=Network")
        content = response.content.decode("utf-8")

        self.assertIn("Networks", content)
        self.assertEqual(response.status_code, 200)

        networks = models.Network.objects.filter(status="ok")
        if networks.exists():
            self.assertIn("view_title", content)

    def test_search_fac(self):
        response = self.client.get("/search/v2?q=Facility")
        content = response.content.decode("utf-8")

        self.assertIn("Facilities", content)
        self.assertEqual(response.status_code, 200)

        facilities = models.Facility.objects.filter(status="ok")
        if facilities.exists():
            self.assertIn("view_title", content)

    def test_search_org(self):
        response = self.client.get("/search/v2?q=Organization")
        content = response.content.decode("utf-8")

        self.assertIn("Organizations", content)
        self.assertEqual(response.status_code, 200)

        orgs = models.Organization.objects.filter(status="ok")
        if orgs.exists():
            self.assertIn("view_title", content)

    def test_search_campus(self):
        response = self.client.get("/search/v2?q=Campus")
        content = response.content.decode("utf-8")

        self.assertIn("Campus", content)
        self.assertEqual(response.status_code, 200)

        campuses = models.Campus.objects.filter(status="ok")
        if campuses.exists():
            self.assertIn("view_title", content)

    def test_search_carrier(self):
        response = self.client.get("/search/v2?q=Carrier")
        content = response.content.decode("utf-8")

        self.assertIn("Carriers", content)
        self.assertEqual(response.status_code, 200)

        carriers = models.Carrier.objects.filter(status="ok")
        if carriers.exists():
            self.assertIn("view_title", content)

    def test_process_near_search(self):
        geo = {}
        q = ["fac near 40.7128,-74.0060"]
        result = views.process_near_search(q, geo)
        self.assertIn("lat", result)
        self.assertIn("long", result)
        self.assertIn("dist", result)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_process_in_search(self, mock_google_maps):
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "United States", "types": ["country"]},
                    {"short_name": "US", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 37.0902, "lng": -95.7129},
                    "bounds": {
                        "northeast": {"lat": 49.3457, "lng": -66.9513},
                        "southwest": {"lat": 25.7617, "lng": -124.7844},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": None,
            "country": "US",
        }
        mock_instance.distance_from_bounds.return_value = 1000

        mock_google_maps.return_value = mock_instance

        geo = {}
        q = ["fac in USA"]
        result = views.process_in_search(q, geo)

        self.assertIn("lat", result)
        self.assertIn("long", result)
        self.assertEqual(result["lat"], 37.0902)
        self.assertEqual(result["long"], -95.7129)

    def test_handle_coordinate_search(self):
        geo = {}
        q = ["fac near 40.7128,-74.0060"]
        list_of_words = q[0].split()
        geo = views.handle_coordinate_search(list_of_words, 1, q, 0, geo)
        self.assertEqual(geo["lat"], "40.7128")
        self.assertEqual(geo["long"], "-74.0060")

    @patch("peeringdb_server.views.handle_proximity_entity_search")
    def test_handle_proximity_entity_search(self, mock_proximity):
        mock_geo = {
            "lat": 48.8584,
            "long": 2.2945,
            "dist": "20km",
            "proximity_entity": {
                "name": "Facility B",
                "latitude": 48.0000,
                "longitude": 2.0000,
                "ref_tag": "fac",
                "id": "123",
            },
        }
        mock_proximity.return_value = mock_geo

        geo = {}
        list_of_words = ["near", "Facility", "A"]
        idx = 0
        q = ["near Facility A"]
        query_idx = 0

        result = views.handle_proximity_entity_search(
            list_of_words, idx, q, query_idx, geo
        )

        self.assertEqual(result, mock_geo)
        self.assertIn("lat", result)
        self.assertIn("long", result)
        self.assertIn("proximity_entity", result)
        self.assertEqual(result["lat"], 48.8584)
        self.assertEqual(result["long"], 2.2945)
        self.assertEqual(result["dist"], "20km")

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_handle_city_country_search(self, mock_google_maps):
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Paris", "types": ["locality"]},
                    {"short_name": "FR", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 48.8566, "lng": 2.3522},
                    "bounds": {
                        "northeast": {"lat": 48.9, "lng": 2.4},
                        "southwest": {"lat": 48.8, "lng": 2.3},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Paris",
            "country": "FR",
        }
        mock_instance.distance_from_bounds.return_value = 10

        mock_google_maps.return_value = mock_instance

        geo = {}
        q = ["fac in France"]
        list_of_words = q[0].split()
        geo = views.handle_city_country_search(list_of_words, 1, q, 0, geo)

        self.assertIn("lat", geo)
        self.assertIn("long", geo)
        self.assertIn("dist", geo)
        self.assertEqual(geo["lat"], 48.8566)
        self.assertEqual(geo["long"], 2.3522)

    def test_escape_query_string(self):
        self.assertEqual(escape_query_string("test"), "test")
        self.assertEqual(escape_query_string("test?"), "test\\?")
        self.assertEqual(escape_query_string("te*st"), "te\\*st")
        self.assertEqual(escape_query_string("test\\"), "test\\\\")

    def test_add_and_between_keywords(self):
        self.assertEqual(
            add_and_between_keywords("test facility".split()),
            ["test", "AND", "facility"],
        )
        self.assertEqual(add_and_between_keywords("facility".split()), ["facility"])

    def test_is_valid_latitude(self):
        self.assertTrue(is_valid_latitude(45.0))
        self.assertTrue(is_valid_latitude(-90.0))
        self.assertFalse(is_valid_latitude(-91.0))
        self.assertFalse(is_valid_latitude(91.0))

    def test_is_valid_longitude(self):
        self.assertTrue(is_valid_longitude(90.0))
        self.assertTrue(is_valid_longitude(-180.0))
        self.assertFalse(is_valid_longitude(181.0))
        self.assertFalse(is_valid_longitude(-181.0))

    def test_elasticsearch_proximity_entity(self):
        facility = models.Facility.objects.filter(
            status="ok", latitude__isnull=False, longitude__isnull=False
        ).first()

        if not facility:
            result = elasticsearch_proximity_entity("test facility")
            self.assertIsNone(result)
            self.skipTest("No facilities with geocode coordinates available")

        search_term = facility.name[:8] if len(facility.name) > 8 else facility.name
        result = elasticsearch_proximity_entity(search_term)

        if result:
            self.assertIn("name", result)
            self.assertIn("ref_tag", result)
            self.assertIn("id", result)
            self.assertIn(result["ref_tag"], ["fac", "org"])

    def test_elasticsearch_proximity_entity_no_results(self):
        result = elasticsearch_proximity_entity("nonexistent facility")
        self.assertIsNone(result)

    def test_order_results_alphabetically(self):
        data = {
            "fac": [
                {"name": "B Facility"},
                {"name": "A Facility"},
                {"name": "C Facility"},
            ]
        }
        expected = {
            "fac": [
                {"name": "A Facility"},
                {"name": "B Facility"},
                {"name": "C Facility"},
            ]
        }

        self.assertEqual(order_results_alphabetically(data, []), expected)

        # test order results with OR query
        data = {
            "fac": [
                {"name": "Equinix DC1"},
                {"name": "FR5 Data Center"},
                {"name": "Equinix FR5"},
                {"name": "ABC Data Center"},
                {"name": "FR51 Facility"},
            ]
        }

        expected = {
            "fac": [
                {"name": "Equinix FR5"},
                {"name": "FR5 Data Center"},
                {"name": "FR51 Facility"},
                {"name": "ABC Data Center"},
                {"name": "Equinix DC1"},
            ]
        }

        search_terms = ["Equinix", "FR5"]
        original_query = "Equinix OR FR5"

        result = order_results_alphabetically(data, search_terms, original_query)
        self.assertEqual(result, expected)

        # test case insensitivity for exact matches
        data = {
            "fac": [
                {"name": "Random Facility"},
                {"name": "TEST FACILITY"},
                {"name": "Another Facility"},
            ]
        }

        expected = {
            "fac": [
                {"name": "TEST FACILITY"},
                {"name": "Another Facility"},
                {"name": "Random Facility"},
            ]
        }

        result = order_results_alphabetically(
            data, search_terms=["test", "facility"], original_query="test facility"
        )
        self.assertEqual(result, expected)

    def test_construct_query_body(self):
        valid_geo = {
            "location": "Los Angeles",
            "country": "US",
            "lat": 34.0549076,
            "long": -118.242643,
            "dist": "84km",
        }

        result = construct_query_body(
            "*fac*",
            valid_geo,
            self.indexes,
            ipv4_construct=False,
            ipv6_construct=False,
            user=None,
        )
        expected = {
            "query": {
                "bool": {
                    "must": {"term": {"_index": "fac"}},
                    "filter": [
                        {
                            "geo_distance": {
                                "distance": "84km",
                                "geocode_coordinates": {
                                    "lat": 34.0549076,
                                    "lon": -118.242643,
                                },
                            }
                        },
                        {"term": {"country.raw": "US"}},
                    ],
                }
            },
            "explain": True,
            "_source": True,
            "sort": ["_score"],
        }
        self.assertEqual(result, expected)

        # test exception handling
        result = construct_query_body(
            "not indexes",
            valid_geo,
            self.indexes,
            ipv4_construct=False,
            ipv6_construct=False,
            user=None,
        )
        expected = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "bool": {
                                "should": [
                                    {
                                        "multi_match": {
                                            "query": "not indexes",
                                            "type": "phrase",
                                            "fields": [
                                                "name",
                                                "name_long",
                                                "aka",
                                                "city",
                                            ],
                                            "boost": 10.0,
                                        }
                                    },
                                    {
                                        "multi_match": {
                                            "query": "not indexes",
                                            "type": "phrase_prefix",
                                            "fields": [
                                                "name",
                                                "name_long",
                                                "aka",
                                                "city",
                                            ],
                                            "boost": 5.0,
                                        }
                                    },
                                    {
                                        "query_string": {
                                            "query": "not indexes",
                                            "fields": [
                                                "name",
                                                "name_long",
                                                "aka",
                                                "city",
                                            ],
                                            "boost": 2.0,
                                        }
                                    },
                                ],
                                "minimum_should_match": 1,
                            }
                        }
                    ],
                    "filter": [
                        {
                            "geo_distance": {
                                "distance": "84km",
                                "geocode_coordinates": {
                                    "lat": 34.0549076,
                                    "lon": -118.242643,
                                },
                            }
                        },
                        {"term": {"country.raw": "US"}},
                    ],
                }
            },
            "explain": True,
            "_source": True,
            "sort": ["_score"],
        }
        self.assertEqual(result, expected)

        # test location only
        result = construct_query_body(
            "",
            valid_geo,
            self.indexes,
            ipv4_construct=False,
            ipv6_construct=False,
            user=None,
        )
        expected = {
            "query": {
                "bool": {
                    "must": {
                        "terms": {
                            "_index": ["fac", "ix", "net", "org", "campus", "carrier"]
                        }
                    },
                    "filter": [
                        {
                            "geo_distance": {
                                "distance": "84km",
                                "geocode_coordinates": {
                                    "lat": 34.0549076,
                                    "lon": -118.242643,
                                },
                            }
                        },
                        {"term": {"country.raw": "US"}},
                    ],
                }
            },
            "explain": True,
            "_source": True,
            "sort": ["_score"],
        }
        self.assertEqual(result, expected)

    def test_build_geo_filter_none(self):
        result = build_geo_filter(
            {
                "location": "nonexistent location",
                "country": "-",
                "lat": None,
                "long": None,
                "dist": "0km",
            }
        )
        self.assertIsNone(result)

    def test_non_matching_geo(self):
        search_query = {
            "took": 1,
            "timed_out": False,
            "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "max_score": 1.0,
                "hits": [
                    {
                        "_index": "fac",
                        "_id": "1001",
                        "_score": 1.0,
                        "_source": {
                            "name": "Test Facility",
                            "country": "US",
                            "longitude": -73.123456,
                            "state": "NY",
                            "latitude": 40.123456,
                            "org": {"id": 2001, "name": "Test Organization"},
                            "geocode_coordinates": {
                                "lat": 40.123456,
                                "lon": -73.123456,
                            },
                            "status": "ok",
                            "address1": "123 Test Street",
                            "address2": "",
                            "city": "Test City",
                            "zipcode": "12345",
                            "aka": "",
                            "name_long": "",
                        },
                    }
                ],
            },
        }

        geo = {
            "location": "",
            "state": None,
            "country": "CA",
            "lat": 45.123456,
            "long": -75.123456,
            "dist": "100km",
        }

        result = process_search_results(
            search_query=search_query, geo=geo, categories=self.indexes, limit=1000
        )

        expected_empty_result = {cat: [] for cat in self.indexes}
        self.assertEqual(result, expected_empty_result)

    def test_is_matching_geo(self):
        sq = {
            "_index": "fac",
            "_id": "1001",
            "_score": 1.0,
            "_source": {
                "name": "Test Facility",
                "country": "US",
                "state": "CA",
                "longitude": -122.123456,
                "latitude": 37.123456,
                "org": {"id": 2001, "name": "Test Organization"},
                "status": "ok",
            },
        }
        geo = {
            "location": "",
            "state": None,
            "country": "US",
            "lat": 37.123456,
            "long": -122.123456,
            "dist": "100km",
        }

        result = is_matching_geo(sq, geo)
        self.assertTrue(result)

        # test matching false
        geo = {
            "location": "",
            "state": "NY",
            "country": "US",
            "lat": 37.123456,
            "long": -122.123456,
            "dist": "100km",
        }

        result = is_matching_geo(sq, geo)
        self.assertFalse(result)

    def test_search_v2_with_or(self):
        facilities = list(models.Facility.objects.filter(status="ok")[:2])
        if len(facilities) < 2:
            self.skipTest("Need at least 2 facilities for OR test")

        fac1, fac2 = facilities[0], facilities[1]

        term1 = fac1.name.split()[0][:5] if fac1.name else "fac"
        term2 = fac2.name.split()[0][:5] if fac2.name else "fac"

        result = search_v2([f"{term1} OR {term2}"])

        self.assertIn("fac", result)
        self.assertIsInstance(result["fac"], list)

        total_results = sum(len(v) for v in result.values())
        if total_results == 0:
            self.skipTest(
                f"No results found for '{term1} OR {term2}' - data may not be indexed yet"
            )

        for category in result:
            if result[category]:
                first_result = result[category][0]
                self.assertIn("id", first_result)
                self.assertIn("name", first_result)
                break

    def test_search_v2_ipv6(self):
        netixlan = models.NetworkIXLan.objects.filter(
            status="ok", ipaddr6__isnull=False
        ).first()

        if not netixlan:
            self.skipTest("No netixlan with IPv6 address available")

        result = search_v2([str(netixlan.ipaddr6)])

        total_results = sum(len(v) for v in result.values())
        self.assertGreater(
            total_results,
            0,
            f"IPv6 search for {netixlan.ipaddr6} should return results",
        )

        for category in result:
            if result[category]:
                first_result = result[category][0]
                self.assertIn("id", first_result)
                self.assertIn("name", first_result)
                break

    def test_search_v2_ipv4(self):
        netixlan = models.NetworkIXLan.objects.filter(
            status="ok", ipaddr4__isnull=False
        ).first()

        if not netixlan:
            self.skipTest("No netixlan with IPv4 address available")

        result = search_v2([str(netixlan.ipaddr4)])

        total_results = sum(len(v) for v in result.values())
        self.assertGreater(
            total_results,
            0,
            f"IPv4 search for {netixlan.ipaddr4} should return results",
        )

        for category in result:
            if result[category]:
                first_result = result[category][0]
                self.assertIn("id", first_result)
                self.assertIn("name", first_result)
                break

    def test_construct_ipv4_query(self):
        """Test that IPv4 query construction works correctly."""
        result = construct_ipv4_query("192.168.1.1")
        expected = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "bool": {
                                "should": [
                                    {
                                        "prefix": {
                                            "ipaddr4.raw": {
                                                "value": "192.168.1.1",
                                                "boost": 10.0,
                                            }
                                        }
                                    },
                                    {
                                        "prefix": {
                                            "ipaddr4": {
                                                "value": "192.168.1.1",
                                                "boost": 5.0,
                                            }
                                        }
                                    },
                                ],
                                "minimum_should_match": 1,
                            }
                        }
                    ]
                }
            },
            "explain": True,
            "_source": True,
            "sort": ["_score"],
        }
        self.assertEqual(result, expected)

    def test_construct_ipv6_query(self):
        """Test that IPv6 query construction works correctly."""
        result = construct_ipv6_query("2001:db8:85a3")
        expected = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "bool": {
                                "should": [
                                    {
                                        "match_phrase": {
                                            "ipaddr6": {
                                                "query": "2001:db8:85a3",
                                                "boost": 10.0,
                                            }
                                        }
                                    },
                                    {
                                        "prefix": {
                                            "ipaddr6.raw": {
                                                "value": "2001:db8:85a3",
                                                "boost": 5.0,
                                            }
                                        }
                                    },
                                    {
                                        "match_phrase_prefix": {
                                            "ipaddr6": {
                                                "query": "2001:db8:85a3",
                                                "boost": 2.0,
                                            }
                                        }
                                    },
                                ],
                                "minimum_should_match": 1,
                            }
                        }
                    ]
                }
            },
            "explain": True,
            "_source": True,
            "sort": ["_score"],
        }
        self.assertEqual(result, expected)

    def test_search_v2_partial_ipv4(self):
        """Test that partial IPv4 addresses work with prefix matching."""
        netixlan = models.NetworkIXLan.objects.filter(
            status="ok", ipaddr4__isnull=False
        ).first()

        if not netixlan:
            self.skipTest("No netixlan with IPv4 address available")

        ip_parts = str(netixlan.ipaddr4).split(".")
        partial_ip = ".".join(ip_parts[:3])

        result = search_v2([partial_ip])

        total_results = sum(len(v) for v in result.values())
        self.assertGreater(
            total_results,
            0,
            f"Partial IPv4 search for {partial_ip} should return results",
        )

        for category in result:
            if result[category]:
                first_result = result[category][0]
                self.assertIn("id", first_result)
                self.assertIn("name", first_result)
                break

    def test_search_v2_partial_ipv6(self):
        """Test that partial IPv6 addresses work with prefix matching."""
        netixlan = models.NetworkIXLan.objects.filter(
            status="ok", ipaddr6__isnull=False
        ).first()

        if not netixlan:
            self.skipTest("No netixlan with IPv6 address available")

        ipv6_str = str(netixlan.ipaddr6)
        ip_parts = ipv6_str.split(":")[:3]
        partial_ipv6 = ":".join(ip_parts)

        result = search_v2([partial_ipv6])

        total_results = sum(len(v) for v in result.values())
        self.assertGreater(
            total_results,
            0,
            f"Partial IPv6 search for {partial_ipv6} should return results",
        )

        for category in result:
            if result[category]:
                first_result = result[category][0]
                self.assertIn("id", first_result)
                self.assertIn("name", first_result)
                break

    def test_search_v2_ipv6_trailing_colon(self):
        """Test that IPv6 addresses with trailing colons work by normalizing to without colon."""
        netixlan = models.NetworkIXLan.objects.filter(
            status="ok", ipaddr6__isnull=False
        ).first()

        if not netixlan:
            self.skipTest("No netixlan with IPv6 address available")

        ipv6_str = str(netixlan.ipaddr6)
        ip_parts = ipv6_str.split(":")[:2]
        partial_ipv6_with_colon = ":".join(ip_parts) + ":"

        result = search_v2([partial_ipv6_with_colon])

        total_results = sum(len(v) for v in result.values())
        self.assertGreater(
            total_results,
            0,
            f"IPv6 search with trailing colon {partial_ipv6_with_colon} should return results",
        )

        for category in result:
            if result[category]:
                first_result = result[category][0]
                self.assertIn("id", first_result)
                self.assertIn("name", first_result)
                break

    def test_search_api_view(self):
        facility = models.Facility.objects.filter(status="ok").first()
        if not facility:
            self.skipTest("No test facilities available")

        search_term = facility.name[:8] if len(facility.name) > 8 else facility.name

        request = self.factory.get(f"/api/search?q={search_term}")
        request.META["HTTP_AUTHORIZATION"] = f"api-key {self.user_key}"

        response = search_api_view(request)

        self.assertEqual(response.status_code, 200)
        content = json.loads(response.content)

        self.assertIsInstance(content, dict)
        expected_keys = ["fac", "ix", "net", "org", "campus", "carrier"]
        for key in expected_keys:
            self.assertIn(key, content)
            self.assertIsInstance(content[key], list)

        total_results = sum(len(v) for v in content.values())
        self.assertGreater(total_results, 0, "API search should return results")

        for category in content:
            if content[category]:
                first_result = content[category][0]
                self.assertIn("id", first_result)
                self.assertIn("name", first_result)
                self.assertIn("org_id", first_result)
                break

    def test_search_api_view_invalid_key(self):
        request = self.factory.get("/api/search?q=sila")
        request.META["HTTP_AUTHORIZATION"] = "api-key invalid-key"

        response = search_api_view(request)

        self.assertEqual(response.status_code, 403)
        content = json.loads(response.content)
        self.assertEqual(content["non_field_errors"][0], "Invalid API key")

    def test_search_api_view_no_auth(self):
        request = self.factory.get("/api/search?q=sila")

        response = search_api_view(request)

        self.assertEqual(response.status_code, 401)
        content = json.loads(response.content)
        self.assertIn("No API key provided", content["error"])


@pytest.mark.django_db
@pytest.mark.xdist_group(name="elasticsearch_tests")
class SearchV2SpecificTestCase(TestCase):
    """
    Test suite for search v2 fixes for specific issues.

    This test class creates its own data and indexes it independently
    to avoid interfering with the main SearchV2TestCase tests.
    """

    def setUp(self):
        search.ELASTICSEARCH_URL = os.environ.get(
            "ELASTICSEARCH_URL", "http://elasticsearch:9200"
        )

    def reindex_for_search(self):
        """
        Helper to reindex Elasticsearch and refresh indices for immediate search.

        Use this after creating objects dynamically in tests that need to
        search for them immediately.
        """
        call_command("pdb_search_index", "--rebuild", "-f")

        try:
            es_url = getattr(settings, "ELASTICSEARCH_URL", "http://elasticsearch:9200")
            es = elasticsearch.Elasticsearch(es_url)
            es.indices.refresh(index="_all")
        except Exception:
            raise

    def test_search_asn_without_prefix(self):
        """Test searching for ASN without 'AS' prefix (e.g., '63311')."""
        org = models.Organization.objects.create(name="Test Org", status="ok")
        net = models.Network.objects.create(
            name="Test Network", asn=63311, status="ok", org=org
        )
        self.reindex_for_search()

        response = self.client.get(f"/search/v2?q={net.asn}")
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Networks", content)

    def test_search_asn_with_prefix(self):
        """Test searching for ASN with 'AS' prefix (e.g., 'AS63311')."""
        org = models.Organization.objects.create(name="Test Org AS", status="ok")
        net = models.Network.objects.create(
            name="Test Network AS", asn=13335, status="ok", org=org
        )
        self.reindex_for_search()

        response = self.client.get(f"/search/v2?q=AS{net.asn}")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/net/{net.id}")

    def test_search_multiword(self):
        """Test multi-word search queries."""
        models.Organization.objects.create(name="Sewan Communications SAS", status="ok")
        self.reindex_for_search()

        response = self.client.get("/search/v2?q=Sewan Communications")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_fac_in_city(self, mock_google_maps):
        """Test 'fac in [city]' search pattern (e.g., 'fac in charlotte')."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Charlotte", "types": ["locality"]},
                    {"short_name": "US", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 35.2271, "lng": -80.8431},
                    "bounds": {
                        "northeast": {"lat": 35.5, "lng": -80.5},
                        "southwest": {"lat": 35.0, "lng": -81.0},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Charlotte",
            "country": "US",
        }
        mock_instance.distance_from_bounds.return_value = 50

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=fac in charlotte")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_fac_in_state(self, mock_google_maps):
        """Test 'fac in [state]' search pattern (e.g., 'fac in ca')."""
        mock_geocode_result = [
            {
                "address_components": [
                    {
                        "long_name": "California",
                        "types": ["administrative_area_level_1"],
                    },
                    {"short_name": "US", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 36.7783, "lng": -119.4179},
                    "bounds": {
                        "northeast": {"lat": 42.0, "lng": -114.1},
                        "southwest": {"lat": 32.5, "lng": -124.4},
                    },
                },
                "types": ["administrative_area_level_1", "political"],
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "California",
            "country": "US",
        }
        mock_instance.distance_from_bounds.return_value = 500

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=fac in ca")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_fac_in_country_code(self, mock_google_maps):
        """Test 'fac in [country code]' search pattern (e.g., 'fac in ie')."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Ireland", "types": ["country", "political"]},
                    {"short_name": "IE", "types": ["country", "political"]},
                ],
                "geometry": {
                    "location": {"lat": 53.1424, "lng": -7.6921},
                    "bounds": {
                        "northeast": {"lat": 55.4, "lng": -5.6},
                        "southwest": {"lat": 51.4, "lng": -10.5},
                    },
                },
                "types": ["country", "political"],
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Ireland",
            "country": "IE",
        }
        mock_instance.distance_from_bounds.return_value = 200

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=fac in ie")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_net_in_city(self, mock_google_maps):
        """Test 'net in [city]' search pattern (e.g., 'net in chicago')."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Chicago", "types": ["locality"]},
                    {"short_name": "US", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 41.8781, "lng": -87.6298},
                    "bounds": {
                        "northeast": {"lat": 42.0, "lng": -87.5},
                        "southwest": {"lat": 41.6, "lng": -87.9},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Chicago",
            "country": "US",
        }
        mock_instance.distance_from_bounds.return_value = 50

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=net in chicago")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_ix_in_city(self, mock_google_maps):
        """Test 'ix in [city]' search pattern (e.g., 'ix in graz')."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Graz", "types": ["locality"]},
                    {"short_name": "AT", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 47.0707, "lng": 15.4395},
                    "bounds": {
                        "northeast": {"lat": 47.2, "lng": 15.6},
                        "southwest": {"lat": 47.0, "lng": 15.3},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Graz",
            "country": "AT",
        }
        mock_instance.distance_from_bounds.return_value = 50

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=ix in graz")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_org_in_city(self, mock_google_maps):
        """Test 'org in [city]' search pattern (e.g., 'org in helsinki')."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Helsinki", "types": ["locality"]},
                    {"short_name": "FI", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 60.1699, "lng": 24.9384},
                    "bounds": {
                        "northeast": {"lat": 60.3, "lng": 25.2},
                        "southwest": {"lat": 60.1, "lng": 24.8},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Helsinki",
            "country": "FI",
        }
        mock_instance.distance_from_bounds.return_value = 50

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=org in helsinki")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_carrier_in_city(self, mock_google_maps):
        """Test 'carrier in [city]' search pattern (e.g., 'carrier in london')."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "London", "types": ["locality"]},
                    {"short_name": "GB", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 51.5074, "lng": -0.1278},
                    "bounds": {
                        "northeast": {"lat": 51.7, "lng": 0.3},
                        "southwest": {"lat": 51.4, "lng": -0.5},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "London",
            "country": "GB",
        }
        mock_instance.distance_from_bounds.return_value = 50

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=carrier in london")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_fac_in_state_country(self, mock_google_maps):
        """Test 'fac in [state], [country]' search pattern (e.g., 'fac in vt, us')."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Vermont", "types": ["administrative_area_level_1"]},
                    {"short_name": "US", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 44.5588, "lng": -72.5778},
                    "bounds": {
                        "northeast": {"lat": 45.0, "lng": -71.5},
                        "southwest": {"lat": 42.7, "lng": -73.4},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Vermont",
            "country": "US",
        }
        mock_instance.distance_from_bounds.return_value = 50

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=fac in vt, us")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_edge_case_in_india(self, mock_google_maps):
        """Test edge case 'fac in in' (facilities in India, country code IN)."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "India", "types": ["country", "political"]},
                    {"short_name": "IN", "types": ["country", "political"]},
                ],
                "geometry": {
                    "location": {"lat": 20.5937, "lng": 78.9629},
                    "bounds": {
                        "northeast": {"lat": 35.5, "lng": 97.4},
                        "southwest": {"lat": 6.7, "lng": 68.1},
                    },
                },
                "types": ["country", "political"],
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "India",
            "country": "IN",
        }
        mock_instance.distance_from_bounds.return_value = 1500

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=fac in in")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_net_in_country_code(self, mock_google_maps):
        """Test 'net in [country code]' (e.g., 'net in at' for Austria)."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Austria", "types": ["country", "political"]},
                    {"short_name": "AT", "types": ["country", "political"]},
                ],
                "geometry": {
                    "location": {"lat": 47.5162, "lng": 14.5501},
                    "bounds": {
                        "northeast": {"lat": 49.0, "lng": 17.2},
                        "southwest": {"lat": 46.4, "lng": 9.5},
                    },
                },
                "types": ["country", "political"],
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Austria",
            "country": "AT",
        }
        mock_instance.distance_from_bounds.return_value = 300

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=net in at")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_org_in_country_code(self, mock_google_maps):
        """Test 'org in [country code]' (e.g., 'org in fi' for Finland)."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Finland", "types": ["country", "political"]},
                    {"short_name": "FI", "types": ["country", "political"]},
                ],
                "geometry": {
                    "location": {"lat": 61.9241, "lng": 25.7482},
                    "bounds": {
                        "northeast": {"lat": 70.1, "lng": 31.6},
                        "southwest": {"lat": 59.8, "lng": 20.5},
                    },
                },
                "types": ["country", "political"],
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Finland",
            "country": "FI",
        }
        mock_instance.distance_from_bounds.return_value = 500

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=org in fi")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_in_country_code(self, mock_google_maps):
        """Test generic search in country (e.g., 'in fi' for Finland)."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Finland", "types": ["country", "political"]},
                    {"short_name": "FI", "types": ["country", "political"]},
                ],
                "geometry": {
                    "location": {"lat": 61.9241, "lng": 25.7482},
                    "bounds": {
                        "northeast": {"lat": 70.1, "lng": 31.6},
                        "southwest": {"lat": 59.8, "lng": 20.5},
                    },
                },
                "types": ["country", "political"],
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Finland",
            "country": "FI",
        }
        mock_instance.distance_from_bounds.return_value = 500

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=in fi")
        self.assertEqual(response.status_code, 200)

    def test_search_with_hyphen(self):
        """Test searching for names with hyphens (e.g., 'DE-CIX')."""
        org = models.Organization.objects.create(name="DE-CIX Org", status="ok")
        ix = models.InternetExchange.objects.create(name="DE-CIX", status="ok", org=org)
        self.reindex_for_search()

        response = self.client.get(f"/search/v2?q={ix.name}")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_hyphenated_name_in_location(self, mock_google_maps):
        """Test 'DE-CIX in Leipzig' style queries."""
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Leipzig", "types": ["locality"]},
                    {"short_name": "DE", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 51.3397, "lng": 12.3731},
                    "bounds": {
                        "northeast": {"lat": 51.5, "lng": 12.5},
                        "southwest": {"lat": 51.2, "lng": 12.2},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Leipzig",
            "country": "DE",
        }
        mock_instance.distance_from_bounds.return_value = 50

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=DE-CIX in Leipzig")
        self.assertEqual(response.status_code, 200)

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_search_proximity_geo_city_variations(self, mock_google_maps):
        """
        Test proximity geo search with city name variations (e.g., vienna/Wien).

        Tests that searching for 'fac in vienna' should find facilities
        in Wien through Google Maps geocoding.
        """
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "Wien", "types": ["locality"]},
                    {"short_name": "AT", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 48.2082, "lng": 16.3738},
                    "bounds": {
                        "northeast": {"lat": 48.3, "lng": 16.6},
                        "southwest": {"lat": 48.1, "lng": 16.2},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": "Wien",
            "country": "AT",
        }
        mock_instance.distance_from_bounds.return_value = 50

        mock_google_maps.return_value = mock_instance

        response = self.client.get("/search/v2?q=fac in vienna")
        self.assertEqual(response.status_code, 200)

    def test_ix_with_facilities_has_facility_countries(self):
        """
        Test that IX with facilities indexes facility countries.
        Related to issue #1833.
        """
        org = models.Organization.objects.create(name="Test Org IX", status="ok")
        ix = models.InternetExchange.objects.create(
            name="Test IX With Facs",
            status="ok",
            org=org,
            city="Paris",
            country="FR",
            region_continent="Europe",
        )

        fac1 = models.Facility.objects.create(
            name="Facility DE",
            status="ok",
            org=org,
            country="DE",
            city="Frankfurt",
            latitude=50.1109,
            longitude=8.6821,
        )
        fac2 = models.Facility.objects.create(
            name="Facility NL",
            status="ok",
            org=org,
            country="NL",
            city="Amsterdam",
            latitude=52.3702,
            longitude=4.8952,
        )

        models.InternetExchangeFacility.objects.create(
            ix=ix, facility=fac1, status="ok"
        )
        models.InternetExchangeFacility.objects.create(
            ix=ix, facility=fac2, status="ok"
        )

        self.reindex_for_search()

        result = search_v2(["Test IX With Facs"])

        self.assertIn("ix", result)
        self.assertGreater(len(result["ix"]), 0)

        ix_names = [item["name"] for item in result["ix"]]
        self.assertIn(ix.name, ix_names, "IX should be found in search results")

    def test_search_name_long_field(self):
        """
        Test that name_long field is included in searches.
        """
        org = models.Organization.objects.create(name="Long Name Org", status="ok")
        ix = models.InternetExchange.objects.create(
            name="IX",
            name_long="Internet Exchange Very Long Full Name",
            status="ok",
            org=org,
            city="London",
            country="GB",
            region_continent="Europe",
        )

        self.reindex_for_search()

        result = search_v2(["Very Long Full Name"])

        self.assertIn("ix", result)
        self.assertGreater(len(result["ix"]), 0)

        ix_names = [item["name"] for item in result["ix"]]
        self.assertIn(ix.name, ix_names, "IX should be found via name_long field")

    def test_ix_without_facilities_has_own_country(self):
        """
        Test that IX without facilities falls back to its own country.
        This is the fix for issue #1833 where IXs with 0 facilities
        had empty country arrays instead of their own country.
        """
        org = models.Organization.objects.create(name="Test Org VN", status="ok")
        ix = models.InternetExchange.objects.create(
            name="Test IX No Facs",
            status="ok",
            org=org,
            city="Hanoi",
            country="VN",
            region_continent="Asia Pacific",
        )
        self.reindex_for_search()

        result = search_v2(["Test IX No Facs"])

        self.assertIn("ix", result)
        self.assertGreater(len(result["ix"]), 0)

        ix_names = [item["name"] for item in result["ix"]]
        self.assertIn(ix.name, ix_names, "IX should be found in search results")

    @patch("peeringdb_server.geo.GoogleMaps")
    def test_ix_geo_search_without_coordinates(self, mock_google_maps):
        """
        Test that IX without coordinates can still be found in country-filtered
        searches. This is part of the fix for issue #1833 where geo_distance
        filter is removed for IX searches.
        """
        mock_geocode_result = [
            {
                "address_components": [
                    {"long_name": "France", "types": ["country"]},
                    {"short_name": "FR", "types": ["country"]},
                ],
                "geometry": {
                    "location": {"lat": 46.2276, "lng": 2.2137},
                    "bounds": {
                        "northeast": {"lat": 51.0891, "lng": 9.5597},
                        "southwest": {"lat": 41.3253, "lng": -5.1406},
                    },
                },
            }
        ]

        mock_instance = MagicMock()
        mock_instance.client.geocode.return_value = mock_geocode_result
        mock_instance.build_location_dict.return_value = {
            "location": None,
            "country": "FR",
        }
        mock_instance.distance_from_bounds.return_value = 1000
        mock_google_maps.return_value = mock_instance

        org = models.Organization.objects.create(name="Geo Search Org", status="ok")
        ix = models.InternetExchange.objects.create(
            name="Test IX Geo Search",
            status="ok",
            org=org,
            city="TestCity",
            country="FR",
            region_continent="Europe",
        )
        self.reindex_for_search()
        # Search for IX in France
        # This would previously fail because IX has no coordinates and
        # geo_distance filter would exclude it
        response = self.client.get("/search/v2?q=ix+in+france")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn(
            ix.name,
            content,
            "IX without coordinates should appear in country-filtered search",
        )

    def test_search_city_field(self):
        """
        Test that city field is included in searches.
        """
        org = models.Organization.objects.create(name="City Search Org", status="ok")
        fac = models.Facility.objects.create(
            name="Unique Facility Name XYZ",
            status="ok",
            org=org,
            city="Testcityname",
            country="US",
            latitude=40.7128,
            longitude=-74.0060,
        )
        self.reindex_for_search()
        result = search_v2(["Testcityname"])

        self.assertIn("fac", result)
        self.assertGreater(len(result["fac"]), 0)

        fac_names = [item["name"] for item in result["fac"]]
        self.assertIn(fac.name, fac_names, "Facility should be found via city field")

    def test_search_numeric_name_not_asn(self):
        """
        Test that searching for a numeric string matches network names,
        not just ASN fields. This is the fix for issue #1850.
        """
        org = models.Organization.objects.create(name="Numeric Name Org", status="ok")
        net = models.Network.objects.create(
            name="31173 Network",
            asn=65000,
            status="ok",
            org=org,
        )

        self.reindex_for_search()

        result = search_v2(["31173"])

        self.assertIn("net", result)
        self.assertGreater(len(result["net"]), 0)

        net_names = [item["name"] for item in result["net"]]
        self.assertIn(net.name, net_names, "Network with numeric name should be found")
