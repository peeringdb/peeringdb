import json
import uuid

import pytest
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.auth.models import AnonymousUser, Group
from django.test import Client, RequestFactory, TestCase
from django_grainy.models import GroupPermission, UserPermission

import peeringdb_server.models as models
import peeringdb_server.views as views

from .util import ClientCase


class ViewTestCase(ClientCase):

    entities = ["ix", "net", "fac"]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # create test users
        for name in [
            "org_admin",
            "user_a",
            "user_b",
            "user_c",
            "user_d",
            "user_e",
            "user_f",
        ]:
            setattr(
                cls,
                name,
                models.User.objects.create_user(name, "%s@localhost" % name, name),
            )
            getattr(cls, name).set_password(name)
            cls.user_group.user_set.add(getattr(cls, name))

        # create test org
        cls.org = models.Organization.objects.create(name="Test org", status="ok")
        cls.org_other = models.Organization.objects.create(
            name="Test org other", status="ok"
        )

        # create test entities
        for tag in cls.entities:
            kwargs = {"name": "Test %s" % tag, "status": "ok", "org": cls.org}
            if tag == "net":
                kwargs.update(asn=1)
            setattr(cls, tag, models.REFTAG_MAP[tag].objects.create(**kwargs))

        # add org_admin user to org as admin
        cls.org.admin_usergroup.user_set.add(cls.org_admin)

        # add user_a user to org as member
        cls.org.usergroup.user_set.add(cls.user_a)
        cls.org_other.usergroup.user_set.add(cls.user_b)

    def setUp(self):
        self.factory = RequestFactory()

    def run_view_test(self, reftag):
        id = getattr(self, reftag).id
        # test #1 - not logged in
        c = Client()
        resp = c.get("/%s/%d" % (reftag, id), follow=True)
        self.assertEqual(resp.status_code, 200)

        # test #2 - guest logged in (not affiliated to any org)
        c = Client()
        c.login(username="guest", password="guest")
        resp = c.get("/%s/%d" % (reftag, id), follow=True)
        self.assertEqual(resp.status_code, 200)

        # test #3 - user logged in
        c = Client()
        c.login(username="user_a", password="user_a")
        resp = c.get("/%s/%d" % (reftag, id), follow=True)
        self.assertEqual(resp.status_code, 200)


class TestExchangeView(ViewTestCase):
    def test_view(self):
        self.run_view_test("ix")


class TestFacilityView(ViewTestCase):
    def test_view(self):
        self.run_view_test("fac")


class TestOrgView(ViewTestCase):
    def test_view(self):
        self.run_view_test("org")


class TestNetworkView(ViewTestCase):
    @classmethod
    def setUpTestData(cls):
        ViewTestCase.setUpTestData()
        # Create PoCs
        models.NetworkContact.objects.create(
            network=cls.net,
            visible="Users",
            name="Contact Users",
            phone="12345",
            email="a@a.a",
            status="ok",
        )
        models.NetworkContact.objects.create(
            network=cls.net,
            visible="Public",
            name="Contact Public",
            phone="12345",
            email="a@a.a",
            status="ok",
        )
        models.NetworkContact.objects.create(
            network=cls.net,
            visible="Private",
            name="Contact Private",
            phone="12345",
            email="a@a.a",
            status="ok",
        )

    def test_view(self):
        self.run_view_test("net")

    def test_poc_notify(self):
        """
        Test that viewers are notified if PoCs are hidden from them
        """

        TEXT_NOT_LOGGED_IN = "Some of this network's contacts are hidden because they are only visible to authenticated users and you are currently not logged in."
        TEXT_NOT_VERIFIED = "Some of this network's contacts are hidden because your user account is not affiliated with any organization."

        self.assertEqual(models.NetworkContact.objects.all().count(), 3)

        # test #1 - not logged in
        c = Client()
        resp = c.get("/net/%d" % self.net.id, follow=True)
        content = resp.content.decode("utf-8")
        self.assertEqual(resp.status_code, 200)
        assert resp.status_code == 200
        assert TEXT_NOT_LOGGED_IN in content
        assert "Contact Public" in content
        assert "Contact Private" not in content
        assert "Contact Users" not in content

        # test #2 - guest logged in (not affiliated to any org)
        c = Client()
        c.login(username="guest", password="guest")
        resp = c.get("/net/%d" % self.net.id)
        content = resp.content.decode("utf-8")
        assert resp.status_code == 200
        assert TEXT_NOT_VERIFIED in content
        assert "Contact Public" in content
        assert "Contact Private" not in content
        assert "Contact Users" not in content

        # test #3 - user logged in
        c = Client()
        c.login(username="user_a", password="user_a")
        resp = c.get("/net/%d" % self.net.id)
        content = resp.content.decode("utf-8")
        assert resp.status_code == 200
        assert TEXT_NOT_LOGGED_IN not in content
        assert TEXT_NOT_VERIFIED not in content

        assert "Contact Public" in content
        assert "Contact Private" in content
        assert "Contact Users" in content

    def test_search_asn_redirect(self):
        """
        When the user types AS*** or ASN*** and hits enter, if
        a result is found it should redirect directly to the result
        """

        c = Client()

        for q in ["as1", "asn1", "AS1", "ASN1"]:
            resp = c.get(f"/search?q={q}", follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.redirect_chain, [(f"/net/{self.net.id}", 302)])
