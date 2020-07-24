import json

from django.urls import reverse
from django.test import Client, RequestFactory

import reversion

from peeringdb_server.models import User, Organization
from peeringdb_server import autocomplete_views
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
