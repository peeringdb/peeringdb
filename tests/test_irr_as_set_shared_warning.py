"""
#2036: a network write that lists an AS-SET another active network already lists
is accepted, with a non-blocking warning in the response's meta block.
"""

from unittest import mock

from django.test import override_settings
from rest_framework.test import APIClient

from peeringdb_server.models import Network, Organization, User
from tests.util import ClientCase


@override_settings(IRR_AS_SET_VERIFY_EXISTENCE=False, IRR_AS_SET_REQUIRE_SOURCE=True)
class TestSharedIrrAsSetWarning(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org = Organization.objects.create(name="Shared AS-SET org", status="ok")
        cls.owner = User.objects.create_user("irr_owner", "irr_owner@localhost")
        cls.user_group.user_set.add(cls.owner)
        cls.org.admin_usergroup.user_set.add(cls.owner)
        cls.net = Network.objects.create(
            name="Editing net",
            asn=63360,
            org=cls.org,
            status="ok",
            website="https://example.com",
            irr_as_set="",
        )
        other_org = Organization.objects.create(name="Other org", status="ok")
        cls.other = Network.objects.create(
            name="Other net",
            asn=63361,
            org=other_org,
            status="ok",
            irr_as_set="RADB::AS-OTHER ripe::as-shared",
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.url = f"/api/net/{self.net.pk}"
        self.payload = {
            "name": self.net.name,
            "asn": self.net.asn,
            "org_id": self.org.pk,
            "website": self.net.website,
        }

    def put_irr_as_set(self, value):
        return self.api.put(
            self.url, {**self.payload, "irr_as_set": value}, format="json"
        )

    def test_shared_set_is_saved_with_warning(self):
        response = self.put_irr_as_set("RIPE::AS-SHARED")

        assert response.status_code == 200
        warning = response.json()["meta"]["irr_as_set_warning"]
        assert warning["networks"] == [
            {
                "irr_as_set": "RIPE::AS-SHARED",
                "id": self.other.id,
                "asn": self.other.asn,
                "name": self.other.name,
            }
        ]
        assert "another network" in warning["message"]
        self.net.refresh_from_db()
        assert self.net.irr_as_set == "RIPE::AS-SHARED"

    def test_other_registry_same_name_does_not_warn(self):
        response = self.put_irr_as_set("ARIN::AS-SHARED")

        assert response.status_code == 200
        assert "irr_as_set_warning" not in response.json()["meta"]

    def test_deleted_network_does_not_warn(self):
        Network.objects.filter(id=self.other.id).update(status="deleted")

        response = self.put_irr_as_set("RIPE::AS-SHARED")

        assert response.status_code == 200
        assert "irr_as_set_warning" not in response.json()["meta"]

    def test_pending_network_does_not_warn(self):
        Network.objects.filter(id=self.other.id).update(status="pending")

        response = self.put_irr_as_set("RIPE::AS-SHARED")

        assert response.status_code == 200
        assert "irr_as_set_warning" not in response.json()["meta"]

    def test_unchanged_value_does_not_warn(self):
        Network.objects.filter(id=self.net.id).update(irr_as_set="RIPE::AS-SHARED")

        response = self.put_irr_as_set("RIPE::AS-SHARED")

        assert response.status_code == 200
        assert "irr_as_set_warning" not in response.json()["meta"]

    @mock.patch("peeringdb_server.serializers.ticket_queue_asnauto_skipvq")
    @mock.patch(
        "peeringdb_server.serializers.validate_rdap_user_or_key", return_value=True
    )
    @mock.patch("peeringdb_server.serializers.RdapLookup")
    def test_create_with_shared_set_warns(self, *_mocks):
        response = self.api.post(
            "/api/net",
            {
                "name": "New net",
                "asn": 63362,
                "org_id": self.org.pk,
                "website": "https://example.com",
                "irr_as_set": "RIPE::AS-SHARED",
            },
            format="json",
        )

        assert response.status_code == 201, response.content
        networks = response.json()["meta"]["irr_as_set_warning"]["networks"]
        assert [net["id"] for net in networks] == [self.other.id]

    def test_adding_a_set_reports_kept_shared_set_without_self(self):
        Network.objects.filter(id=self.net.id).update(irr_as_set="RIPE::AS-SHARED")

        response = self.put_irr_as_set("RIPE::AS-SHARED RIPE::AS-NEW")

        assert response.status_code == 200
        networks = response.json()["meta"]["irr_as_set_warning"]["networks"]
        assert [(net["irr_as_set"], net["id"]) for net in networks] == [
            ("RIPE::AS-SHARED", self.other.id)
        ]
