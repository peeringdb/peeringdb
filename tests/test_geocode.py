import pytest
import json
import uuid
import re

from django.test import Client, TestCase, RequestFactory
from django.contrib.auth.models import Group, AnonymousUser
from django.contrib.auth import get_user
import django_namespace_perms as nsp

import peeringdb_server.models as models


class ViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):

        # create organizations
        cls.organizations = dict((k,
                                  models.Organization.objects.create(
                                      name="Geocode Org %s" % k, status="ok"))
                                 for k in ["a", "b", "c", "d"])

        # create facilities
        cls.facilities = dict(
            (k,
             models.Facility.objects.create(
                 name="Geocode Fac %s" % k, status="ok", org=cls.organizations[
                     k], address1="Some street", address2=k, city="Chicago",
                 country="US", state="IL", zipcode="1234", latitude=1.23,
                 longitude=-1.23, geocode_status=True))
            for k in ["a", "b", "c", "d"])

    def test_base(self):
        self.assertEqual(self.facilities["a"].geocode_address,
                         u"Some street a, Chicago, IL 1234")
        self.assertEqual(self.facilities["a"].geocode_coordinates,
                         (1.23, -1.23))

    def test_change(self):
        self.assertEqual(self.facilities["b"].geocode_status, True)
        self.facilities["b"].address1 = "Another street b"
        self.facilities["b"].save()
        self.assertEqual(self.facilities["b"].geocode_status, False)
        self.assertEqual(self.facilities["c"].geocode_status, True)
        self.facilities["c"].lat = 4567.0
        self.facilities["c"].save()
        self.assertEqual(self.facilities["c"].geocode_status, True)
        self.assertEqual(self.facilities["d"].geocode_status, True)
        self.facilities["d"].website = 'http://www.test.com'
        self.facilities["d"].save()
        self.assertEqual(self.facilities["d"].geocode_status, True)
