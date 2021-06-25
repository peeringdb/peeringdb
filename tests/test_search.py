"""
Unit-tests for quick search functionality - note that advanced search is not
tested here as that is using the PDB API entirely.
"""
import re
import datetime

import pytest
import unidecode

from django.test import TestCase, RequestFactory
from django.core.management import call_command

import peeringdb_server.search as search
import peeringdb_server.models as models
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
        for model in search.searchable_models:
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

        for model in search.searchable_models:
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
            response.content.decode(),
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
