import os
import json
import reversion
import requests
import jsonschema
import time
import io
import base64
import pytest_filedata

from django.db import transaction
from django.core.cache import cache
from django.test import TestCase, Client, RequestFactory
from django.core.management import call_command

from peeringdb_server.models import (
    Organization,
    Network,
    NetworkIXLan,
    IXLan,
    IXLanPrefix,
    InternetExchange,
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    User,
)

from peeringdb_server.import_views import (
    view_import_ixlan_ixf_preview,
    view_import_net_ixf_preview,
    view_import_net_ixf_postmortem,
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
        cls.ticket_user = User.objects.create_user("ixf_importer", "ixf_importer@localhost", "ixf_importer")

        cls.org.admin_usergroup.user_set.add(cls.admin_user)

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
