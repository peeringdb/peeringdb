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

        cls.organizations = dict(("{}".format(k),
                                  models.Organization.objects.create(
                                      name="Sponsor Org %s" % k, status="ok"))
                                 for k in range(1,7))

        # create sponsorships

        cls.sponsorships = {
            "1": models.Sponsorship.objects.create(level=1),
            "2": models.Sponsorship.objects.create(level=1),
            "3": models.Sponsorship.objects.create(level=2),
            "4": models.Sponsorship.objects.create(level=1),
            "5_and_6": models.Sponsorship.objects.create(level=3)
        }

        # org sponsorship with logo and url set lvl1

        models.SponsorshipOrganization.objects.create(sponsorship=cls.sponsorships["1"],
                                               org=cls.organizations["1"],
                                               logo="fake.png",
                                               url="org-1.com",)

        # org sponsorship with logo set lvl1

        models.SponsorshipOrganization.objects.create(sponsorship=cls.sponsorships["2"],
                                               org=cls.organizations["2"],
                                               logo="fake.png",)


        # org sponsorship with logo set lvl2

        models.SponsorshipOrganization.objects.create(sponsorship=cls.sponsorships["3"],
                                               org=cls.organizations["3"],
                                               logo="fake.png",)


        # org sponsorship without logo or url set lvl1

        models.SponsorshipOrganization.objects.create(sponsorship=cls.sponsorships["4"],
                                               org=cls.organizations["4"],)


       # two orgs in one sponsorship

        models.SponsorshipOrganization.objects.create(sponsorship=cls.sponsorships["5_and_6"],
                                               org=cls.organizations["5"],
                                               logo="fake.png",
                                               url="org-5.com",)


        models.SponsorshipOrganization.objects.create(sponsorship=cls.sponsorships["5_and_6"],
                                               org=cls.organizations["6"],
                                               logo="fake.png",
                                               url="org-6.com",)


    def setUp(self):
        self.factory = RequestFactory()

    def test_data_view(self):
        c = Client()
        resp = c.get("/data/sponsors", follow=True)
        self.assertEqual(resp.status_code, 200)
        expected = {u'sponsors': {u'1': {u'id': 1, u'name': u'silver'}, u'3': {u'id': 3, u'name': u'gold'}, u'2': {u'id': 2, u'name': u'silver'}, u'5': {u'id': 5, u'name': u'platinum'}, u'4': {u'id': 4, u'name': u'silver'}, u'6': {u'id': 6, u'name': u'platinum'}}}
        self.assertEqual(resp.json(), expected)

    def test_view(self):
        c = Client()
        resp = c.get("/sponsors", follow=True)
        self.assertEqual(resp.status_code, 200)

        #make sure org a,b and c exist in the sponsors page
        self.assertGreater(resp.content.find(self.organizations["1"].name), -1)
        self.assertGreater(resp.content.find(self.organizations["2"].name), -1)
        self.assertGreater(resp.content.find(self.organizations["3"].name), -1)
        self.assertGreater(resp.content.find(self.organizations["5"].name), -1)
        self.assertGreater(resp.content.find(self.organizations["6"].name), -1)

        #make sure org d does not exist in the sponsors page
        self.assertEqual(resp.content.find(self.organizations["4"].name), -1)

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
