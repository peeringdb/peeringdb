"""
Unit-tests for quick search functionality - note that advanced search is not
tested here as that is using the PDB API entirely.
"""

import datetime
import re

import pytest
import unidecode
from django.core.management import call_command
from django.test import RequestFactory, TestCase

import peeringdb_server.models as models
import peeringdb_server.search as search
import peeringdb_server.views as views


class SearchTests(TestCase):
    """
    Test quick-search functionality
    """

    @classmethod
    def create_instance(cls, model, org, asn=1, prefix="Test", accented=False):
        kwargs = {}
        if model.handleref.tag == "net":
            kwargs = {"asn": asn}

        kwargs.update(status="ok", name=f"{prefix} {model.handleref.tag}")

        if accented:
            kwargs.update(name=f"ãccented {model.handleref.tag}")

        if model.handleref.tag != "org":
            kwargs.update(org=org)

        instance = model.objects.create(**kwargs)

        if model.handleref.tag == "org":
            instance.org_id = instance.id

        return instance

    @classmethod
    def setUpTestData(cls):
        cls.instances = {}
        cls.instances_accented = {}
        cls.instances_sponsored = {}

        # create an instance of each searchable model, so we have something
        # to search for
        cls.org = models.Organization.objects.create(name="Parent org")
        for model in search.autocomplete_models:
            cls.instances[model.handleref.tag] = cls.create_instance(model, cls.org)
            cls.instances_accented[model.handleref.tag] = cls.create_instance(
                model, cls.org, asn=2, accented=True
            )

        # we also need to test that sponsor ship status comes through
        # accordingly
        cls.org_w_sponsorship = models.Organization.objects.create(
            name="Sponsor Parent org", status="ok"
        )

        now = datetime.datetime.now().replace(tzinfo=models.UTC())

        cls.sponsorship = models.Sponsorship.objects.create(
            start_date=now - datetime.timedelta(days=1),
            end_date=now + datetime.timedelta(days=1),
            level=1,
        )
        models.SponsorshipOrganization.objects.create(
            org=cls.org_w_sponsorship, sponsorship=cls.sponsorship
        )

        for model in search.autocomplete_models:
            cls.instances_sponsored[model.handleref.tag] = cls.create_instance(
                model, cls.org_w_sponsorship, asn=3, prefix="Sponsor"
            )

        call_command("rebuild_index", "--noinput")

    def test_search(self):
        """
        search for entities containing 'Test' - this should return all
        instances we created during setUp
        """

        rv = search.search("Test")
        for k, inst in list(self.instances.items()):
            assert k in rv
            assert len(rv[k]) == 1
            assert rv[k][0]["name"] == inst.search_result_name
            assert rv[k][0]["org_id"] == inst.org_id

        # test that term order does not matter

        for k, inst in list(self.instances.items()):
            rv = search.search(f"Test {k}")
            assert k in rv
            assert len(rv[k]) == 1
            assert rv[k][0]["name"] == inst.search_result_name
            assert rv[k][0]["org_id"] == inst.org_id

            rv = search.search(f"{k} Test")
            assert k in rv
            assert len(rv[k]) == 1
            assert rv[k][0]["name"] == inst.search_result_name
            assert rv[k][0]["org_id"] == inst.org_id

        rv = search.search("as1")
        assert len(rv["net"]) == 1
        assert rv["net"][0]["name"] == self.instances["net"].search_result_name
        assert rv["net"][0]["org_id"] == self.instances["net"].org_id

        rv = search.search("asn1")
        assert len(rv["net"]) == 1
        assert rv["net"][0]["name"] == self.instances["net"].search_result_name
        assert rv["net"][0]["org_id"] == self.instances["net"].org_id

    def test_sponsor_badges(self):
        """
        Test that the sponsor badges show up in search result
        """

        factory = RequestFactory()
        request = factory.get("/search", {"q": "Sponsor"})
        response = views.request_search(request)
        m = re.findall(
            re.escape('<a href="/sponsors" class="sponsor silver">'),
            response.content.decode()
            .split('id="search-category-view"')[1]
            .split('id="search-list-view"')[0],
        )

        assert len(m) == 4

    def test_search_case(self):
        """
        search for entities containing 'test' - this should return all
        instances we created during setUp since matching is case-insensitive
        """
        rv = search.search("test")
        for k, inst in list(self.instances.items()):
            assert k in rv
            assert len(rv[k]) == 1
            assert rv[k][0]["name"] == inst.search_result_name

    def test_search_unaccent(self):
        """
        search for entities containing 'ãccented' using accented and unaccented
        terms
        """
        rv = search.search("accented")
        for k, inst in list(self.instances_accented.items()):
            assert k in rv
            assert len(rv[k]) == 1
            assert unidecode.unidecode(rv[k][0]["name"]) == unidecode.unidecode(
                inst.search_result_name
            )

        rv = search.search("ãccented")
        for k, inst in list(self.instances_accented.items()):
            assert k in rv
            assert len(rv[k]) == 1
            assert unidecode.unidecode(rv[k][0]["name"]) == unidecode.unidecode(
                inst.search_result_name
            )

    def test_search_asn_match(self):
        """
        Test that exact numeric match on an ASN
        always appears at the top of the results (#232)
        """

        # network with asn 633 - this should be the first
        # resut when searching for `633`

        net_1 = models.Network.objects.create(
            name="Test ASN Matching", asn=633, org=self.org, status="ok"
        )

        # network with asn 6333, this should match, but not
        # be the first result

        net_2 = models.Network.objects.create(
            name="Test ASN Matching 2", asn=6333, org=self.org, status="ok"
        )

        # network with asn 6334 and 633 as part of its name
        # this should score high, but should not be the first
        # result

        net_3 = models.Network.objects.create(
            name="Test ASN 633 Matching", asn=6334, org=self.org, status="ok"
        )

        # rebuild the index

        call_command("rebuild_index", "--noinput")

        rv = search.search("633")

        assert rv["net"][0]["id"] == net_1.id

        # clean up

        net_1.delete(hard=True)
        net_2.delete(hard=True)
        net_3.delete(hard=True)
        call_command("rebuild_index", "--noinput")

    def test_search_asn_direct(self):
        """
        Test that the new fast matching methods of asn and ip address
        comparisons do not return deleted objects
        """

        org_1 = models.Organization.objects.create(name="Test org 1")
        net_1 = models.Network.objects.create(
            org_id=org_1.id, asn=34532, name="Net 1", status="ok"
        )

        rv = search.search("34532")

        assert rv["net"][0]["id"] == net_1.id

        # soft-delete network, should disappear from results

        net_1.delete()
        rv = search.search("34532")

        assert not rv["net"]

    def test_search_ipv4(self):
        """
        This will test a search for a partial ipv4 address
        """
        org_1 = models.Organization.objects.create(name="Test org 1", status="ok")
        org_2 = models.Organization.objects.create(name="Test org 2", status="ok")
        net_1 = models.Network.objects.create(
            org_id=org_1.id, asn=34532, name="Net 1", status="ok"
        )
        net_2 = models.Network.objects.create(
            org_id=org_2.id, asn=2432, name="Net 2", status="ok"
        )
        ix_1 = models.InternetExchange.objects.create(
            org_id=org_1.id, name="IX 1", status="ok"
        )
        ix_2 = models.InternetExchange.objects.create(
            org_id=org_2.id, name="IX 2", status="ok"
        )
        next_id = models.IXLan.objects.all().order_by("-id").first().id + 1
        ixlan_1 = models.IXLan(id=next_id, ix=ix_1)
        ixlan_2 = models.IXLan(id=next_id + 1, ix=ix_2)
        ixlan_1.save()
        ixlan_2.save()
        netixlan_1 = models.NetworkIXLan.objects.create(
            ipaddr4="8.8.4.4",
            asn=34532,
            ixlan=ixlan_1,
            network=net_1,
            speed=1000,
            status="ok",
        )

        netixlan_2 = models.NetworkIXLan.objects.create(
            ipaddr4="8.8.8.8",
            asn=2432,
            ixlan=ixlan_2,
            network=net_2,
            speed=1000,
            status="ok",
        )

        call_command("rebuild_index", "--noinput")

        rv = search.search("8.8.4")

        assert rv["net"][0]["id"] == net_1.id

        # soft-delete network, should disappear from results
        net_1.delete()
        rv = search.search("8.8.4")
        assert not rv["net"]

        # clean up
        netixlan_1.delete(hard=True)
        netixlan_2.delete(hard=True)
        ix_1.delete(hard=True)
        ix_2.delete(hard=True)
        ixlan_1.delete(hard=True)
        ixlan_2.delete(hard=True)
        net_1.delete(hard=True)
        net_2.delete(hard=True)
        org_1.delete(hard=True)
        org_2.delete(hard=True)

        call_command("rebuild_index", "--noinput")

    def test_search_ipv6(self):
        """
        This will test a search for a partial ipv6 address.
        """
        org_1 = models.Organization.objects.create(name="Test org 1", status="ok")
        org_2 = models.Organization.objects.create(name="Test org 2", status="ok")
        net_1 = models.Network.objects.create(
            org_id=org_1.id, asn=34532, name="Net 1", status="ok"
        )
        net_2 = models.Network.objects.create(
            org_id=org_2.id, asn=2432, name="Net 2", status="ok"
        )
        ix_1 = models.InternetExchange.objects.create(
            org_id=org_1.id, name="IX 1", status="ok"
        )
        ix_2 = models.InternetExchange.objects.create(
            org_id=org_2.id, name="IX 2", status="ok"
        )
        next_id = models.IXLan.objects.all().order_by("-id").first().id + 1
        ixlan_1 = models.IXLan(id=next_id, ix=ix_1)
        ixlan_2 = models.IXLan(id=next_id + 1, ix=ix_2)
        ixlan_1.save()
        ixlan_2.save()
        netixlan_1 = models.NetworkIXLan.objects.create(
            ipaddr6="2001:4888:456:2::",
            asn=34532,
            ixlan=ixlan_1,
            network=net_1,
            speed=1000,
            status="ok",
        )

        netixlan_2 = models.NetworkIXLan.objects.create(
            ipaddr6="2001:4888:432:2::",
            asn=2432,
            ixlan=ixlan_2,
            network=net_2,
            speed=1000,
            status="ok",
        )

        call_command("rebuild_index", "--noinput")

        rv = search.search("2001:4888:456")

        assert rv["net"][0]["id"] == net_1.id

        # soft-delete network, should disappear from results

        net_1.delete()
        rv = search.search("2001:4888:456")

        assert not rv["net"]

        # clean up
        netixlan_1.delete(hard=True)
        netixlan_2.delete(hard=True)
        ix_1.delete(hard=True)
        ix_2.delete(hard=True)
        ixlan_1.delete(hard=True)
        ixlan_2.delete(hard=True)
        net_1.delete(hard=True)
        net_2.delete(hard=True)
        org_1.delete(hard=True)
        org_2.delete(hard=True)

        call_command("rebuild_index", "--noinput")
