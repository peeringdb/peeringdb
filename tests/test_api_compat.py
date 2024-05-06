import json

import pytest
from rest_framework.test import APIClient, force_authenticate

from peeringdb_server.models import REFTAG_MAP, User

from .test_api import setup_module, teardown_module
from .util import ClientCase


class TestAPIClientCompat(ClientCase):
    expected_unknown_auth_method_err_str = "Unknown authorization method"
    expected_malformed_auth_header_err_str = "Malformed authorization header"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.superuser = User.objects.create_user(
            "su", "neteng@20c.com", "su", is_superuser=True
        )
        cls.org = REFTAG_MAP["org"].objects.create(name="Test Org", status="ok")

    @property
    def expected_compat_err_str(self):
        return "Your client version is incompatible with server version of the api, please install peeringdb>={},<={} {}>={},<={}".format(
            "0.6", "0.6.5", "django_peeringdb", "0.6", "0.6.5"
        )

    def _compat(self, ua_c, ua_be, error):
        if ua_c and ua_be:
            useragent = f"PeeringDB/{ua_c} django_peeringdb/{ua_be}"
            self.client = APIClient(HTTP_USER_AGENT=useragent)
        else:
            self.client = APIClient()
        self.client.force_authenticate(self.superuser)

        org_id = self.org.id
        print(self.org, self.org.id)

        r = self.client.get(f"/api/org/{org_id}", format="json")
        content = json.loads(r.content)
        if error:
            assert r.status_code == 400
            assert content["meta"]["error"] == self.expected_compat_err_str
        else:
            assert r.status_code == 200

        r = self.client.post(
            "/api/net",
            {
                "org_id": org_id,
                "name": "Test net",
                "asn": 9000000,
                "website": "https://www.example.com",
            },
            format="json",
        )
        content = json.loads(r.content)
        print(content)
        if error:
            assert r.status_code == 400
            assert content["meta"]["error"] == self.expected_compat_err_str
            net = {"id": 1}
        else:
            assert r.status_code == 201
            net = content["data"][0]
            del net["org"]

        r = self.client.put("/api/net/{}".format(net["id"]), net, format="json")
        content = json.loads(r.content)
        if error:
            assert r.status_code == 400
            assert content["meta"]["error"] == self.expected_compat_err_str
        else:
            assert r.status_code == 200

        r = self.client.delete("/api/net/{}".format(net["id"]), {}, format="json")
        if error:
            content = json.loads(r.content)
            assert r.status_code == 400
            assert content["meta"]["error"] == self.expected_compat_err_str
        else:
            assert r.status_code == 204

        REFTAG_MAP["net"].objects.all().delete()

    def test_incompatible(self):
        self._compat("0.5.0", "0.4.0", True)
        self._compat("0.6.0", "0.5.0", True)
        self._compat("0.5.0", "0.6.0", True)
        self._compat("0.7.0", "0.6.0", True)
        self._compat("0.6.0", "0.7.0", True)

    def test_compatible(self):
        self._compat("0.6.0", "0.6.0", False)
        self._compat("0.6", "0.6", False)
        self._compat("0.6.1", "0.6.1", False)
        self._compat("0.6", "0.6.1", False)
        self._compat("0.6.1", "0.6", False)
        self._compat(None, None, False)

    def test_auth_header(self):
        # this should return 400 with an unknown authorization method message
        r = self.client.get("/api/net", HTTP_AUTHORIZATION="apikey deadbeef")
        content = json.loads(r.content)

        assert content["meta"]["error"] == self.expected_unknown_auth_method_err_str

        # this should return 400 with an malformed authorization header message
        r = self.client.get("/api/net", HTTP_AUTHORIZATIONS="apikey deadbeef")
        content = json.loads(r.content)

        assert content["meta"]["error"] == self.expected_malformed_auth_header_err_str
