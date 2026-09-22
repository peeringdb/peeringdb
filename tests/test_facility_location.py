import uuid
from copy import deepcopy
from unittest.mock import Mock, patch

import pytest
import requests
from django.contrib.auth.models import Group
from django.core import signing
from django.core.cache import cache, caches
from django.middleware.csrf import CSRF_SESSION_KEY, get_token
from django.test import RequestFactory
from django.urls import Resolver404
from django.urls import resolve as resolve_url
from rest_framework.test import APIClient
from reversion.models import Version

from peeringdb_server import location
from peeringdb_server.context_processors import admin_config
from peeringdb_server.mock import Mock as MockData
from peeringdb_server.models import Facility, Organization, User, UserAPIKey
from peeringdb_server.serializers import FacilitySerializer

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("enabled", [False, True])
def test_optional_browser_settings(settings, rf, enabled):
    settings.FACILITY_ADDRESS_SELECTION_ENABLED = enabled
    for key in ("GOOGLE_MAPS_API_KEY", "GOOGLE_MAPS_MAP_ID"):
        if hasattr(settings, key):
            delattr(settings, key)
    context = admin_config(rf.get("/"))
    assert context["facility_location_enabled"] is enabled
    assert context["facility_location_maps_key"] == ""
    assert context["facility_location_map_id"] == ""


@pytest.mark.parametrize("method", ["search", "place", "pin"])
def test_missing_server_key_returns_unavailable(settings, method):
    if hasattr(settings, "GOOGLE_GEOLOC_API_KEY"):
        del settings.GOOGLE_GEOLOC_API_KEY
    provider = location.GoogleLocation()
    with patch.object(requests, "request") as request:
        with pytest.raises(location.LocationUnavailable):
            if method == "search":
                provider.search("Main Street", "US", str(uuid.uuid4()))
            elif method == "place":
                provider.resolve(country="US", place_id="some-place")
            else:
                provider.resolve(country="US", pin=(41.88, -87.63))
        request.assert_not_called()


def test_mock_facility_has_no_selection_provenance():
    facility = MockData().create("fac")
    assert facility.location_method == ""
    assert facility.location_place_id == ""


@pytest.fixture
def enabled(settings):
    settings.FACILITY_ADDRESS_SELECTION_ENABLED = True
    settings.GOOGLE_GEOLOC_API_KEY = "test-key"
    settings.API_THROTTLE_WRITE = "1000/minute"
    cache.clear()


@pytest.fixture
def google_result():
    return {
        "id": "selected-place",
        "addressComponents": [
            {"types": ["street_number"], "longText": "123"},
            {"types": ["route"], "longText": "Main Street"},
            {"types": ["locality"], "longText": "Chicago", "languageCode": "en"},
            {
                "types": ["administrative_area_level_1"],
                "longText": "Illinois",
                "shortText": "IL",
            },
            {"types": ["country"], "longText": "United States", "shortText": "US"},
            {"types": ["postal_code"], "longText": "60601"},
        ],
        "location": {"latitude": 41.88, "longitude": -87.63},
    }


@pytest.fixture
def provider(google_result):
    def request(method, url, **kwargs):
        if url.endswith("/english-city"):
            return {
                "id": "english-city",
                "types": ["locality"],
                "addressComponents": [
                    item
                    for item in google_result["addressComponents"]
                    if set(item["types"]) & {"locality", "country"}
                ],
            }
        if url.endswith("/geocode/json"):
            if "address" in kwargs.get("params", {}):
                address = deepcopy(google_result)
                address["place_id"] = address["id"]
                address["geometry"] = {
                    "location": {
                        "lat": address["location"]["latitude"],
                        "lng": address["location"]["longitude"],
                    }
                }
                return {"status": "OK", "results": [address]}
            value = mock.return_value
            results = value.get("results", [google_result])
            return {
                "status": "OK",
                "results": results
                + [{"types": ["locality"], "place_id": "english-city"}],
            }
        return mock.return_value

    with patch.object(
        location.GoogleLocation,
        "request",
        side_effect=request,
        return_value=google_result,
    ) as mock:
        yield mock


@pytest.fixture
def owner(db, settings):
    Group.objects.get_or_create(id=settings.GUEST_GROUP_ID, defaults={"name": "guest"})
    Group.objects.get_or_create(id=settings.USER_GROUP_ID, defaults={"name": "user"})
    user = User.objects.create_user(
        username="location-owner", email="location@example.com"
    )
    user.set_verified()
    org = Organization.objects.create(name="Location Owner", status="ok")
    org.admin_usergroup.user_set.add(user)
    return user, org


@pytest.fixture
def client(owner, enabled):
    client = APIClient()
    client.force_login(owner[0])
    return client


@pytest.fixture
def facility(owner):
    return Facility.objects.create(
        org=owner[1],
        name="Existing Location Facility",
        status="ok",
        address1="123 Main Street",
        address2="Building B",
        suite="4",
        floor="2",
        city="Chicago",
        country="US",
        state="IL",
        zipcode="60601",
        latitude=41.88,
        longitude=-87.63,
    )


def resolve(client, org, facility=None, **extra):
    data = {
        "ref_tag": "fac",
        "org_id": org.pk,
        "country": "US",
        "session_token": str(uuid.uuid4()),
        "place_id": "selected-place",
    }
    if facility:
        data.update(
            ref_id=facility.pk,
            location_version=location.location_version(facility),
        )
    data.update(extra)
    if not data.get("place_id"):
        data.pop("place_id", None)
    return client.post("/data/location/resolve", data, format="json")


def payload(org, proposal=None, facility=None):
    data = {
        "org_id": org.pk,
        "name": "New Location Facility",
        "website": "https://example.com",
        "address1": "123 Main Street",
        "address2": "",
        "city": "Chicago",
        "country": "US",
        "state": "IL",
        "zipcode": "60601",
        "latitude": 41.88,
        "longitude": -87.63,
        "tech_phone": "",
        "sales_phone": "",
    }
    if facility:
        data.update(
            name=facility.name,
            address2=facility.address2,
            suite=facility.suite,
            floor=facility.floor,
        )
    if proposal:
        data.update(proposal["location"])
        data["location_confirmation"] = proposal["location_confirmation"]
    return data


def save_selection(client, org, data, facility=None, **extra):
    fields = data.copy()
    body = {
        "ref_tag": "fac",
        "org_id": org.pk,
        "country": fields.get("country", "US"),
        "location_confirmation": fields.pop("location_confirmation", ""),
        "data": fields,
    }
    if facility:
        body.update(
            ref_id=facility.pk, location_version=location.location_version(facility)
        )
    body.update(extra)
    method = client.put if facility else client.post
    return method("/data/location/save", body, format="json")


def proposal_data(response):
    assert response.status_code == 200, response.content
    return response.json()


@pytest.mark.parametrize("latitude,longitude", [(0, 0), (-90, -180), (90, 180)])
def test_coordinate_boundaries(latitude, longitude):
    assert location.coordinates(latitude, longitude) == (latitude, longitude)


@pytest.mark.parametrize(
    "latitude,longitude",
    [(None, 1), (1, None), (91, 0), (0, 181), (True, 0), ("nan", 0), (0, "inf")],
)
def test_invalid_coordinate_pairs(latitude, longitude):
    with pytest.raises(location.ValidationError):
        location.coordinates(latitude, longitude)


def test_mapping_uses_locality_and_codes(google_result):
    google_result["addressComponents"].append(
        {"types": ["postal_town"], "longText": "Other town"}
    )
    result = location.location_from_result(google_result, city_result=google_result)
    assert result["city"] == "Chicago"
    assert result["state"] == "IL"


def test_postal_town_fallback_and_non_us_state_code(google_result):
    for item in google_result["addressComponents"]:
        if item["types"] == ["locality"]:
            item.update(types=["postal_town"], longText="London")
        if item["types"] == ["country"]:
            item["shortText"] = "GB"
    result = location.location_from_result(google_result, city_result=google_result)
    assert result["city"] == "London"
    assert result["state"] == "IL"


@pytest.mark.parametrize("city", ["", "東京都", "Москва", "123"])
def test_missing_or_non_latin_city_goes_to_support(google_result, city):
    google_result["addressComponents"][2]["longText"] = city
    with pytest.raises(location.ValidationError, match="contact support"):
        location.location_from_result(google_result, city_result=google_result)


def test_latin_diacritics_are_allowed(google_result):
    google_result["addressComponents"][2]["longText"] = "São Paulo"
    assert (
        location.location_from_result(google_result, city_result=google_result)["city"]
        == "São Paulo"
    )


def test_no_admin_area_city_fallback(google_result):
    google_result["addressComponents"][2]["types"] = ["administrative_area_level_2"]
    with pytest.raises(location.ValidationError):
        location.location_from_result(google_result, city_result=google_result)


def test_map_pin_keeps_coordinates_without_street_or_postcode(google_result):
    google_result["addressComponents"] = google_result["addressComponents"][2:5]
    result = location.location_from_result(
        google_result, city_result=google_result, pin=(0, 0)
    )
    assert result["latitude"] == result["longitude"] == 0
    assert result["address1"] == result["zipcode"] == ""


def test_map_requires_us_state(google_result):
    google_result["addressComponents"][3]["types"] = []
    with pytest.raises(location.ValidationError):
        location.location_from_result(
            google_result, city_result=google_result, pin=(0, 0)
        )


@pytest.mark.django_db
def test_create_saves_exact_confirmed_fields(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    with patch.object(
        Facility,
        "process_geo_location",
        side_effect=AssertionError("normalization must not run"),
    ):
        response = save_selection(client, owner[1], payload(owner[1], proposal))
    assert response.status_code == 201, response.content
    saved = Facility.objects.get(name="New Location Facility")
    for field, value in proposal["location"].items():
        assert location.same_value(field, getattr(saved, field), value)
    assert saved.location_method == "google"
    assert saved.location_place_id == "selected-place"


@pytest.mark.django_db
def test_raw_create_matches_without_confirmation(client, owner, provider):
    response = client.post("/api/fac", payload(owner[1]), format="json")
    assert response.status_code == 201, response.content
    assert (
        Facility.objects.get(name="New Location Facility").location_method == "google"
    )
    assert provider.call_count == 3


def test_raw_address_match_is_case_insensitive(client, owner, provider):
    data = payload(owner[1])
    data.update(address1="123 MAIN STREET", city="CHICAGO", state="il")
    response = client.post("/api/fac", data, format="json")
    assert response.status_code == 201, response.content
    saved = Facility.objects.get(name=data["name"])
    assert (saved.address1, saved.city, saved.state) == (
        "123 Main Street",
        "Chicago",
        "IL",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("address1", "123 Main St"),
        ("city", "Other city"),
        ("state", "CA"),
        ("zipcode", "60602"),
    ],
)
def test_raw_address_requires_every_field_to_match(
    client, owner, provider, field, value
):
    data = payload(owner[1])
    data[field] = value
    response = client.post("/api/fac", data, format="json")
    assert response.status_code == 400, response.content
    assert "No exact address match" in str(response.json())
    assert not Facility.objects.filter(name=data["name"]).exists()


@pytest.mark.parametrize(
    "limit,latitude,expected",
    [(1, 41.8805, 201), (1, 41.9, 400), (3, 41.9, 201), (0.01, 41.8805, 400)],
)
def test_raw_coordinate_distance_limit(
    client, owner, provider, settings, limit, latitude, expected
):
    settings.LOCATION_MATCH_MAX_DISTANCE_KM = limit
    data = payload(owner[1])
    data["latitude"] = latitude
    response = client.post("/api/fac", data, format="json")
    assert response.status_code == expected, response.content
    if expected == 201:
        saved = Facility.objects.get(name=data["name"])
        assert float(saved.latitude) == latitude
        assert float(saved.longitude) == data["longitude"]
    else:
        assert "Coordinates must be within" in str(response.json())
        assert not Facility.objects.filter(name=data["name"]).exists()


@pytest.mark.parametrize("nulls", [False, True])
def test_raw_address_without_coordinates_uses_match(client, owner, provider, nulls):
    data = payload(owner[1])
    for field in ("latitude", "longitude"):
        if nulls:
            data[field] = None
        else:
            data.pop(field)
    response = client.post("/api/fac", data, format="json")
    assert response.status_code == 201, response.content
    saved = Facility.objects.get(name=data["name"])
    assert float(saved.latitude) == 41.88
    assert float(saved.longitude) == -87.63


def test_raw_single_coordinate_is_rejected_before_lookup(client, owner, provider):
    data = payload(owner[1])
    data.pop("longitude")
    response = client.post("/api/fac", data, format="json")
    assert response.status_code == 400
    provider.assert_not_called()


def test_raw_matching_update_and_unrelated_fields(client, owner, facility, provider):
    data = payload(owner[1], facility=facility)
    data.update(latitude=41.8805, notes="Keep these notes")
    response = client.put(f"/api/fac/{facility.pk}", data, format="json")
    assert response.status_code == 200, response.content
    facility.refresh_from_db()
    assert float(facility.latitude) == 41.8805
    assert facility.notes == "Keep these notes"
    assert facility.address2 == "Building B"
    assert facility.suite == "4"


def test_raw_coordinate_update_preserves_omitted_address(client, facility, provider):
    response = client.put(
        f"/api/fac/{facility.pk}",
        {
            "name": facility.name,
            "org_id": facility.org_id,
            "website": "https://example.com",
            "latitude": 41.8805,
            "longitude": -87.63,
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    facility.refresh_from_db()
    assert float(facility.latitude) == 41.8805
    assert facility.zipcode == "60601"
    assert facility.address1 == "123 Main Street"
    assert facility.city == "Chicago"
    assert facility.state == "IL"
    assert str(facility.country) == "US"


@pytest.mark.parametrize("zipcode", ["", "60602"])
def test_raw_coordinate_update_validates_explicit_postcode(
    client, facility, provider, zipcode
):
    response = client.put(
        f"/api/fac/{facility.pk}",
        {
            "name": facility.name,
            "org_id": facility.org_id,
            "website": "https://example.com",
            "latitude": 41.8805,
            "longitude": -87.63,
            "zipcode": zipcode,
        },
        format="json",
    )
    assert response.status_code == 400, response.content
    assert "postcode" in str(response.json()) or "No exact address match" in str(
        response.json()
    )
    facility.refresh_from_db()
    assert float(facility.latitude) == 41.88
    assert facility.zipcode == "60601"


def test_raw_lookup_checks_permissions_before_google(client, owner, provider):
    other = Organization.objects.create(name="Other API address owner", status="ok")
    response = client.post("/api/fac", payload(other), format="json")
    assert response.status_code == 403, response.content
    provider.assert_not_called()


def test_raw_provider_outage_does_not_save(client, owner, provider):
    provider.side_effect = location.LocationUnavailable()
    response = client.post("/api/fac", payload(owner[1]), format="json")
    assert response.status_code == 503, response.content
    assert not Facility.objects.filter(name="New Location Facility").exists()


def test_raw_match_is_rechecked_under_lock(client, owner, facility, provider):
    request = Mock(
        method="PUT", query_params={}, user=owner[0], _permission_holder=owner[0]
    )
    data = payload(owner[1], facility=facility)
    data["latitude"] = 41.8805
    serializer = FacilitySerializer(facility, data=data, context={"request": request})
    assert serializer.is_valid(), serializer.errors
    Facility.objects.filter(pk=facility.pk).update(city="Concurrent update")
    with pytest.raises(location.LocationConflict):
        serializer.save()


def test_raw_lookup_shares_location_throttle(client, owner, provider, settings):
    settings.API_THROTTLE_LOCATION = "1/minute"
    assert resolve(client, owner[1]).status_code == 200
    response = client.post("/api/fac", payload(owner[1]), format="json")
    assert response.status_code == 429
    assert provider.call_count == 3


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("city", "Other City"),
        ("state", "CA"),
        ("country", "CA"),
        ("latitude", 0),
        ("longitude", 0),
        ("address1", "Other Street"),
    ],
)
def test_derived_field_tampering_rejected(client, owner, provider, field, value):
    proposal = proposal_data(resolve(client, owner[1]))
    data = payload(owner[1], proposal)
    data[field] = value
    response = save_selection(client, owner[1], data)
    assert response.status_code == 400, response.content
    assert field in response.json()


@pytest.mark.django_db
def test_map_create_without_street_or_postcode(client, owner, google_result, provider):
    google_result["addressComponents"] = google_result["addressComponents"][2:5]
    google_result["place_id"] = "reverse-place"
    provider.return_value = {"status": "OK", "results": [google_result]}
    proposal = proposal_data(
        resolve(client, owner[1], place_id="", latitude=0, longitude=0)
    )
    response = save_selection(client, owner[1], payload(owner[1], proposal))
    assert response.status_code == 201, response.content
    saved = Facility.objects.get(name="New Location Facility")
    assert saved.address1 == saved.zipcode == ""
    assert saved.latitude == saved.longitude == 0
    assert saved.location_method == "map"


@pytest.mark.django_db
def test_update_preserves_supplementary_details(client, owner, facility, provider):
    proposal = proposal_data(resolve(client, owner[1], facility))
    data = payload(owner[1], proposal, facility)
    data.pop("address2")
    data.pop("suite")
    data.pop("floor")
    response = save_selection(client, owner[1], data, facility)
    assert response.status_code == 200, response.content
    facility.refresh_from_db()
    assert (facility.address2, facility.suite, facility.floor) == (
        "Building B",
        "4",
        "2",
    )


@pytest.mark.django_db
def test_stale_confirmation_does_not_overwrite(client, owner, facility, provider):
    proposal = proposal_data(resolve(client, owner[1], facility))
    Facility.objects.filter(pk=facility.pk).update(city="New city")
    response = save_selection(
        client, owner[1], payload(owner[1], proposal, facility), facility
    )
    assert response.status_code == 409, response.content
    facility.refresh_from_db()
    assert facility.city == "New city"


@pytest.mark.django_db
def test_stale_form_cannot_resolve(client, owner, facility, provider):
    Facility.objects.filter(pk=facility.pk).update(city="New city")
    response = resolve(client, owner[1], facility)
    assert response.status_code == 409, response.content
    provider.assert_not_called()


@pytest.mark.django_db
def test_unrelated_edit_needs_no_selection(client, owner, facility, provider):
    data = payload(owner[1], facility=facility)
    data["notes"] = "Updated notes"
    response = client.put(f"/api/fac/{facility.pk}", data, format="json")
    assert response.status_code == 200, response.content
    facility.refresh_from_db()
    assert facility.notes == "Updated notes"
    provider.assert_not_called()


@pytest.mark.django_db
def test_unrelated_edit_of_incomplete_legacy_location(
    client, owner, facility, provider
):
    facility.city = facility.address1 = facility.zipcode = ""
    facility.save()
    data = payload(owner[1], facility=facility)
    data.update(city="", address1="", zipcode="", notes="Legacy notes")
    response = client.put(f"/api/fac/{facility.pk}", data, format="json")
    assert response.status_code == 200, response.content
    facility.refresh_from_db()
    assert facility.city == facility.address1 == facility.zipcode == ""
    assert facility.notes == "Legacy notes"
    provider.assert_not_called()


@pytest.mark.django_db
def test_raw_update_without_exact_match_is_rejected(client, owner, facility, provider):
    data = payload(owner[1], facility=facility)
    data["city"] = "Changed city"
    response = client.put(f"/api/fac/{facility.pk}", data, format="json")
    assert response.status_code == 400, response.content
    facility.refresh_from_db()
    assert facility.city == "Chicago"
    assert "location" in response.json()
    assert provider.call_count == 3


@pytest.mark.django_db
def test_field_selection_still_works(client, facility):
    response = client.get(f"/api/fac/{facility.pk}?fields=id")
    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_provider_outage_preserves_existing_data(client, owner, facility, provider):
    provider.side_effect = location.LocationUnavailable()
    before = location.snapshot(facility)
    response = resolve(client, owner[1], facility)
    assert response.status_code == 503, response.content
    facility.refresh_from_db()
    assert location.snapshot(facility) == before


@pytest.mark.django_db
def test_country_conflict(client, owner, google_result, provider):
    google_result["addressComponents"][4]["shortText"] = "CA"
    response = resolve(client, owner[1])
    assert response.status_code == 400, response.content
    assert "country" in response.json()


@pytest.mark.django_db
def test_unauthorized_lookup_is_not_a_google_proxy(client, owner, provider):
    other = Organization.objects.create(name="Someone else", status="ok")
    response = resolve(client, other)
    assert response.status_code == 403, response.content
    provider.assert_not_called()


@pytest.mark.django_db
def test_disabled_rollout_keeps_legacy_api(client, owner, settings, provider):
    settings.FACILITY_ADDRESS_SELECTION_ENABLED = False
    response = client.post("/api/fac", payload(owner[1]), format="json")
    assert response.status_code == 201, response.content
    assert resolve(client, owner[1]).status_code == 400
    provider.assert_not_called()


@pytest.mark.django_db
def test_expired_and_cross_actor_tokens(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    token = proposal["location_confirmation"]
    with patch.object(signing.TimestampSigner, "timestamp", return_value="1"):
        old = location.sign_selection(
            proposal, f"User:{owner[0].pk}", owner[1].pk, None, ref_tag="fac"
        )
    for invalid in (old, token + "broken"):
        data = payload(owner[1], proposal)
        data["location_confirmation"] = invalid
        assert save_selection(client, owner[1], data).status_code == 400
    other = User.objects.create_user(
        username="other-location-owner", email="other@example.com"
    )
    other.set_verified()
    owner[1].admin_usergroup.user_set.add(other)
    client.force_login(other)
    assert (
        save_selection(client, owner[1], payload(owner[1], proposal)).status_code == 400
    )


def test_timeout_does_not_expose_provider_key(enabled):
    with patch("requests.request", side_effect=requests.Timeout("secret key in URL")):
        with pytest.raises(location.LocationUnavailable) as exc:
            location.GoogleLocation().search("Main Street", "US", str(uuid.uuid4()))
    assert "secret" not in str(exc.value)


@pytest.mark.django_db
def test_confirmed_location_bypasses_later_normalization(facility):
    facility.location_method = "google"
    facility.location_place_id = "selected-place"
    facility.save()
    with patch(
        "peeringdb_server.geo.Melissa.sanitize",
        side_effect=AssertionError("must not normalize"),
    ):
        assert facility.process_geo_location()["city"] == "Chicago"
    facility.city = "Admin correction"
    facility.save()
    assert facility.location_method == facility.location_place_id == ""


@pytest.mark.django_db
def test_confirmation_rechecked_under_lock(client, owner, facility, provider):
    proposal = proposal_data(resolve(client, owner[1], facility))
    request = Mock(
        method="PUT", query_params={}, user=owner[0], _permission_holder=owner[0]
    )
    serializer = FacilitySerializer(
        facility,
        data=payload(owner[1], proposal, facility),
        context={
            "request": request,
            "location_confirmation": proposal["location_confirmation"],
        },
    )
    assert serializer.is_valid(), serializer.errors
    Facility.objects.filter(pk=facility.pk).update(city="Concurrent update")
    with pytest.raises(location.LocationConflict):
        serializer.save()


def test_state_name_fallback_without_code(google_result):
    google_result["addressComponents"][3].pop("shortText")
    assert (
        location.location_from_result(google_result, city_result=google_result)["state"]
        == "Illinois"
    )


@pytest.mark.django_db
def test_search_returns_labels_and_uses_english(client, owner, provider):
    provider.return_value = {
        "suggestions": [
            {
                "placePrediction": {
                    "placeId": "p1",
                    "text": {"text": "Main Street, Chicago"},
                }
            }
        ]
    }
    response = client.post(
        "/data/location/search",
        {
            "ref_tag": "fac",
            "org_id": owner[1].pk,
            "country": "US",
            "input": "Main",
            "session_token": str(uuid.uuid4()),
        },
        format="json",
    )
    assert proposal_data(response)["suggestions"] == [
        {"place_id": "p1", "label": "Main Street, Chicago"}
    ]
    assert provider.call_args.kwargs["json"]["languageCode"] == "en"


@pytest.mark.django_db
def test_suggestion_uses_configured_org(client, owner, provider, settings):
    settings.SUGGEST_ENTITY_ORG = owner[1].pk
    proposal = proposal_data(resolve(client, owner[1]))
    data = payload(owner[1], proposal)
    data.update(suggest=True, org_id=0)
    response = save_selection(client, owner[1], data)
    assert response.status_code == 201, response.content
    saved = Facility.objects.get(name=data["name"])
    assert saved.org_id == owner[1].pk
    assert saved.status == "pending"


@pytest.mark.django_db
def test_trusted_serializer_and_admin_save_remain_available(enabled, owner, facility):
    serializer = FacilitySerializer(
        facility, data=payload(owner[1], facility=facility), context={"request": None}
    )
    assert serializer.is_valid(), serializer.errors
    with patch.object(Facility, "process_geo_location", return_value={}):
        serializer.save()
    facility.city = "Support correction"
    facility.save()
    facility.refresh_from_db()
    assert facility.city == "Support correction"


@pytest.mark.django_db
def test_user_api_key_uses_raw_matching_not_website_helpers(enabled, owner, provider):
    key, secret = UserAPIKey.objects.create_key(user=owner[0], name="Location test")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + secret)
    assert resolve(client, owner[1]).status_code == 403
    provider.assert_not_called()
    response = client.post("/api/fac", payload(owner[1]), format="json")
    assert response.status_code == 201, response.content


@pytest.mark.django_db
def test_lost_permissions_prevent_confirmed_save(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    owner[1].admin_usergroup.user_set.remove(owner[0])
    if hasattr(owner[0], "_permissions_util"):
        del owner[0]._permissions_util
    response = save_selection(client, owner[1], payload(owner[1], proposal))
    assert response.status_code == 403, response.content


@pytest.mark.django_db
def test_readonly_provenance_cannot_be_forged(client, owner, facility, provider):
    data = payload(owner[1], facility=facility)
    data.update(location_method="google", location_place_id="forged")
    response = client.put(f"/api/fac/{facility.pk}", data, format="json")
    assert response.status_code == 200, response.content
    facility.refresh_from_db()
    assert facility.location_method == facility.location_place_id == ""


@pytest.mark.django_db
def test_country_mismatch_and_incomplete_pin_do_not_call_provider(
    client, owner, provider
):
    for extra in (
        {"place_id": "", "latitude": 1},
        {"latitude": 1, "longitude": 2},
        {"place_id": "", "latitude": True, "longitude": 2},
        {"country": "ZZ"},
    ):
        response = resolve(client, owner[1], **extra)
        assert response.status_code == 400, response.content
    provider.assert_not_called()


@pytest.mark.django_db
def test_unrelated_save_after_concurrent_location_change(client, owner, facility):
    request = Mock(
        method="PUT", query_params={}, user=owner[0], _permission_holder=owner[0]
    )
    data = payload(owner[1], facility=facility)
    data["notes"] = "Unrelated change"
    serializer = FacilitySerializer(facility, data=data, context={"request": request})
    assert serializer.is_valid(), serializer.errors
    Facility.objects.filter(pk=facility.pk).update(city="Concurrent city")
    serializer.save()
    facility.refresh_from_db()
    assert facility.city == "Concurrent city"
    assert facility.notes == "Unrelated change"


def test_location_throttle_is_configurable(client, owner, provider, settings):
    settings.API_THROTTLE_LOCATION = "1/minute"
    assert resolve(client, owner[1]).status_code == 200
    response = resolve(client, owner[1])
    assert response.status_code == 429
    assert provider.call_count == 3


def test_country_viewport_is_not_a_location_confirmation(client, owner):
    provider_result = {
        "status": "OK",
        "results": [
            {
                "types": ["country", "political"],
                "address_components": [{"types": ["country"], "short_name": "AT"}],
                "geometry": {
                    "viewport": {
                        "northeast": {"lat": 49, "lng": 17},
                        "southwest": {"lat": 46, "lng": 9},
                    }
                },
            }
        ],
    }
    with patch.object(
        location.GoogleLocation, "request", return_value=provider_result
    ) as provider:
        response = client.post(
            "/data/location/country",
            {"ref_tag": "fac", "org_id": owner[1].pk, "country": "AT"},
            format="json",
        )
    assert proposal_data(response) == {
        "viewport": {"north": 49, "south": 46, "east": 17, "west": 9}
    }
    assert provider.call_args.kwargs["params"]["components"] == "country:AT"
    provider_result["results"][0]["address_components"][0]["short_name"] = "DE"
    with patch.object(location.GoogleLocation, "request", return_value=provider_result):
        with pytest.raises(location.ValidationError):
            location.GoogleLocation().country_viewport("AT")


def test_country_viewport_checks_target_permissions(client, provider):
    other = Organization.objects.create(name="Other Country Map Owner", status="ok")
    response = client.post(
        "/data/location/country",
        {"ref_tag": "fac", "org_id": other.pk, "country": "AT"},
        format="json",
    )
    assert response.status_code == 403
    provider.assert_not_called()


def test_unsupported_entity_does_not_call_provider(client, owner, provider):
    response = resolve(client, owner[1], ref_tag="org")
    assert response.status_code == 400
    assert "ref_tag" in response.json()
    provider.assert_not_called()


def test_confirmation_cannot_cross_entity_types(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    proposal["location_confirmation"] = location.sign_selection(
        proposal, f"User:{owner[0].pk}", owner[1].pk, None, ref_tag="org"
    )
    response = save_selection(client, owner[1], payload(owner[1], proposal))
    assert response.status_code == 400
    assert "location_confirmation" in response.json()


def test_location_version_supports_organization(owner):
    org = owner[1]
    version = location.location_version(org)
    org.city = "Changed city"
    assert location.location_version(org) != version


@pytest.fixture
def vienna_results(google_result):
    address = deepcopy(google_result)
    address["place_id"] = address["id"]
    address["addressComponents"][2].update(longText="Wien", languageCode="de")
    address["addressComponents"][3].update(longText="Wien", shortText="Wien")
    address["addressComponents"][4].update(longText="Austria", shortText="AT")
    address["addressComponents"][5]["longText"] = "1220"
    address["location"] = {"latitude": 48.23411, "longitude": 16.444364}
    city = {
        "id": "vienna-city",
        "types": ["locality", "political"],
        "addressComponents": [
            {"types": ["locality"], "longText": "Vienna", "languageCode": "en"},
            {"types": ["country"], "shortText": "AT"},
        ],
    }
    reverse = {
        "status": "OK",
        "results": [
            address,
            {"types": ["postal_town"], "place_id": "vienna-postal-town"},
            {"types": ["locality", "political"], "place_id": "vienna-city"},
        ],
    }
    return address, reverse, city


@pytest.mark.parametrize("method", ["place", "pin"])
def test_wien_resolves_and_saves_as_vienna(client, owner, vienna_results, method):
    address, reverse, city = vienna_results
    responses = [address, reverse, city] if method == "place" else [reverse, city]
    extra = (
        {}
        if method == "place"
        else {"place_id": "", "latitude": 48.23411, "longitude": 16.444364}
    )
    with patch.object(
        location.GoogleLocation, "request", side_effect=responses
    ) as request:
        proposal = proposal_data(resolve(client, owner[1], country="AT", **extra))
    assert request.call_args.args[1].endswith("/vienna-city")
    assert request.call_args.kwargs["params"] == {"languageCode": "en"}
    assert proposal["location"]["city"] == "Vienna"
    assert proposal["location"]["state"] == "Wien"
    assert proposal["location"]["latitude"] == 48.23411
    assert proposal["location"]["longitude"] == 16.444364
    response = save_selection(client, owner[1], payload(owner[1], proposal))
    assert response.status_code == 201, response.content
    assert Facility.objects.get(name="New Location Facility").city == "Vienna"


@pytest.mark.parametrize("language", ["de", "", None])
def test_non_english_or_unknown_city_language_cannot_be_confirmed(
    client, owner, vienna_results, language
):
    address, reverse, city = vienna_results
    city["addressComponents"][0].update(longText="Wien", languageCode=language)
    with patch.object(
        location.GoogleLocation, "request", side_effect=[address, reverse, city]
    ):
        response = resolve(client, owner[1], country="AT")
    assert response.status_code == 400
    assert "contact support" in response.json()["location"]
    assert "location_confirmation" not in response.json()


@pytest.mark.parametrize(
    "problem", ["missing", "ambiguous", "wrong_type", "wrong_country"]
)
def test_unresolved_city_cannot_be_confirmed(client, owner, vienna_results, problem):
    address, reverse, city = vienna_results
    if problem == "missing":
        reverse["results"] = [
            address,
            {"types": ["administrative_area_level_1"], "place_id": "state"},
        ]
    elif problem == "ambiguous":
        reverse["results"].append({"types": ["locality"], "place_id": "another-city"})
    elif problem == "wrong_type":
        city["types"] = ["administrative_area_level_1"]
    else:
        city["addressComponents"][1]["shortText"] = "DE"
    with patch.object(
        location.GoogleLocation, "request", side_effect=[address, reverse, city]
    ):
        response = resolve(client, owner[1], country="AT")
    assert response.status_code == 400
    assert "contact support" in response.json()["location"]


def test_postal_town_resolves_only_when_locality_absent(client, owner, vienna_results):
    address, reverse, city = vienna_results
    reverse["results"] = [address, reverse["results"][1]]
    city["id"] = "vienna-postal-town"
    city["types"] = ["postal_town"]
    city["addressComponents"][0]["types"] = ["postal_town"]
    with patch.object(
        location.GoogleLocation, "request", side_effect=[address, reverse, city]
    ):
        proposal = proposal_data(resolve(client, owner[1], country="AT"))
    assert proposal["location"]["city"] == "Vienna"


def test_confirmation_from_before_english_city_fix_is_rejected(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    old = signing.dumps(
        signing.loads(
            proposal["location_confirmation"], salt=location.CONFIRMATION_SALT
        ),
        salt="location-selection-v1",
    )
    data = payload(owner[1], proposal)
    data["location_confirmation"] = old
    assert save_selection(client, owner[1], data).status_code == 400


@pytest.mark.parametrize("use_next", [False, True])
def test_facility_page_renders_location_selector(
    client, owner, facility, settings, use_next
):
    user = owner[0]
    user.opt_flags = settings.USER_OPT_FLAG_UI_NEXT if use_next else 0
    user.save(update_fields=["opt_flags"])
    client.force_login(user)
    response = client.get(f"/fac/{facility.pk}")
    assert response.status_code == 200
    assert b'class="location-open location-secondary"' in response.content


@pytest.mark.parametrize("action", ["search", "country", "resolve"])
def test_location_helpers_are_website_only(client, action, provider):
    with pytest.raises(Resolver404):
        resolve_url(f"/api/location/{action}")
    assert client.get(f"/data/location/{action}").status_code == 405
    anonymous = APIClient()
    response = anonymous.post(f"/data/location/{action}", {}, format="json")
    assert response.status_code == 403
    provider.assert_not_called()


@pytest.mark.parametrize("csrf_in_session", [False, True])
def test_location_helper_requires_csrf(
    owner, enabled, provider, settings, csrf_in_session
):
    settings.CSRF_USE_SESSIONS = csrf_in_session
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(owner[0])
    assert resolve(client, owner[1]).status_code == 403
    provider.assert_not_called()
    caches["negative"].clear()
    request = RequestFactory().get("/")
    token = get_token(request)
    if csrf_in_session:
        session = client.session
        session[CSRF_SESSION_KEY] = request.META["CSRF_COOKIE"]
        session.save()
    else:
        client.cookies["csrftoken"] = request.META["CSRF_COOKIE"]
    client.credentials(HTTP_X_CSRFTOKEN=token)
    response = resolve(client, owner[1])
    assert response.status_code == 200, response.content


@pytest.mark.parametrize("body", ["{", "[]", "null", '"text"'])
def test_location_helper_rejects_invalid_json(client, provider, body):
    response = client.post(
        "/data/location/resolve", body, content_type="application/json"
    )
    assert response.status_code == 400
    assert "location" in response.json()
    provider.assert_not_called()


def test_location_helper_rejects_mixed_authentication(client, owner, provider):
    _, secret = UserAPIKey.objects.create_key(user=owner[0], name="Extra header")
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + secret)
    assert resolve(client, owner[1]).status_code == 400
    provider.assert_not_called()


def test_public_facility_serializer_has_no_selection_fields(client, facility):
    assert (
        not {"location_confirmation", "location_version"}
        & FacilitySerializer().fields.keys()
    )
    response = client.get(f"/api/fac/{facility.pk}")
    assert response.status_code == 200
    assert (
        not {"location_confirmation", "location_version"}
        & response.json()["data"][0].keys()
    )


def test_api_confirmation_cannot_bypass_address_matching(
    client, owner, provider, google_result
):
    google_result["place_id"] = "reverse-place"
    google_result["addressComponents"] = google_result["addressComponents"][2:5]
    proposal = proposal_data(
        resolve(client, owner[1], place_id="", latitude=0, longitude=0)
    )
    provider.reset_mock()
    response = client.post("/api/fac", payload(owner[1], proposal), format="json")
    assert response.status_code == 400
    assert "location" in response.json()
    assert not Facility.objects.filter(name="New Location Facility").exists()


def test_website_save_records_revision_user(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    response = save_selection(client, owner[1], payload(owner[1], proposal))
    assert response.status_code == 201, response.content
    facility = Facility.objects.get(pk=response.json()["data"][0]["id"])
    revision = Version.objects.get_for_object(facility).first().revision
    assert revision.user_id == owner[0].pk
    assert (
        not {"location_confirmation", "location_version"}
        & response.json()["data"][0].keys()
    )


def test_website_save_rolls_back_serialization_failure(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    with patch(
        "peeringdb_server.location_views.JsonResponse",
        side_effect=TypeError("encoding failed"),
    ):
        with pytest.raises(TypeError, match="encoding failed"):
            save_selection(client, owner[1], payload(owner[1], proposal))
    assert not Facility.objects.filter(name="New Location Facility").exists()


def test_website_save_rolls_back_deleted_name_reclaim(
    client, owner, facility, provider
):
    facility.status = "deleted"
    facility.save()
    original_name = facility.name
    proposal = proposal_data(resolve(client, owner[1]))
    data = payload(owner[1], proposal)
    data.update(name=original_name, tech_phone="invalid phone")
    response = save_selection(client, owner[1], data)
    assert response.status_code == 400, response.content
    facility.refresh_from_db()
    assert facility.name == original_name
    assert facility.status == "deleted"


@pytest.mark.parametrize("problem", ["missing_token", "wrong_org", "wrong_method"])
def test_website_save_rejects_invalid_target_or_confirmation(
    client, owner, facility, provider, problem
):
    proposal = proposal_data(resolve(client, owner[1]))
    data = payload(owner[1], proposal)
    extra = {}
    if problem == "missing_token":
        data.pop("location_confirmation")
    elif problem == "wrong_org":
        data["org_id"] = owner[1].pk + 1
    else:
        extra.update(
            ref_id=facility.pk, location_version=location.location_version(facility)
        )
    response = save_selection(client, owner[1], data, **extra)
    assert response.status_code == 400, response.content
    assert not Facility.objects.filter(name="New Location Facility").exists()


def test_website_save_requires_csrf(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    protected = APIClient(enforce_csrf_checks=True)
    protected.force_login(owner[0])
    response = save_selection(protected, owner[1], payload(owner[1], proposal))
    assert response.status_code == 403
    assert not Facility.objects.filter(name="New Location Facility").exists()


def test_website_save_uses_write_throttle(client, owner, provider):
    proposal = proposal_data(resolve(client, owner[1]))
    with patch(
        "peeringdb_server.location_views.WriteRateThrottle.get_rate",
        return_value="1/minute",
    ):
        assert (
            save_selection(client, owner[1], payload(owner[1], proposal)).status_code
            == 201
        )
        data = payload(owner[1], proposal)
        data["name"] = "Second Website Facility"
        response = save_selection(client, owner[1], data)
    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0
    assert not Facility.objects.filter(name="Second Website Facility").exists()
