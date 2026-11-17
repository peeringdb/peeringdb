import base64
import json
from unittest.mock import patch

import jsonschema
import pytest
import pytest_filedata
from django.core.cache import cache
from django.test import RequestFactory
from grainy.const import PERM_READ

from peeringdb_server import ixf
from peeringdb_server.import_views import (
    view_import_ixlan_ixf_preview,
    view_import_net_ixf_preview,
)
from peeringdb_server.models import (
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkIXLan,
    Organization,
    OrganizationAPIKey,
    User,
    UserAPIKey,
)

from .util import ClientCase


@pytest.mark.xdist_group(name="ixf_import_tests")
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
            self.ixlan.ixf_cache_key,
            {
                "url": self.ixlan.ixf_ixp_member_list_url,
                "data": json.loads(data_ixf_preview_net.json),
            },
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
        for perm in self.org.admin_usergroup.grainy_permissions.all():
            self.org_api_key.grainy_permissions.add_permission(
                perm.namespace, perm.permission
            )

        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.META["HTTP_AUTHORIZATION"] = f"Api-Key {self.org_key}"

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        print(response.content)

        assert response.status_code == 200
        assert json.loads(response.content)["errors"] == [
            "IX-F import url not specified"
        ]

    def assert_preview_refused(self, key):
        """
        The preview answers 403 for `key` and never runs the importer
        """
        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.META["HTTP_AUTHORIZATION"] = f"Api-Key {key}"

        with patch.object(ixf.Importer, "update") as update:
            response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        assert response.status_code == 403, response.content
        update.assert_not_called()
        return json.loads(response.content)

    def test_import_preview_inactive_user_api_key(self):
        """
        The key of a deactivated user is refused like an unknown key (#535)
        """
        self.admin_user.is_active = False
        self.admin_user.save()

        content = self.assert_preview_refused(self.key)
        assert content["non_field_errors"] == ["Invalid API key"]

    def test_import_preview_readonly_user_api_key(self):
        """
        A readonly key does not pass the update check of its user (#535)
        """
        _, readonly_key = UserAPIKey.objects.create_key(
            name="readonly key", user=self.admin_user, readonly=True
        )

        content = self.assert_preview_refused(readonly_key)
        assert content["non_field_errors"] == ["Permission denied"]

    def test_import_preview_readonly_org_api_key(self):
        """
        An org key without update grants is refused, even for an exchange
        of its own organization (#535)
        """
        org_api_key, readonly_key = OrganizationAPIKey.objects.create_key(
            name="readonly org key", org=self.org, email="test@example.com"
        )
        org_api_key.grainy_permissions.add_permission(
            self.org.grainy_namespace, PERM_READ
        )

        content = self.assert_preview_refused(readonly_key)
        assert content["non_field_errors"] == ["Permission denied"]

    def test_import_preview_org_api_key_other_org(self):
        """
        An org key with full grants on its own organization is refused for
        an exchange of another organization
        """
        other_org = Organization.objects.create(name="Other Test Org", status="ok")
        org_api_key, other_key = OrganizationAPIKey.objects.create_key(
            name="other org key", org=other_org, email="test@example.com"
        )
        for perm in other_org.admin_usergroup.grainy_permissions.all():
            org_api_key.grainy_permissions.add_permission(
                perm.namespace, perm.permission
            )

        self.assert_preview_refused(other_key)

    def test_import_preview_admin_due_for_reauth(self):
        """
        An exchange admin whose organization requires periodic
        re-authentication, and who has not re-confirmed an email address, is
        refused through a session, as on the REST API (#535)
        """
        self.org.periodic_reauth = True
        self.org.periodic_reauth_period = "1y"
        self.org.save()

        request = RequestFactory().get(f"/import/ixlan/{self.ixlan.id}/ixf/preview/")
        request.user = self.admin_user

        with patch.object(ixf.Importer, "update") as update:
            response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        assert response.status_code == 403, response.content
        update.assert_not_called()
