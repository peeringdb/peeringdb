from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase

import peeringdb_server.models as models
import peeringdb_server.search as search
import peeringdb_server.views as views
from peeringdb_server.search_v2 import (
    add_and_between_keywords,
    build_geo_filter,
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


class SearchV2TestCase(TestCase):
    @classmethod
    def setUpTestData(self):
        call_command("pdb_generate_test_data", limit=2, commit=True)
        for model in [
            models.InternetExchange,
            models.Network,
            models.Facility,
            models.Organization,
            models.Campus,
            models.Carrier,
        ]:
            search_result = {
                "took": 1,
                "timed_out": False,
                "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                "hits": {
                    "total": {"value": model.objects.count(), "relation": "eq"},
                    "max_score": 1.0,
                    "hits": [],
                },
            }
            for id, obj in enumerate(model.objects.all()):
                hits = {
                    "_index": model._handleref.tag,
                    "_type": "_doc",
                    "_id": id + 1,
                    "_score": 1.0,
                    "_source": {
                        "name": obj.name,
                        "status": "ok",
                    },
                }
                if model._handleref.tag != "org":
                    hits["_source"].update(
                        {"org": {"id": obj.org.id, "name": obj.org.name}}
                    )
                    if model._handleref.tag == "net":
                        hits["_source"].update({"asn": obj.asn})
                search_result["hits"]["hits"].append(hits)
            setattr(self, f"{model._handleref.tag}_result", search_result)

    def setUp(self):
        search.ELASTICSEARCH_URL = "https://test:9200"
        self.indexes = ["fac", "ix", "net", "org", "campus", "carrier"]

    def tearDown(self):
        search.ELASTICSEARCH_URL = ""

    @patch("elasticsearch.Elasticsearch.search")
    def test_search_ix(self, mock_search):
        mock_search.return_value = self.ix_result
        response = self.client.get(
            "/search/v2?q=ix",
        )
        self.assertIn(
            f'<div class="view_title">Exchanges ({models.InternetExchange.objects.count()})</div>',
            response.content.decode("utf-8"),
        )
        for id, obj in enumerate(models.InternetExchange.objects.all()):
            self.assertIn(
                f'<a href="/ix/{id+1}">{obj.name}</a>', response.content.decode("utf-8")
            )
        self.assertEqual(response.status_code, 200)

    @patch("elasticsearch.Elasticsearch.search")
    def test_search_net(self, mock_search):
        mock_search.return_value = self.net_result
        response = self.client.get(
            "/search/v2?q=net",
        )
        self.assertIn(
            f'<div class="view_title">Networks ({models.Network.objects.count()})</div>',
            response.content.decode("utf-8"),
        )
        for id, obj in enumerate(models.Network.objects.all()):
            self.assertIn(
                f'<a href="/net/{id+1}">{obj.name} ({obj.asn})</a>',
                response.content.decode("utf-8"),
            )
        self.assertEqual(response.status_code, 200)

    @patch("elasticsearch.Elasticsearch.search")
    def test_search_fac(self, mock_search):
        mock_search.return_value = self.fac_result
        response = self.client.get(
            "/search/v2?q=fac",
        )
        self.assertIn(
            f'<div class="view_title">Facilities ({models.Facility.objects.count()})</div>',
            response.content.decode("utf-8"),
        )
        for id, obj in enumerate(models.Facility.objects.all()):
            self.assertIn(
                f'<a href="/fac/{id+1}">{obj.name}</a>',
                response.content.decode("utf-8"),
            )
        self.assertEqual(response.status_code, 200)

    @patch("elasticsearch.Elasticsearch.search")
    def test_search_org(self, mock_search):
        mock_search.return_value = self.org_result
        response = self.client.get(
            "/search/v2?q=org",
        )
        self.assertIn(
            f'<div class="view_title">Organizations ({models.Organization.objects.count()})</div>',
            response.content.decode("utf-8"),
        )
        for id, obj in enumerate(models.Organization.objects.all()):
            self.assertIn(
                f'<a href="/org/{id+1}">{obj.name}</a>',
                response.content.decode("utf-8"),
            )
        self.assertEqual(response.status_code, 200)

    @patch("elasticsearch.Elasticsearch.search")
    def test_search_campus(self, mock_search):
        mock_search.return_value = self.campus_result
        response = self.client.get(
            "/search/v2?q=campus",
        )
        self.assertIn(
            f'<div class="view_title">Campus ({models.Campus.objects.count()})</div>',
            response.content.decode("utf-8"),
        )
        for id, obj in enumerate(models.Campus.objects.all()):
            self.assertIn(
                f'<a href="/campus/{id+1}">{obj.name}</a>',
                response.content.decode("utf-8"),
            )
        self.assertEqual(response.status_code, 200)

    @patch("elasticsearch.Elasticsearch.search")
    def test_search_carrier(self, mock_search):
        mock_search.return_value = self.carrier_result
        response = self.client.get(
            "/search/v2?q=carrier",
        )
        self.assertIn(
            f'<div class="view_title">Carriers ({models.Carrier.objects.count()})</div>',
            response.content.decode("utf-8"),
        )
        for id, obj in enumerate(models.Carrier.objects.all()):
            self.assertIn(
                f'<a href="/carrier/{id+1}">{obj.name}</a>',
                response.content.decode("utf-8"),
            )
        self.assertEqual(response.status_code, 200)

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

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_elasticsearch_proximity_entity(self, mock_elasticsearch):
        mock_es = mock_elasticsearch.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_index": "fac",
                        "_id": "123",
                        "_source": {"name": "facility a"},
                    }
                ],
            }
        }

        result = elasticsearch_proximity_entity("facility a")
        self.assertEqual(result, {"name": "facility a", "ref_tag": "fac", "id": "123"})

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_elasticsearch_proximity_entity_no_results(self, mock_elasticsearch):
        mock_es = mock_elasticsearch.return_value
        mock_es.search.return_value = {"hits": {"total": {"value": 0}, "hits": []}}

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
            "*fac*", valid_geo, self.indexes, ipv6_construct=False
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
            "not indexes", valid_geo, self.indexes, ipv6_construct=False
        )
        expected = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "bool": {
                                "should": [
                                    {
                                        "match_phrase": {
                                            "name": {
                                                "query": "not indexes",
                                                "boost": 10.0,
                                            }
                                        }
                                    },
                                    {
                                        "match_phrase_prefix": {
                                            "name": {
                                                "query": "not indexes",
                                                "boost": 5.0,
                                            }
                                        }
                                    },
                                    {
                                        "query_string": {
                                            "query": "not indexes",
                                            "fields": ["name"],
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
        result = construct_query_body("", valid_geo, self.indexes, ipv6_construct=False)
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

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_search_v2_with_or(self, mock_elasticsearch):
        self.maxDiff = None

        expected_result = {
            "fac": [
                {
                    "id": "2",
                    "name": "Facility B",
                    "org_id": 100,
                    "sub_name": None,
                    "extra": {"_score": 10, "_score_explanation": {}},
                },
                {
                    "id": "1",
                    "name": "Facility A",
                    "org_id": 100,
                    "sub_name": None,
                    "extra": {"_score": 10, "_score_explanation": {}},
                },
            ],
            "ix": [],
            "net": [],
            "org": [],
            "campus": [],
            "carrier": [],
        }

        mock_es = mock_elasticsearch.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 2, "relation": "eq"},
                "hits": [
                    {
                        "_index": "fac",
                        "_id": "1",
                        "_score": 10,
                        "_source": {
                            "name": "Facility A",
                            "org": {"id": 100, "name": "Org One"},
                            "status": "ok",
                        },
                    },
                    {
                        "_index": "fac",
                        "_id": "2",
                        "_score": 10,
                        "_source": {
                            "name": "Facility B",
                            "org": {"id": 100, "name": "Org One"},
                            "status": "ok",
                        },
                    },
                ],
            }
        }

        result = search_v2(["Facility A OR Facility B"])

        self.assertEqual(result, expected_result)

    @patch("peeringdb_server.search_v2.new_elasticsearch")
    def test_search_v2_ipv6(self, mock_elasticsearch):
        expected_result = {
            "fac": [],
            "ix": [
                {
                    "id": "1",
                    "name": "Test IX",
                    "org_id": 100,
                    "sub_name": None,
                    "extra": {"_score": 10, "_score_explanation": {}},
                }
            ],
            "net": [],
            "org": [],
            "campus": [],
            "carrier": [],
        }

        mock_es = mock_elasticsearch.return_value
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [
                    {
                        "_index": "ix",
                        "_id": "1",
                        "_score": 10,
                        "_source": {
                            "name": "Test IX",
                            "org": {"id": 100, "name": "Test Organization"},
                            "ipaddr6": "2001:db8:85a3::8a2e:370:7334",
                            "status": "ok",
                        },
                    }
                ],
            }
        }

        result = search_v2(["2001:db8:85a3::8a2e:370:7334"])
        self.assertEqual(result, expected_result)
