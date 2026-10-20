"""
With address selection on, a raw API update that sends coordinates is matched
through Google (faked in conftest) and then still runs the legacy
`validate_distance_geocode` check. When the city changes or the facility has no
coordinates yet, that check measures the pin against the city centre from
`GoogleMaps.geocode_freeform`.
"""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from peeringdb_server import geo
from peeringdb_server.models import Facility, Organization, User

pytestmark = pytest.mark.django_db

EVANSTON = {"lat": 42.0451, "lng": -87.6877}
TOKYO = {"lat": 35.689487, "lng": 139.691711}


@pytest.fixture
def owner(settings):
    settings.FACILITY_ADDRESS_SELECTION_ENABLED = True
    Group.objects.get_or_create(id=settings.GUEST_GROUP_ID, defaults={"name": "guest"})
    Group.objects.get_or_create(id=settings.USER_GROUP_ID, defaults={"name": "user"})
    user = User.objects.create_user(
        username="distance-owner", email="distance@example.com"
    )
    user.set_verified()
    org = Organization.objects.create(name="Distance Owner", status="ok")
    org.admin_usergroup.user_set.add(user)
    client = APIClient()
    client.force_login(user)
    return client, org


def make_facility(org, **location):
    fields = dict(
        address1="123 Main Street",
        city="Chicago",
        state="IL",
        zipcode="60601",
        country="US",
        latitude=41.88,
        longitude=-87.63,
    )
    fields.update(location)
    return Facility.objects.create(
        org=org, name="Distance Facility", status="ok", **fields
    )


def put(client, facility, **changes):
    data = {
        "org_id": facility.org_id,
        "name": facility.name,
        "website": "https://example.com",
        "address1": facility.address1,
        "address2": "",
        "city": facility.city,
        "state": facility.state,
        "zipcode": facility.zipcode,
        "country": "US",
        "latitude": facility.latitude,
        "longitude": facility.longitude,
        "tech_phone": "",
        "sales_phone": "",
    }
    data.update(changes)
    return client.put(f"/api/fac/{facility.pk}", data, format="json")


@pytest.mark.parametrize(
    "city_centre,status",
    [(EVANSTON, 200), (TOKYO, 400)],
    ids=["within-50km", "beyond-50km"],
)
def test_city_change_checks_pin_against_city_centre(owner, city_centre, status):
    client, org = owner
    facility = make_facility(org)
    with patch.object(
        geo.GoogleMaps, "geocode_freeform", return_value=city_centre
    ) as geocode:
        response = put(
            client,
            facility,
            city="Evanston",
            zipcode="60201",
            latitude=41.881,
            longitude=-87.631,
        )
    assert response.status_code == status, response.content
    geocode.assert_called_once_with("Evanston")
    facility.refresh_from_db()
    if status == 200:
        assert facility.city == "Evanston"
        # only the selection branch of update() records the Google match
        assert facility.location_method == "google"
    else:
        assert "from the city center" in response.json()["latitude"][0]
        assert facility.city == "Chicago"


def test_first_coordinates_check_pin_against_city_centre(owner):
    client, org = owner
    facility = make_facility(org, latitude=None, longitude=None)
    with patch.object(
        geo.GoogleMaps,
        "geocode_freeform",
        return_value={"lat": 41.8781, "lng": -87.6298},
    ) as geocode:
        response = put(client, facility, latitude=41.881, longitude=-87.631)
    assert response.status_code == 200, response.content
    geocode.assert_called_once_with("Chicago")
    facility.refresh_from_db()
    assert float(facility.latitude) == 41.881
    assert facility.location_method == "google"
