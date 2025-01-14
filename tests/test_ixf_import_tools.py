import base64
import io
import json
import os
import time

import jsonschema
import pytest_filedata
import requests
import reversion
from django.core.cache import cache
from django.core.management import call_command
from django.db import transaction
from django.test import Client, RequestFactory, TestCase

from peeringdb_server.import_views import (
    view_import_ixlan_ixf_preview,
    view_import_net_ixf_postmortem,
    view_import_net_ixf_preview,
)
from peeringdb_server.models import (
    InternetExchange,
    IXLan,
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    IXLanPrefix,
    Network,
    NetworkIXLan,
    Organization,
    OrganizationAPIKey,
    User,
    UserAPIKey,
)

from .util import ClientCase


class TestImportPreview(ClientCase):
    """
    Test the ixf import preview
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org = Organization.objects.create(name="Test Org", status="ok")
        cls.ix = InternetExchange.objects.create(
            name="Test IX", status="ok", org=cls.org
        )

        cls.ixlan = cls.ix.ixlan
        cls.ixlan.ixf_ixp_import_enabled = True
        cls.ixlan.save()

        IXLanPrefix.objects.create(
            ixlan=cls.ixlan, status="ok", prefix="195.69.144.0/22", protocol="IPv4"
        )
        IXLanPrefix.objects.create(
            ixlan=cls.ixlan, status="ok", prefix="2001:7f8:1::/64", protocol="IPv6"
        )

        cls.net = Network.objects.create(
            org=cls.org, status="ok", asn=1000, name="net01", allow_ixp_update=True
        )
        cls.net_2 = Network.objects.create(
            org=cls.org, status="ok", asn=1001, name="net02", allow_ixp_update=True
        )

        NetworkIXLan.objects.create(
            ixlan=cls.ixlan,
            network=cls.net,
            ipaddr4="195.69.144.20",
            status="ok",
            asn=cls.net.asn,
            speed=1000,
        )

        cls.admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        cls.ticket_user = User.objects.create_user(
            "ixf_importer", "ixf_importer@localhost", "ixf_importer"
        )

        cls.org.admin_usergroup.user_set.add(cls.admin_user)

        cls.api_key, cls.key = UserAPIKey.objects.create_key(
            name="Test API Key", user=cls.admin_user
        )

        cls.org_api_key, cls.org_key = OrganizationAPIKey.objects.create_key(
            name="Test Org API Key", org=cls.org, email="test@example.com"
        )

    def test_import_preview_net(self):
        data_ixf_preview_net = pytest_filedata.get_data("data_ixf_preview_net")[
            "test_0"
        ]

        self.ixlan.ixf_ixp_member_list_url = "https://localhost"
        self.ixlan.save()

        cache.set(
            f"IXF-CACHE-{self.ixlan.ixf_ixp_member_list_url}",
            json.loads(data_ixf_preview_net.json),
            timeout=None,
        )

        request = RequestFactory().get(f"/import/net/{self.net.id}/ixf/preview/")
        request.user = self.admin_user

        response = view_import_net_ixf_preview(request, self.net.id)

        data_ixf_preview_net.expected["data"][0]["peer"].update(
            ixlan_id=self.ixlan.id,
            ix_id=self.ixlan.id,
            net_id=self.net.id,
        )

        data_ixf_preview_net.expected["data"][1]["peer"].update(
            ixlan_id=self.ixlan.id,
            ix_id=self.ixlan.id,
            net_id=self.net.id,
        )

        assert response.status_code == 200
        assert (
            json.loads(response.content.decode("utf8")) == data_ixf_preview_net.expected
        )

    def test_import_preview_no_url(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.user = self.admin_user

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        assert response.status_code == 200
        assert json.loads(response.content)["errors"] == [
            "IX-F import url not specified"
        ]

    def test_import_preview_basic_auth(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        auth = base64.b64encode(b"admin:admin").decode("utf-8")
        request.META["HTTP_AUTHORIZATION"] = f"Basic {auth}"

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        print(response.content)

        assert response.status_code == 200
        assert json.loads(response.content)["errors"] == [
            "IX-F import url not specified"
        ]

    def test_import_preview_fail_ratelimit(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.user = self.admin_user

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)
        assert response.status_code == 200

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)
        assert response.status_code == 400

    def test_import_preview_fail_permission(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.user = self.guest_user

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)
        assert response.status_code == 403

    def test_import_net_preview(self):
        request = RequestFactory().get(f"/import/net/{self.net.id}/ixf/preview/")
        request.user = self.admin_user

        response = view_import_net_ixf_preview(request, self.net.id)

        assert response.status_code == 200

    def test_import_net_preview_basic_auth(self):
        request = RequestFactory().get(f"/import/net/{self.net.id}/ixf/preview/")
        auth = base64.b64encode(b"admin:admin").decode("utf-8")
        request.META["HTTP_AUTHORIZATION"] = f"Basic {auth}"
        response = view_import_net_ixf_preview(request, self.net.id)

        assert response.status_code == 200

    def test_import_net_preview_fail_ratelimit(self):
        request = RequestFactory().get(f"/import/net/{self.net.id}/ixf/preview/")
        request.user = self.admin_user

        response = view_import_net_ixf_preview(request, self.net.id)
        assert response.status_code == 200

        response = view_import_net_ixf_preview(request, self.net.id)
        assert response.status_code == 400

    def test_import_net_preview_fail_permission(self):
        request = RequestFactory().get(f"/import/net/{self.net.id}/ixf/preview/")
        request.user = self.guest_user

        response = view_import_net_ixf_preview(request, self.net.id)
        assert response.status_code == 403

    def test_import_preview_api_key_auth(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.META["HTTP_AUTHORIZATION"] = f"Api-Key {self.key}"

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        print(response.content)

        assert response.status_code == 200
        assert json.loads(response.content)["errors"] == [
            "IX-F import url not specified"
        ]

    def test_import_preview_invalid_api_key(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.META["HTTP_AUTHORIZATION"] = "Api-Key invalid_key"

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        print(response.content)

        assert response.status_code == 403
        assert json.loads(response.content)["non_field_errors"] == ["Invalid API key"]

    def test_import_preview_valid_org_api_key(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.META["HTTP_AUTHORIZATION"] = f"Api-Key {self.org_api_key}"

        request.org = self.org
        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        print(response.content)

        assert response.status_code == 200
        assert json.loads(response.content)["errors"] == [
            "IX-F import url not specified"
        ]
