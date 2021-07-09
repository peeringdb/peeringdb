import json

import reversion
from django.test import Client, RequestFactory
from django.urls import reverse

from peeringdb_server import autocomplete_views
from peeringdb_server.models import Network, Organization, User

from .util import ClientCase


class TestAutocomplete(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.staff_user = User.objects.create_user(
            "staff", "staff@localhost", "staff", is_staff=True
        )

    def setUp(self):
        self.factory = RequestFactory()

    def test_deleted_versions(self):
        with reversion.create_revision():
            org = Organization.objects.create(name="Test Org", status="ok")
        with reversion.create_revision():
            org.delete()
        with reversion.create_revision():
            org.status = "ok"
            org.save()
        with reversion.create_revision():
            org.delete()

        url = reverse("autocomplete-admin-deleted-versions")

        r = self.factory.get(f"{url}?q=org {org.id}")
        r.user = self.staff_user
        r = autocomplete_views.DeletedVersionAutocomplete.as_view()(r)

        content = json.loads(r.content)

        assert reversion.models.Version.objects.all().count() == 4
        assert len(content.get("results")) == 2

    def test_network_autocomplete(self):
        org = Organization.objects.create(name="Test Org", status="ok")
        net = Network.objects.create(
            name="First Network", asn=1000, status="ok", org=org
        )
        net = Network.objects.create(
            name="Second Network", asn=2000, status="ok", org=org
        )

        url = reverse("autocomplete-net")

        req = self.factory.get(f"{url}?q=First")
        rsp = autocomplete_views.NetworkAutocomplete.as_view()(req).content.decode(
            "utf-8"
        )

        assert "First" in rsp
        assert "Second" not in rsp

        req = self.factory.get(f"{url}?q=1000")
        rsp = autocomplete_views.NetworkAutocomplete.as_view()(req).content.decode(
            "utf-8"
        )

        assert "First" in rsp
        assert "Second" not in rsp

        req = self.factory.get(f"{url}?q=Network")
        rsp = autocomplete_views.NetworkAutocomplete.as_view()(req).content.decode(
            "utf-8"
        )

        assert "First" in rsp
        assert "Second" in rsp
