import pytest
import json
import re
import os

from django.test import Client, TestCase, RequestFactory
from django.contrib.auth.models import Group, AnonymousUser
from django.contrib.auth import get_user
from django.core.management import call_command
from django.core.exceptions import ValidationError

import peeringdb_server.models as models


# class ViewTestCase(TestCase):
#     @classmethod
#     def setUpTestData(cls):

#         # create organizations
#         cls.organizations = {
#             k: models.Organization.objects.create(
#                 name="Geocode Org %s" % k, status="ok"
#             )
#             for k in ["a", "b", "c", "d"]
#         }

#         # create facilities
#         cls.facilities = {
#             k: models.Facility.objects.create(
#                 name=f"Geocode Fac {k}",
#                 status="ok",
#                 org=cls.organizations[k],
#                 address1="Some street",
#                 address2=k,
#                 city="Chicago",
#                 country="US",
#                 state="IL",
#                 zipcode="1234",
#                 latitude=1.23,
#                 longitude=-1.23,
#                 geocode_status=True,
#             )
#             for k in ["a", "b", "c", "d"]
#         }

#     def test_base(self):
#         self.assertEqual(
#             self.facilities["a"].geocode_address, "Some street a, Chicago, IL 1234"
#         )
#         self.assertEqual(self.facilities["a"].geocode_coordinates, (1.23, -1.23))

#     def test_change(self):
#         self.assertEqual(self.facilities["b"].geocode_status, True)
#         self.facilities["b"].address1 = "Another street b"
#         self.facilities["b"].save()
#         self.assertEqual(self.facilities["b"].geocode_status, False)
#         self.assertEqual(self.facilities["c"].geocode_status, True)
#         self.facilities["c"].lat = 4567.0
#         self.facilities["c"].save()
#         self.assertEqual(self.facilities["c"].geocode_status, True)
#         self.assertEqual(self.facilities["d"].geocode_status, True)
#         self.facilities["d"].website = "http://www.test.com"
#         self.facilities["d"].save()
#         self.assertEqual(self.facilities["d"].geocode_status, True)

#     def test_command(self):
#         self.assertEqual(self.facilities["a"].geocode_status, True)

#         # change address to flag facility for geocoding

#         self.facilities["a"].address1 = "Another street a"

#         # test unicode output from command by adding special characters
#         # to the new address

#         self.facilities["a"].name = "sdílených služeb"
#         self.facilities["a"].save()

#         out = io.StringIO()
#         call_command("pdb_geosync", "fac", limit=1, stdout=out)
#         out = out.getvalue()

#         assert "[fac 1/1 ID:1]" in out

@pytest.fixture
def fac():
    fac = models.Facility(
        name="Geocode Fac",
        status="ok",
        address1="Some street",
        address2="",
        city="Chicago",
        country="US",
        state="IL",
        zipcode="1234",
    )
    return fac


def load_json(filename):
    with open(
        os.path.join(
            os.path.dirname(__file__),
            "data",
            "geo",
            f"{filename}.json",
        ),
    ) as fh:
        json_data = json.load(fh)
    return json_data


@pytest.fixture
def reverse():
    return load_json("reverse")


@pytest.fixture
def reverse_parsed():
    return load_json("reverse_parsed")


def test_geo_model_defaults(fac):
    assert fac.geocode_status == False
    assert fac.geocode_date == None


def test_geo_model_geocode_coordinates(fac):
    assert fac.geocode_coordinates == None
    fac.latitude = 41.876212
    fac.longitude = -87.631453
    assert fac.geocode_coordinates == (41.876212, -87.631453)


def test_geo_model_geocode_addresss(fac):
    assert fac.geocode_address == "Some street , Chicago, IL 1234"


def test_geo_model_get_address1(fac):
    data = [{"empty": "empty"}]
    assert fac.get_address1_from_geocode(data) == None

    data = load_json("address1_test0")
    assert fac.get_address1_from_geocode(data) == "427 S LaSalle St"

    data = load_json("address1_test1")
    assert fac.get_address1_from_geocode(data) == "427"

    data = load_json("address1_test2")
    assert fac.get_address1_from_geocode(data) == "S LaSalle St"


def test_geo_model_reverse_geocode_blank(fac):
    with pytest.raises(ValidationError) as exc:
        fac.reverse_geocode(None)
    message = "Latitude and longitude must be defined for reverse geocode lookup"
    assert message in str(exc.value)


def test_geo_model_parse_reverse(fac, reverse, reverse_parsed):
    assert fac.parse_reverse_geocode(reverse) == reverse_parsed



