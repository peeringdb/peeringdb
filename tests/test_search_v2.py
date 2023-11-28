from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

import peeringdb_server.models as models
import peeringdb_server.search as search


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
