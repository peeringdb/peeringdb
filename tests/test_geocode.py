import json
import os
from unittest.mock import MagicMock, patch

import googlemaps
import pytest
from django.core.cache import caches
from django.core.exceptions import ValidationError

import peeringdb_server.geo as geo
import peeringdb_server.models as models
from peeringdb_server.serializers import GeocodeSerializerMixin, SpatialSearchMixin


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


@pytest.mark.django_db
def test_geo_model_defaults(fac):
    assert fac.geocode_status is False
    assert fac.geocode_date is None


@pytest.mark.django_db
def test_geo_model_geocode_coordinates(fac):
    assert fac.geocode_coordinates is None
    fac.latitude = 41.876212
    fac.longitude = -87.631453
    assert fac.geocode_coordinates == (41.876212, -87.631453)


@pytest.mark.django_db
def test_geo_model_geocode_addresss(fac):
    assert fac.geocode_address == "Some street , Chicago, IL 1234"


@pytest.mark.django_db
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


@pytest.mark.django_db
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


@pytest.mark.django_db
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


@pytest.mark.django_db
def test_melissa_global_address_best_result():
    client = geo.Melissa("")

    expected = {"Results": "AV25", "Address1": "value1"}

    result = {"Records": [expected, {"Results": "AV25", "Address1": "value2"}]}

    assert client.global_address_best_result(result) == expected
    assert client.global_address_best_result({}) == None
    assert client.global_address_best_result(None) == None

    result = {"Records": [{"Results": "AV12", "Address1": "value2"}]}

    assert client.global_address_best_result(result) == None


@pytest.mark.django_db
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


@pytest.mark.django_db
def test_melissa_sanitize(fac):
    client = MockMelissa()

    sanitized = client.sanitize_address_model(fac)

    assert sanitized["address1"] == "address 1"
    assert sanitized["city"] == "city"
    assert sanitized["latitude"] == 1.234567
    assert sanitized["longitude"] == 1.234567
    assert sanitized["zipcode"] == "12345"


@pytest.fixture
def google_maps_mock():
    with patch("peeringdb_server.serializers.GoogleMaps") as mock:
        gmaps = MagicMock()
        mock.return_value = gmaps
        gmaps.client.geocode.return_value = [
            {
                "geometry": {
                    "bounds": {
                        "northeast": {"lat": 40.9, "lng": -73.7},
                        "southwest": {"lat": 40.5, "lng": -74.3},
                    }
                }
            }
        ]
        gmaps.distance_from_bounds.return_value = 50
        yield mock


@pytest.mark.django_db
@pytest.fixture(autouse=True)
def clear_cache():
    caches["geo"].clear()
    yield


@pytest.mark.django_db
@pytest.mark.parametrize(
    "filters, expected_filters, expected_geocode_call",
    [
        (
            {"city": "New York", "country": "US"},
            {"city": "New York", "country": "US", "distance": 50},
            "New York, US",
        ),
        (
            {"city__in": ["New York"], "country": "US"},
            {"city": "New York", "country": "US", "distance": 50},
            "New York, US",
        ),
        (
            {"city": "New York", "country__in": ["US"]},
            {"city": "New York", "country": "US", "distance": 50},
            "New York, US",
        ),
        (
            {"city": "New York"},
            {"city": "New York", "country": "US", "distance": 50},
            "New York",
        ),
    ],
)
def test_convert_to_spatial_search(
    google_maps_mock, filters, expected_filters, expected_geocode_call
):
    if "country" not in filters:
        google_maps_mock.return_value.parse_results_get_country.return_value = "US"

    SpatialSearchMixin.convert_to_spatial_search(filters)

    assert filters == expected_filters
    google_maps_mock.return_value.client.geocode.assert_called_once_with(
        expected_geocode_call
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "filters, expected_filters",
    [
        ({"country": "US"}, {"country": "US"}),
        (
            {"city__in": ["New York", "Los Angeles"], "country": "US"},
            {"city__in": ["New York", "Los Angeles"], "country": "US"},
        ),
    ],
)
def test_convert_to_spatial_search_no_change(filters, expected_filters):
    original_filters = filters.copy()

    SpatialSearchMixin.convert_to_spatial_search(filters)

    assert filters == expected_filters == original_filters


@pytest.mark.django_db
def test_convert_to_spatial_search_cached(google_maps_mock, settings):
    filters = {"city": "New York", "country": "US"}
    cache_key = "geo.city.New York_US"
    cached_result = json.dumps(
        [
            {
                "geometry": {
                    "bounds": {
                        "northeast": {"lat": 40.9, "lng": -73.7},
                        "southwest": {"lat": 40.5, "lng": -74.3},
                    }
                }
            }
        ]
    )

    # Pre-populate the cache
    caches["geo"].set(cache_key, cached_result, timeout=settings.GEOCOORD_CACHE_EXPIRY)

    SpatialSearchMixin.convert_to_spatial_search(filters)

    assert filters == {"city": "New York", "country": "US", "distance": 50}
    google_maps_mock.return_value.client.geocode.assert_not_called()

    # Verify that the cache was used
    assert caches["geo"].get(cache_key) == cached_result


@pytest.mark.django_db
def test_convert_to_spatial_search_caching(google_maps_mock):
    filters = {"city": "New York", "country": "US"}
    cache_key = "geo.city.New York_US"

    # Ensure cache is empty
    assert caches["geo"].get(cache_key) is None

    SpatialSearchMixin.convert_to_spatial_search(filters)

    # Verify that the result was cached
    assert caches["geo"].get(cache_key) is not None

    # Clear the mocks
    google_maps_mock.reset_mock()

    # Call again to use cached result
    SpatialSearchMixin.convert_to_spatial_search(filters)

    # Verify that Google Maps API was not called again
    google_maps_mock.return_value.client.geocode.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "country, result_types, typ, expected_found",
    [
        # Test sovereign microstate (Singapore) city detection
        ("SG", ["country"], "city", True),
        ("SG", ["locality"], "city", True),
        ("SG", ["administrative_area_level_1"], "city", False),
        # Test non-microstate normal country (FR) city detection
        ("FR", ["locality"], "city", True),
        ("FR", ["administrative_area_level_1"], "city", True),
        ("FR", ["country"], "city", False),
        # Test country with states (US) city detection
        ("US", ["locality"], "city", True),
        ("US", ["administrative_area_level_1"], "city", False),
        ("US", ["country"], "city", False),
        # Test state detection for country with states
        ("US", ["administrative_area_level_1"], "state", True),
        ("CA", ["administrative_area_level_1"], "state", True),
        ("FR", ["administrative_area_level_1"], "state", False),
    ],
)
def test_geocode_address_location_types(country, result_types, typ, expected_found):
    """
    Test location type detection for different geographic hierarchies
    """

    client = geo.GoogleMaps("AIza_test")

    # Mock the geocoding result
    mock_result = [
        {"types": result_types, "geometry": {"location": {"lat": 1.0, "lng": 1.0}}}
    ]

    with patch.object(client.client, "geocode", return_value=mock_result):
        if expected_found:
            location = client.geocode_address("Test Address", country, typ)
            assert location == {"lat": 1.0, "lng": 1.0}
        else:
            with pytest.raises(geo.NotFound):
                client.geocode_address("Test Address", country, typ)
