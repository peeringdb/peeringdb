import pytest
import json
import uuid
import re

from django.test import Client, TestCase, RequestFactory
from django.contrib.auth.models import Group, AnonymousUser
from django.contrib.auth import get_user
import django_namespace_perms as nsp

import peeringdb_server.views as views
import peeringdb_server.models as models


class ViewTestCase(TestCase):

    entities = ["ix", "net", "fac"]

    @classmethod
    def setUpTestData(cls):
        # create user and guest group

        guest_group = Group.objects.create(name="guest")
        user_group = Group.objects.create(name="user")

        cls.guest_user = models.User.objects.create_user(
            "guest", "guest@localhost", "guest")
        cls.guest_user.set_password("guest")
        guest_group.user_set.add(cls.guest_user)

        # create organizations
        cls.organizations = dict((k,
                                  models.Organization.objects.create(
                                      name="Sponsor Org %s" % k, status="ok"))
                                 for k in ["a", "b", "c", "d"])

        # create sponsorships
        cls.sponsorships = {
            "a": models.Sponsorship.objects.create(
                org=cls.organizations.get("a"), logo="fake.png",
                url="org-a.com", level=1),
            "b": models.Sponsorship.objects.create(
                org=cls.organizations.get("b"), logo="fake.png", level=1),
            "c": models.Sponsorship.objects.create(
                org=cls.organizations.get("c"), logo="fake.png", level=2),
            "d": models.Sponsorship.objects.create(
                org=cls.organizations.get("d"), level=1)
        }

    def setUp(self):
        self.factory = RequestFactory()

    def test_data_view(self):
        c = Client()
        resp = c.get("/data/sponsors", follow=True)
        self.assertEqual(resp.status_code, 200)

        expected = {u'sponsorships': {u'1': {u'id': 1, u'name': u'silver'}, u'3': {u'id': 3, u'name': u'gold'}, u'2': {u'id': 2, u'name': u'silver'}, u'4': {u'id': 4, u'name': u'silver'}}}
        self.assertEqual(resp.json(), expected)

    def test_view(self):
        c = Client()
        resp = c.get("/sponsors", follow=True)
        self.assertEqual(resp.status_code, 200)

        #make sure org a,b and c exist in the sponsors page
        self.assertGreater(resp.content.find(self.organizations["a"].name), -1)
        self.assertGreater(resp.content.find(self.organizations["b"].name), -1)
        self.assertGreater(resp.content.find(self.organizations["c"].name), -1)

        #make sure org d does not exist in the sponsors page
        self.assertEqual(resp.content.find(self.organizations["d"].name), -1)

        #makre sure order is randomized with each view
        i = 0
        rgx = re.compile("fake.png\" alt=\"([^\"]+)\"")
        a = re.findall(rgx, resp.content)
        while i < 100:
            resp = c.get("/sponsors", follow=True)
            b = re.findall(rgx, resp.content)
            self.assertEqual(len(a), len(b))
            if b != a:
                break
            i += 1
        self.assertLess(i, 99)
