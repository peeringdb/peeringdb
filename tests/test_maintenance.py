import json

import pytest
from django.test import Client, TestCase
from rest_framework.test import APIClient

import peeringdb_server.views as views
from peeringdb_server import maintenance, settings
from peeringdb_server.models import REFTAG_MAP, User

from .util import ClientCase


class TestMaintenanceMode(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.superuser = User.objects.create_user(
            "su", "su@localhost", "su", is_superuser=True
        )
        cls.org = REFTAG_MAP["org"].objects.create(name="Test Org", status="ok")

    @pytest.fixture(autouse=True)
    def init_lockfile(self, tmpdir):
        settings.MAINTENANCE_MODE_LOCKFILE = str(tmpdir.join("maintenance.lock"))

    def test_signup(self):
        """
        user signup should be blocked during maintenance
        """

        maintenance.on()

        client = Client()
        resp = client.post("/register", data={})
        assert resp.status_code == 503
        assert "maintenance mode" in resp.content.decode()

        maintenance.off()

    def test_api(self):
        """
        test that maintenance mode on blocks all write ops to the rest api
        """

        # set maintenance on
        maintenance.on()

        # init api client
        self.client = APIClient()
        self.client.force_authenticate(self.superuser)

        err_str = "in maintenance mode"

        # GET requests should work as expected
        r = self.client.get(f"/api/org/{self.org.id}", format="json")
        content = json.loads(r.content)
        assert r.status_code == 200

        # POST should be blocked
        r = self.client.post(
            "/api/net", {"org_id": 1, "name": "Test net", "asn": 9000000}, format="json"
        )
        content = json.loads(r.content)
        assert r.status_code == 503
        assert err_str in content["meta"]["error"]
        net = {"id": 1}

        # PUT should be blocked
        r = self.client.put("/api/net/{}".format(net["id"]), net, format="json")
        content = json.loads(r.content)
        assert r.status_code == 503
        assert err_str in content["meta"]["error"]

        # DELETE should be blocked
        r = self.client.delete("/api/net/{}".format(net["id"]), {}, format="json")
        content = json.loads(r.content)
        assert r.status_code == 503
        assert err_str in content["meta"]["error"]

        # set maintenance mode off
        maintenance.off()
