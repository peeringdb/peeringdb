import py.test
import pytest
import json

from rest_framework.test import APIClient
from django.test import Client, TestCase

from peeringdb_server import maintenance, settings
from peeringdb_server.models import REFTAG_MAP, User
import peeringdb_server.views as views

from util import ClientCase

class TestMaintenanceMode(ClientCase):

    @classmethod
    def setUpTestData(cls):
        super(TestMaintenanceMode, cls).setUpTestData()
        cls.superuser = User.objects.create_user("su","su@localhost","su",is_superuser=True)
        cls.org = REFTAG_MAP["org"].objects.create(name="Test Org",
                                                   status="ok")


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
        assert resp.content.find("maintenance mode") > -1

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
        r = self.client.get("/api/org/1", format="json")
        content = json.loads(r.content)
        assert r.status_code == 200

        # POST should be blocked
        r = self.client.post("/api/net", {
            "org_id": 1,
            "name": "Test net",
            "asn": 9000000
        }, format="json")
        content = json.loads(r.content)
        assert r.status_code == 503
        assert content["meta"]["error"].find(err_str) > -1
        net = {"id": 1}

        # PUT should be blocked
        r = self.client.put("/api/net/{}".format(net["id"]), net,
                            format="json")
        content = json.loads(r.content)
        assert r.status_code == 503
        assert content["meta"]["error"].find(err_str) > -1


        # DELETE should be blocked
        r = self.client.delete("/api/net/{}".format(net["id"]), {},
                               format="json")
        content = json.loads(r.content)
        assert r.status_code == 503
        assert content["meta"]["error"].find(err_str) > -1

        # set maintenance mode off
        maintenance.off()
