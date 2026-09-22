"""Google location selection and signed entity confirmations."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from decimal import Decimal
from typing import Protocol
from urllib.parse import quote

import requests
from django.conf import settings
from django.core import signing
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _
from django_countries import countries
from geopy.distance import geodesic
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError


class LocatedEntity(Protocol):
    pk: int
    grainy_namespace: str


class LocationMethod(TextChoices):
    GOOGLE = "google", _("Google place")
    MAP = "map", _("Map pin")


LOCATION_FIELDS = (
    "address1",
    "city",
    "state",
    "zipcode",
    "country",
    "latitude",
    "longitude",
)
ADDRESS_FIELDS = LOCATION_FIELDS[:-2]
STATE_REQUIRED_COUNTRIES = {"US", "CA"}
CONFIRMATION_SALT = "location-selection-v2"
CONFIRMATION_MAX_AGE = 900


class LocationConflict(APIException):
    status_code = 409
    default_detail = "The location changed. Reload and select it again."
    default_code = "location_conflict"


class LocationUnavailable(APIException):
    status_code = 503
    default_detail = "Google location lookup is unavailable. Retry or contact support."
    default_code = "location_unavailable"


def snapshot(instance: LocatedEntity) -> dict[str, str]:
    values = {
        field: "" if getattr(instance, field) is None else str(getattr(instance, field))
        for field in LOCATION_FIELDS
    }
    for field in ("latitude", "longitude"):
        if values[field]:
            values[field] = str(Decimal(values[field]).normalize())
    return values


def location_version(instance: LocatedEntity) -> str:
    values = snapshot(instance)
    values["namespace"] = instance.grainy_namespace
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def same_value(field: str, left: object, right: object) -> bool:
    if field in ("latitude", "longitude"):
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except (ValueError, ArithmeticError):
            return left in (None, "") and right in (None, "")
    return str(left or "") == str(right or "")


def coordinates(latitude: object, longitude: object) -> tuple[float, float]:
    try:
        if (
            isinstance(latitude, bool)
            or isinstance(longitude, bool)
            or not isinstance(latitude, (str, int, float, Decimal))
            or not isinstance(longitude, (str, int, float, Decimal))
        ):
            raise ValueError
        lat, lng = float(latitude), float(longitude)
        if not math.isfinite(lat) or not math.isfinite(lng):
            raise ValueError
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise ValueError
        return round(lat, 6), round(lng, 6)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(
            {"location": "Provide valid latitude and longitude together."}
        ) from None


def country_code(value: object) -> str:
    if not isinstance(value, str) or value not in dict(countries):
        raise ValidationError({"country": "Select a valid country."})
    return value


def latin_name(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return bool(letters) and all(
        "LATIN" in unicodedata.name(char, "") for char in letters
    )


def location_from_result(
    result: dict, *, city_result: dict, pin: tuple[float, float] | None = None
) -> dict:
    if not isinstance(result, dict):
        raise LocationUnavailable()
    components = {}
    items = result.get("addressComponents", result.get("address_components", []))
    if not isinstance(items, list):
        raise LocationUnavailable()
    for item in items:
        if not isinstance(item, dict):
            raise LocationUnavailable()
        kinds = item.get("types", [])
        if not isinstance(kinds, list) or not all(
            isinstance(kind, str) for kind in kinds
        ):
            raise LocationUnavailable()
        for kind in kinds:
            components[kind] = item

    def component(kind: str, short: bool = False) -> str:
        item = components.get(kind, {})
        value = item.get(
            "shortText" if short else "longText",
            item.get("short_name" if short else "long_name", ""),
        )
        return value.strip() if isinstance(value, str) else ""

    country = component("country", short=True)
    city = english_city(city_result, country)
    state = component("administrative_area_level_1", short=True) or component(
        "administrative_area_level_1"
    )
    if (
        country not in dict(countries)
        or not latin_name(city)
        or (country in STATE_REQUIRED_COUNTRIES and not state)
    ):
        raise ValidationError(
            {
                "location": "Required country, English city or state could not be established. Choose another location or contact support."
            }
        )

    if pin is None:
        point = result.get("location", {})
        if not point:
            point = result.get("geometry", {}).get("location", {})
        pin = coordinates(
            point.get("latitude", point.get("lat")),
            point.get("longitude", point.get("lng")),
        )
    street = component("route")
    number = component("street_number")
    address = " ".join(value for value in (number, street) if value) if street else ""
    return {
        "address1": address,
        "city": city,
        "state": state,
        "country": country,
        "zipcode": component("postal_code"),
        "latitude": pin[0],
        "longitude": pin[1],
    }


def english_city(result: dict, country: str) -> str:
    components = result.get("addressComponents", [])
    if not isinstance(components, list) or not all(
        isinstance(item, dict) for item in components
    ):
        raise LocationUnavailable()
    countries = [
        item.get("shortText")
        for item in components
        if "country" in item.get("types", [])
    ]
    for kind in ("locality", "postal_town"):
        cities = [item for item in components if kind in item.get("types", [])]
        if not cities:
            continue
        name = cities[0].get("longText", "")
        language = cities[0].get("languageCode", "")
        if (
            len(cities) == 1
            and countries == [country]
            and isinstance(name, str)
            and latin_name(name)
            and isinstance(language, str)
            and language.split("-")[0] == "en"
        ):
            return name.strip()
        break
    raise ValidationError(
        {
            "location": "An English city could not be established. Choose another location or contact support."
        }
    )


class GoogleLocation:
    def request(self, method: str, url: str, **kwargs) -> dict:
        key = getattr(settings, "GOOGLE_GEOLOC_API_KEY", "")
        if not key:
            raise LocationUnavailable()
        try:
            response = requests.request(method, url, timeout=5, **kwargs)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            # Provider exceptions can contain the key-bearing request URL.
            raise LocationUnavailable() from None
        if not isinstance(data, dict) or data.get("error"):
            raise LocationUnavailable()
        return data

    def country_viewport(self, country: str) -> dict[str, float]:
        data = self.request(
            "GET",
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "key": getattr(settings, "GOOGLE_GEOLOC_API_KEY", ""),
                "address": str(dict(countries)[country]),
                "components": f"country:{country}",
                "language": "en",
            },
        )
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            raise LocationUnavailable()
        for result in data.get("results", []):
            if "country" not in result.get("types", []):
                continue
            if not any(
                "country" in item.get("types", []) and item.get("short_name") == country
                for item in result.get("address_components", [])
            ):
                continue
            viewport = result.get("geometry", {}).get("viewport", {})
            northeast = viewport.get("northeast", {})
            southwest = viewport.get("southwest", {})
            north, east = coordinates(northeast.get("lat"), northeast.get("lng"))
            south, west = coordinates(southwest.get("lat"), southwest.get("lng"))
            return {"north": north, "east": east, "south": south, "west": west}
        raise ValidationError(
            {
                "country": "The country map could not be loaded. Retry or contact support."
            }
        )

    def match_address(
        self, address: dict, pin: tuple[float, float] | None = None
    ) -> dict:
        country = country_code(str(address["country"]))
        if not address["address1"] or not address["city"]:
            raise ValidationError(
                {
                    "location": "Provide a street address and city to match, or select a location on the website."
                }
            )
        if not address["zipcode"] and country not in settings.NON_ZIPCODE_COUNTRIES:
            raise ValidationError(
                {
                    "zipcode": "Provide a postcode to match, or select a location on the website."
                }
            )
        data = self.request(
            "GET",
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "key": getattr(settings, "GOOGLE_GEOLOC_API_KEY", ""),
                "address": ", ".join(
                    str(address[field]) for field in ADDRESS_FIELDS if address[field]
                ),
                "components": f"country:{country}",
                "language": "en",
            },
        )
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            raise LocationUnavailable()
        matched_address = False
        for result in data.get("results", []):
            place_id = result.get("place_id")
            if not isinstance(place_id, str) or not place_id or len(place_id) > 512:
                continue
            try:
                point = result.get("geometry", {}).get("location", {})
                coords = coordinates(point.get("lat"), point.get("lng"))
                resolved = location_from_result(
                    result, city_result=self.resolve_city(self.reverse(coords))
                )
            except ValidationError:
                continue
            if not all(
                str(address[field]).casefold() == str(resolved[field]).casefold()
                for field in ADDRESS_FIELDS
            ):
                continue
            matched_address = True
            if pin is not None:
                if geodesic(coords, pin).km > settings.LOCATION_MATCH_MAX_DISTANCE_KM:
                    continue
                resolved["latitude"], resolved["longitude"] = pin
            return {
                "location": resolved,
                "method": LocationMethod.GOOGLE,
                "place_id": place_id,
            }
        if matched_address:
            raise ValidationError(
                {
                    "latitude": f"Coordinates must be within {settings.LOCATION_MATCH_MAX_DISTANCE_KM:g} km of the matched address."
                }
            )
        raise ValidationError(
            {
                "location": "No exact address match was found. Check the address fields or select a location on the website."
            }
        )

    def search(
        self, text: str, country: str, session_token: str
    ) -> list[dict[str, str]]:
        data = self.request(
            "POST",
            "https://places.googleapis.com/v1/places:autocomplete",
            headers={"X-Goog-Api-Key": getattr(settings, "GOOGLE_GEOLOC_API_KEY", "")},
            json={
                "input": text,
                "languageCode": "en",
                "includedRegionCodes": [country.lower()],
                "sessionToken": session_token,
            },
        )
        suggestions = []
        items = data.get("suggestions", [])
        if not isinstance(items, list):
            raise LocationUnavailable()
        for item in items:
            if not isinstance(item, dict):
                raise LocationUnavailable()
            prediction = item.get("placePrediction", {})
            place_id = prediction.get("placeId")
            label = prediction.get("text", {}).get("text")
            if isinstance(place_id, str) and isinstance(label, str):
                suggestions.append({"place_id": place_id, "label": label})
        return suggestions

    def reverse(self, pin: tuple[float, float]) -> list[dict]:
        data = self.request(
            "GET",
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "key": getattr(settings, "GOOGLE_GEOLOC_API_KEY", ""),
                "latlng": f"{pin[0]},{pin[1]}",
                "language": "en",
            },
        )
        if data.get("status") == "ZERO_RESULTS":
            raise ValidationError(
                {
                    "location": "No address was found for this point. Move the pin or contact support."
                }
            )
        if data.get("status") != "OK":
            raise LocationUnavailable()
        results = data.get("results", [])
        if (
            not isinstance(results, list)
            or not results
            or not all(isinstance(result, dict) for result in results)
        ):
            raise LocationUnavailable()
        return results

    def resolve_city(self, results: list[dict]) -> dict:
        for kind in ("locality", "postal_town"):
            cities = [result for result in results if kind in result.get("types", [])]
            if not cities:
                continue
            place_ids = {result.get("place_id") for result in cities}
            if len(place_ids) == 1:
                place_id = place_ids.pop()
                if isinstance(place_id, str) and place_id:
                    result = self.request(
                        "GET",
                        "https://places.googleapis.com/v1/places/"
                        + quote(place_id, safe=""),
                        headers={
                            "X-Goog-Api-Key": getattr(
                                settings, "GOOGLE_GEOLOC_API_KEY", ""
                            ),
                            "X-Goog-FieldMask": "id,types,addressComponents",
                        },
                        params={"languageCode": "en"},
                    )
                    if result.get("id") == place_id and kind in result.get("types", []):
                        return result
            break
        raise ValidationError(
            {
                "location": "The city could not be established unambiguously. Choose another location or contact support."
            }
        )

    def resolve(
        self,
        *,
        country: str,
        place_id: str = "",
        session_token: str = "",
        pin: tuple[float, float] | None = None,
    ) -> dict:
        if pin is None:
            result = self.request(
                "GET",
                "https://places.googleapis.com/v1/places/" + quote(place_id, safe=""),
                headers={
                    "X-Goog-Api-Key": getattr(settings, "GOOGLE_GEOLOC_API_KEY", ""),
                    "X-Goog-FieldMask": "id,addressComponents,location,attributions",
                },
                params={"languageCode": "en", "sessionToken": session_token},
            )
            place_id = result.get("id", "")
            point = result.get("location", {})
            results = self.reverse(
                coordinates(point.get("latitude"), point.get("longitude"))
            )
        else:
            results = self.reverse(pin)
            result = results[0]
            place_id = result.get("place_id", "")
        if not isinstance(place_id, str) or not place_id:
            raise LocationUnavailable()
        location = location_from_result(
            result, city_result=self.resolve_city(results), pin=pin
        )
        if location["country"] != country:
            raise ValidationError(
                {
                    "country": "The selected location is in a different country. Change the country and select again."
                }
            )
        if pin is None and (
            not location["address1"]
            or (
                not location["zipcode"]
                and country not in settings.NON_ZIPCODE_COUNTRIES
            )
        ):
            raise ValidationError(
                {
                    "location": "This result has no complete street address. Choose on map or contact support."
                }
            )
        if len(place_id) > 512:
            raise LocationUnavailable()
        return {
            "location": location,
            "method": LocationMethod.MAP if pin is not None else LocationMethod.GOOGLE,
            "place_id": place_id,
            "attributions": result.get("attributions", []),
        }


def actor_id(holder: object) -> str:
    pk = getattr(holder, "pk", None)
    if pk is None:
        raise PermissionDenied("Authentication is required to select a location.")
    return f"{holder.__class__.__name__}:{pk}"


def sign_selection(
    proposal: dict,
    actor: str,
    org_id: int,
    instance: LocatedEntity | None,
    *,
    ref_tag: str,
) -> str:
    return signing.dumps(
        {
            "location": proposal["location"],
            "method": proposal["method"],
            "place_id": proposal["place_id"],
            "actor": actor,
            "org_id": org_id,
            "ref_tag": ref_tag,
            "ref_id": instance.pk if instance else None,
            "version": location_version(instance) if instance else None,
        },
        salt=CONFIRMATION_SALT,
        compress=True,
    )


def read_selection(
    token: str, actor: str, org_id: int, instance: LocatedEntity | None, *, ref_tag: str
) -> dict:
    try:
        selection = signing.loads(
            token, salt=CONFIRMATION_SALT, max_age=CONFIRMATION_MAX_AGE
        )
    except (signing.BadSignature, TypeError, ValueError):
        raise ValidationError(
            {
                "location_confirmation": "The selection expired or is invalid. Select and confirm the location again."
            }
        ) from None
    if (
        selection.get("actor") != actor
        or selection.get("org_id") != org_id
        or selection.get("ref_tag") != ref_tag
        or selection.get("ref_id") != (instance.pk if instance else None)
    ):
        raise ValidationError(
            {
                "location_confirmation": "The selection belongs to a different user or entity."
            }
        )
    if instance and selection["version"] != location_version(instance):
        raise LocationConflict()
    return selection
