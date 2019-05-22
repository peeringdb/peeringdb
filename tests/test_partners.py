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
                                      name="Partner Org %s" % k, status="ok"))
                                 for k in ["a", "b", "c", "d"])

        # create partnerships
        cls.partnerships = {
            "a": models.Partnership.objects.create(
                org=cls.organizations.get("a"), logo="fake.png",
                url="org-a.com", level=1),
            "b": models.Partnership.objects.create(
                org=cls.organizations.get("b"), logo="fake.png", level=1),
            "c": models.Partnership.objects.create(
                org=cls.organizations.get("c"), logo="fake.png", level=2),
            "d": models.Partnership.objects.create(
                org=cls.organizations.get("d"), level=1)
        }

    def setUp(self):
        self.factory = RequestFactory()

    def test_view(self):

        # disable this test until we re-enable the partners page
        return

        c = Client()
        resp = c.get("/partners", follow=True)
        self.assertEqual(resp.status_code, 200)

        #make sure org a,b and c exist in the partners page
        self.assertGreater(resp.content.find(self.organizations["a"].name), -1)
        self.assertGreater(resp.content.find(self.organizations["b"].name), -1)
        self.assertGreater(resp.content.find(self.organizations["c"].name), -1)

        #make sure org d does not exist in the partners page
        self.assertEqual(resp.content.find(self.organizations["d"].name), -1)

        #make sure partnership a url exists in the partners page
        self.assertGreater(resp.content.find(self.partnerships["a"].url), -1)

        #makre sure order is randomized with each view
        i = 0
        rgx = re.compile("fake.png\" alt=\"([^\"]+)\"")
        a = re.findall(rgx, resp.content)
        while i < 100:
            resp = c.get("/partners", follow=True)
            b = re.findall(rgx, resp.content)
            self.assertEqual(len(a), len(b))
            if b != a:
                break
            i += 1
        self.assertLess(i, 99)
