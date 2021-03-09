import json
import os

import pytest
from django.core.exceptions import ValidationError
import googlemaps

import peeringdb_server.models as models
from peeringdb_server.serializers import GeocodeSerializerMixin


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
    with pytest.raises(AttributeError):
        fac.reverse_geocode(None, "-1,1")

    with pytest.raises(ValidationError) as exc:
        fac.reverse_geocode(None, None)
    message = "Latitude and longitude must be defined for reverse geocode lookup"
    assert message in str(exc.value)


def test_geo_model_parse_reverse(fac, reverse, reverse_parsed):
    assert fac.parse_reverse_geocode(reverse) == reverse_parsed


def test_need_address_suggestion(fac):
    suggested_address = {
        "name": "Geocode Fac",
        "status": "ok",
        "address1": "New street",
        "address2": "",
        "city": "New York",
        "country": "US",
        "state": "NY",
        "zipcode": "1234",
    }
    geocodeserializer = GeocodeSerializerMixin()
    assert geocodeserializer.needs_address_suggestion(suggested_address, fac)


def test_does_not_need_address_suggestion(fac):
    suggested_address = {
        "name": "Geocode Fac",
        "status": "ok",
        "address1": "Some street",
        "address2": "",
        "city": "Chicago",
        "country": "US",
        "state": "IL",
        "zipcode": "1234",
    }
    geocodeserializer = GeocodeSerializerMixin()
    assert geocodeserializer.needs_address_suggestion(suggested_address, fac) is False
