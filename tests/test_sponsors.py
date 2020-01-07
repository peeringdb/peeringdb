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
            "guest", "guest@localhost", "guest"
        )
        cls.guest_user.set_password("guest")
        guest_group.user_set.add(cls.guest_user)

        # create organizations

        cls.organizations = dict(
            (
                "{}".format(k),
                models.Organization.objects.create(
                    name="Sponsor Org %s" % k, status="ok"
                ),
            )
            for k in range(1, 7)
        )

        # create sponsorships

        cls.sponsorships = {
            "1": models.Sponsorship.objects.create(level=1),
            "2": models.Sponsorship.objects.create(level=1),
            "3": models.Sponsorship.objects.create(level=2),
            "4": models.Sponsorship.objects.create(level=1),
            "5_and_6": models.Sponsorship.objects.create(level=3),
        }

        # org sponsorship with logo and url set lvl1

        models.SponsorshipOrganization.objects.create(
            sponsorship=cls.sponsorships["1"],
            org=cls.organizations["1"],
            logo="fake.png",
            url="org-1.com",
        )

        # org sponsorship with logo set lvl1

        models.SponsorshipOrganization.objects.create(
            sponsorship=cls.sponsorships["2"],
            org=cls.organizations["2"],
            logo="fake.png",
        )

        # org sponsorship with logo set lvl2

        models.SponsorshipOrganization.objects.create(
            sponsorship=cls.sponsorships["3"],
            org=cls.organizations["3"],
            logo="fake.png",
        )

        # org sponsorship without logo or url set lvl1

        models.SponsorshipOrganization.objects.create(
            sponsorship=cls.sponsorships["4"], org=cls.organizations["4"],
        )

        # two orgs in one sponsorship

        models.SponsorshipOrganization.objects.create(
            sponsorship=cls.sponsorships["5_and_6"],
            org=cls.organizations["5"],
            logo="fake.png",
            url="org-5.com",
        )

        models.SponsorshipOrganization.objects.create(
            sponsorship=cls.sponsorships["5_and_6"],
            org=cls.organizations["6"],
            logo="fake.png",
            url="org-6.com",
        )

    def setUp(self):
        self.factory = RequestFactory()

    def test_data_view(self):
        c = Client()
        resp = c.get("/data/sponsors", follow=True)
        self.assertEqual(resp.status_code, 200)
        expected = {
            "sponsors": {
                "1": {"id": 1, "name": "silver"},
                "3": {"id": 3, "name": "gold"},
                "2": {"id": 2, "name": "silver"},
                "5": {"id": 5, "name": "platinum"},
                "4": {"id": 4, "name": "silver"},
                "6": {"id": 6, "name": "platinum"},
            }
        }
        self.assertEqual(resp.json(), expected)

    def test_view(self):
        c = Client()
        resp = c.get("/sponsors", follow=True)
        self.assertEqual(resp.status_code, 200)

        # make sure orgs 1,2,3,5 and 6 exists in the sponsor page
        assert self.organizations["1"].name in resp.content.decode()
        assert self.organizations["2"].name in resp.content.decode()
        assert self.organizations["3"].name in resp.content.decode()
        assert self.organizations["5"].name in resp.content.decode()
        assert self.organizations["6"].name in resp.content.decode()

        # make sure org 4 does not exist in the sponsors page
        assert self.organizations["4"].name not in resp.content.decode()

        # makre sure order is randomized with each view
        i = 0
        rgx = re.compile(r'fake.png" alt="([^"]+)"')
        a = re.findall(rgx, resp.content.decode())
        while i < 100:
            resp = c.get("/sponsors", follow=True)
            b = re.findall(rgx, resp.content.decode())
            self.assertEqual(len(a), len(b))
            if b != a:
                break
            i += 1
        self.assertLess(i, 99)
