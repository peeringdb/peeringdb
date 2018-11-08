"""
Unit-tests for quick search functionality - note that advanced search is not
tested here as that is using the PDB API entirely.
"""

import pytest

from django.test import TestCase

import peeringdb_server.search as search
import peeringdb_server.models as models


class SearchTests(TestCase):
    """
    Test quick-search functionality
    """

    @classmethod
    def setUpTestData(cls):

        # in case other tests updated the search index through object
        # creation we need to flush it
        search.SEARCH_CACHE["search_index"] = {}

        cls.instances = {}
        # create an instance of each searchable model, so we have something
        # to search for
        cls.org = models.Organization.objects.create(name="Test org")
        for model in search.searchable_models:
            if model.handleref.tag == "net":
                kwargs = {"asn": 1}
            else:
                kwargs = {}
            cls.instances[model.handleref.tag] = model.objects.create(
                status="ok", org=cls.org, name="Test %s" % model.handleref.tag,
                **kwargs)

    def test_search(self):
        """
        search for entities containing 'Test' - this should return all
        instances we created during setUp
        """

        rv = search.search("Test")
        for k, inst in self.instances.items():
            assert k in rv
            assert len(rv[k]) == 1
            assert rv[k][0]["name"] == inst.search_result_name

        rv = search.search("as1")
        assert len(rv["net"]) == 1
        assert rv["net"][0]["name"] == self.instances["net"].search_result_name

        rv = search.search("asn1")
        assert len(rv["net"]) == 1
        assert rv["net"][0]["name"] == self.instances["net"].search_result_name

    def test_search_case(self):
        """
        search for entities containing 'test' - this should return all
        instances we created during setUp since matching is case-insensitive
        """
        rv = search.search("test")
        for k, inst in self.instances.items():
            assert k in rv
            assert len(rv[k]) == 1
            assert rv[k][0]["name"] == inst.search_result_name

    def test_index_updates(self):
        """
        test that indexes get updated correctly when objects are created
        or deleted or updated from pending to ok
        """

        # this object will be status pending and should not be returned in the search
        # results
        new_ix_p = models.InternetExchange.objects.create(
            status="pending", org=self.org, name="Test IU ix")
        self.test_search()

        # this object will be status ok, and should show up in the index
        new_ix_o = models.InternetExchange.objects.create(
            status="ok", org=self.org, name="Test IU P ix")
        rv = search.search("test")
        assert len(rv["ix"]) == 2

        # now we switch the first object to ok as well and it as well should show up in the
        # index
        new_ix_p.status = "ok"
        new_ix_p.save()
        rv = search.search("test")
        assert len(rv["ix"]) == 3

        #finally we delete both and they should disappear again
        new_ix_p.delete()
        new_ix_o.delete()
        self.test_search()
