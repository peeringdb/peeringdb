import json
import re
import uuid

import pytest
from django.contrib.auth import get_user
from django.contrib.auth.models import AnonymousUser, Group
from django.test import Client, RequestFactory, TestCase

import peeringdb_server.models as models
import peeringdb_server.views as views


class ViewTestCase(TestCase):
    entities = ["ix", "net", "fac"]

    @classmethod
    def setUpTestData(cls):
        # create user and guest group

        guest_group = Group.objects.create(name="guest")
        user_group = Group.objects.create(name="user")

        cls.guest_user = models.User.objects.create_user(
            "guest", "guest@localhost", "guest"
        )
        cls.guest_user.set_password("guest")
        guest_group.user_set.add(cls.guest_user)

        # create organizations
        cls.organizations = {
            k: models.Organization.objects.create(
                name="Partner Org %s" % k, status="ok"
            )
            for k in ["a", "b", "c", "d"]
        }

        # create partnerships
        cls.partnerships = {
            "a": models.Partnership.objects.create(
                org=cls.organizations.get("a"),
                logo="fake.png",
                url="org-a.com",
                level=1,
            ),
            "b": models.Partnership.objects.create(
                org=cls.organizations.get("b"), logo="fake.png", level=1
            ),
            "c": models.Partnership.objects.create(
                org=cls.organizations.get("c"), logo="fake.png", level=2
            ),
            "d": models.Partnership.objects.create(
                org=cls.organizations.get("d"), level=1
            ),
        }

    def setUp(self):
        self.factory = RequestFactory()

    def test_view(self):
        # disable this test until we re-enable the partners page
        return

        c = Client()
        resp = c.get("/partners", follow=True)
        self.assertEqual(resp.status_code, 200)

        # make sure org a,b and c exist in the partners page
        assert self.organizations["a"].name in resp.content.decode()
        assert self.organizations["b"].name in resp.content.decode()
        assert self.organizations["c"].name in resp.content.decode()

        # make sure org d does not exist in the partners page
        assert self.organizations["d"].name not in resp.content.decode()

        # make sure partnership a url exists in the partners page
        assert self.organizations["a"].url in resp.content.decode()

        # makre sure order is randomized with each view
        i = 0
        rgx = re.compile(r'fake.png" alt="([^"]+)"')
        a = re.findall(rgx, resp.content)
        while i < 100:
            resp = c.get("/partners", follow=True)
            b = re.findall(rgx, resp.content)
            self.assertEqual(len(a), len(b))
            if b != a:
                break
            i += 1
        self.assertLess(i, 99)
