import json
import os

import pytest
from django.core.exceptions import ValidationError

import peeringdb_server.models as models


@pytest.fixture
def org():
    org = models.Organization(name="Geocode Org", status="ok")
    return org


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
    assert fac.geocode_status is False
    assert fac.geocode_date is None


def test_geo_model_geocode_coordinates(fac):
    assert fac.geocode_coordinates is None
    fac.latitude = 41.876212
    fac.longitude = -87.631453
    assert fac.geocode_coordinates == (41.876212, -87.631453)


def test_geo_model_geocode_addresss(fac):
    assert fac.geocode_address == "Some street , Chicago, IL 1234"


def test_geo_model_get_address1(fac):
    data = [{"empty": "empty"}]
    assert fac.get_address1_from_geocode(data) is None

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


@pytest.mark.django_db
def test_round_geo_model_lat_long(org, fac):
    # Per issue 865, we remove the DB limit
    # but add rounding to the clean method

    # Lat and long aren't rounded on save
    fac.latitude = 41.123456789
    fac.longitude = -87.987654321

    # Need a saved org to save a facility
    org.save()
    fac.org_id = org.id
    fac.save()
    assert fac.latitude == 41.123456789
    assert fac.longitude == -87.987654321

    # Lat and long are rounded on clean
    fac.clean()
    fac.save()
    assert fac.latitude == 41.123457
    assert fac.longitude == -87.987654
