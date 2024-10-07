import json

import reversion
from django.test import Client, RequestFactory
from django.urls import resolve, reverse

from peeringdb_server import autocomplete_views
from peeringdb_server.models import (
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    Network,
    NetworkFacility,
    Organization,
    User,
)

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

    def test_netfac_autocomplete(self):
        org = Organization.objects.create(name="Test Org", status="ok")
        net = Network.objects.create(
            name="Test Network", asn=1000, status="ok", org=org
        )

        fac = Facility.objects.create(name="Test Facility", status="ok", org=org)

        netfac = NetworkFacility.objects.create(network=net, facility=fac, status="ok")

        url = reverse("autocomplete-netfac", kwargs={"net_id": net.id})
        req = self.factory.get(url)
        req.resolver_match = resolve(url)

        rsp = autocomplete_views.NetworkFacilityAutocomplete.as_view()(
            req
        ).content.decode("utf-8")

        assert "Test Facility" in rsp

        # test autocomplte-netfac with filter
        req = self.factory.get(f"{url}?q=Test")
        req.resolver_match = resolve(url)

        rsp = autocomplete_views.NetworkFacilityAutocomplete.as_view()(
            req
        ).content.decode("utf-8")

        assert "Test Facility" in rsp

    def test_ixfac_autocomplete(self):
        org = Organization.objects.create(name="Test Org", status="ok")
        ix = InternetExchange.objects.create(name="First IX", status="ok", org=org)

        fac = Facility.objects.create(name="Test Facility", status="ok", org=org)

        ixfac = InternetExchangeFacility.objects.create(
            ix=ix, facility=fac, status="ok"
        )

        url = reverse("autocomplete-ixfac", kwargs={"ix_id": ix.id})
        req = self.factory.get(url)
        req.resolver_match = resolve(url)

        rsp = autocomplete_views.InternetExchangeFacilityAutoComplete.as_view()(
            req
        ).content.decode("utf-8")

        assert "Test Facility" in rsp

        # test autocomplte-ixfac with filter
        req = self.factory.get(f"{url}?q=Test")
        req.resolver_match = resolve(url)

        rsp = autocomplete_views.InternetExchangeFacilityAutoComplete.as_view()(
            req
        ).content.decode("utf-8")

        assert "Test Facility" in rsp

    def test_autocomplete_sort(self):
        org = Organization.objects.create(name="Test Org", status="ok")

        Network.objects.all().delete()

        # Data for exact matches
        net1 = Network.objects.create(name=f"NET", asn=1, status="ok", org=org)
        # Data for startswith matches
        net2 = Network.objects.create(name=f"NET DUMMY", asn=2, status="ok", org=org)
        # Data for contains matches
        net3 = Network.objects.create(name=f"TEST NET", asn=3, status="ok", org=org)

        url = reverse("autocomplete-net")

        req = self.factory.get(f"{url}?q=NET")
        rsp = autocomplete_views.NetworkAutocomplete.as_view()(req).content.decode(
            "utf-8"
        )

        res = rsp.split("</span>")

        # First result should be exact match
        assert f'data-value="{net1.id}"' in res[0]

        # Second result should be startswith match
        assert f'data-value="{net2.id}"' in res[1]

        # Third result should be contains match
        assert f'data-value="{net3.id}"' in res[2]

    def test_autocomplete_results(self):
        org = Organization.objects.create(name="Test Org", status="ok")

        for i in range(1, 130):
            InternetExchange.objects.create(name=f"IX {i}", status="ok", org=org)

        url = reverse("autocomplete-ix")

        req = self.factory.get(f"{url}?q=IX")
        rsp = autocomplete_views.ExchangeAutocomplete.as_view()(req).content.decode(
            "utf-8"
        )

        assert 129 == rsp.count("data-value")
