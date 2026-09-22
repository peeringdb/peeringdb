"""Metadata validation through authenticated API requests and JSON rendering."""

from rest_framework.test import APIClient

from peeringdb_server.models import Network, Organization, User
from tests.util import ClientCase


class TestMetadataAPI(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org = Organization.objects.create(name="Metadata API org", status="ok")
        cls.owner = User.objects.create_user("metadata_owner", "owner@localhost")
        cls.user_group.user_set.add(cls.owner)
        cls.org.admin_usergroup.user_set.add(cls.owner)
        cls.net = Network.objects.create(
            name="Metadata API net",
            asn=63350,
            org=cls.org,
            status="ok",
            website="https://example.com",
            info_unicast=True,
            meta={"preferred_ip_mtu": 9000},
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

    def test_unknown_key_explanation_reaches_the_client(self):
        response = self.api.put(
            self.url, {**self.payload, "meta": {"unknown_key": True}}, format="json"
        )

        assert response.status_code == 400
        assert response.json()["meta"] == {
            "error": "Bad Request",
            "field_errors": {"meta": {"unknown_key": "unregistered metadata key"}},
        }
        self.net.refresh_from_db()
        assert self.net.meta == {"preferred_ip_mtu": 9000}

    def test_flat_field_validation_explanation_reaches_the_editor(self):
        response = self.api.put(
            self.url,
            {**self.payload, "rtbh_community": "invalid-community"},
            format="json",
        )

        assert response.status_code == 400
        errors = response.json()["meta"]["field_errors"]["meta"]
        assert "rtbh_community" in errors
        assert "community" in str(errors["rtbh_community"])
        self.net.refresh_from_db()
        assert self.net.meta == {"preferred_ip_mtu": 9000}

    def test_non_object_metadata_explanation_reaches_the_client(self):
        response = self.api.put(
            self.url, {**self.payload, "meta": "not-an-object"}, format="json"
        )

        assert response.status_code == 400
        assert response.json()["meta"]["field_errors"]["meta"] == ["must be an object"]

    def test_documented_put_forms_replace_then_merge_metadata(self):
        assert not self.owner.is_superuser
        response = self.api.put(
            self.url,
            {
                **self.payload,
                "meta": {"rtbh_community": "65000:666", "preferred_ip_mtu": 9000},
            },
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.json()["data"][0]["meta"] == {
            "rtbh_community": "65000:666",
            "preferred_ip_mtu": 9000,
        }

        response = self.api.put(
            self.url,
            {**self.payload, "rtbh_community": "65000:777"},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.json()["data"][0]["meta"] == {
            "rtbh_community": "65000:777",
            "preferred_ip_mtu": 9000,
        }
