import json
import os

import googlemaps
import pytest
from django.core.exceptions import ValidationError

import peeringdb_server.geo as geo
import peeringdb_server.models as models
from peeringdb_server.serializers import GeocodeSerializerMixin


class MockMelissa(geo.Melissa):
    def __init__(self):
        super().__init__("")

    def global_address(self, **kwargs):

        return {
            "Records": [
                {
                    "Results": "AV25",
                    "FormattedAddress": "address 1;address 2;city",
                    "AdministrativeArea": "state",
                    "AddressLine1": "address 1",
                    "AddressLine2": "address 2",
                    "Locality": "city",
                    "PostalCode": "12345",
                    "Latitude": 1.234567,
                    "Longitude": 1.234567,
                }
            ]
        }


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


def test_melissa_global_address_params():
    client = geo.Melissa("")

    expected = {
        "a1": "address 1",
        "a2": "address 2",
        "ctry": "us",
        "loc": "city",
        "postal": "12345",
    }

    assert (
        client.global_address_params(
            address1="address 1",
            address2="address 2",
            country="us",
            city="city",
            zipcode="12345",
        )
        == expected
    )


def test_melissa_global_address_best_result():
    client = geo.Melissa("")

    expected = {"Results": "AV25", "Address1": "value1"}

    result = {"Records": [expected, {"Results": "AV25", "Address1": "value2"}]}

    assert client.global_address_best_result(result) == expected
    assert client.global_address_best_result({}) == None
    assert client.global_address_best_result(None) == None

    result = {"Records": [{"Results": "AV12", "Address1": "value2"}]}

    assert client.global_address_best_result(result) == None


def test_melissa_apply_global_address():

    client = geo.Melissa("")

    data = client.apply_global_address(
        {
            "address1": "address1 old",
            "city": "city old",
            "zipcode": "zipcode old",
        },
        {
            "Results": "AV25",
            "FormattedAddress": "address1 new;address2 new",
            "AdministrativeArea": "state new",
            "AddressLine1": "address1 new",
            "AddressLine2": "address2 new",
            "Latitude": 1.234567,
            "Longitude": 1.234567,
            "PostalCode": "zipcode new",
            "Locality": "city new",
        },
    )

    expected = {
        "address1": "address1 new",
        "address2": "address2 new",
        "city": "city new",
        "zipcode": "zipcode new",
        "longitude": 1.234567,
        "latitude": 1.234567,
        "state": "state new",
    }

    assert data == expected


def test_melissa_sanitize(fac):

    client = MockMelissa()

    sanitized = client.sanitize_address_model(fac)

    assert sanitized["address1"] == "address 1"
    assert sanitized["city"] == "city"
    assert sanitized["latitude"] == 1.234567
    assert sanitized["longitude"] == 1.234567
    assert sanitized["zipcode"] == "12345"
