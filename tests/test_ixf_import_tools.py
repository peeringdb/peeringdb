import os
import json
import reversion
import requests
import jsonschema
import time
import io
import base64

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

        IXLanPrefix.objects.create(
            ixlan=cls.ixlan, status="ok", prefix="195.69.144.0/22", protocol="IPv4"
        )
        IXLanPrefix.objects.create(
            ixlan=cls.ixlan, status="ok", prefix="2001:7f8:1::/64", protocol="IPv6"
        )

        cls.net = Network.objects.create(
            org=cls.org, status="ok", asn=1000, name="net01"
        )
        cls.net_2 = Network.objects.create(
            org=cls.org, status="ok", asn=1001, name="net02"
        )

        cls.admin_user = User.objects.create_user("admin", "admin@localhost", "admin")

        cls.org.admin_usergroup.user_set.add(cls.admin_user)

    def test_import_preview(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.user = self.admin_user

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        assert response.status_code == 200
        assert json.loads(response.content)["errors"] == [
            "IXF import url not specified"
        ]

    def test_import_preview_basic_auth(self):
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        auth = base64.b64encode(b"admin:admin").decode("utf-8")
        request.META["HTTP_AUTHORIZATION"] = f"Basic {auth}"

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        assert response.status_code == 200
        assert json.loads(response.content)["errors"] == [
            "IXF import url not specified"
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
