"""
Utilities for geocoding and geo normalization.
"""

import copy
import re

import googlemaps
import requests
import structlog
import unidecode
from django.conf import settings
from django.core.cache import caches
from django.utils.translation import gettext_lazy as _
from geopy.distance import geodesic

from peeringdb_server.context import current_request

logger = structlog.getLogger(__name__)


class Timeout(IOError):
    def __init__(self):
        super().__init__("Geo location lookup has timed out")


class RequestError(IOError):
    def __init__(self, exc):
        super().__init__(f"{exc}")


class NotFound(IOError):
    pass


class GoogleMaps:
    def __init__(self, key, timeout=5):
        self.key = key
        self.client = googlemaps.Client(key, timeout=timeout)

    def geocode(self, instance):
        geocode = self.geocode_address(instance.geocode_address, instance.country.code)
        instance.latitude = geocode.get("lat")
        instance.longitude = geocode.get("lng")

    def geocode_address(self, address, country, typ="premise"):
        """
        Return the latitude, longitude field values of the specified
        address.
        """

        try:
            result = self.client.geocode(
                address,
                components={"country": country},
            )
        except (
            googlemaps.exceptions.HTTPError,
            googlemaps.exceptions.ApiError,
            googlemaps.exceptions.TransportError,
        ) as exc:
            raise RequestError(exc)
        except googlemaps.exceptions.Timeout:
            raise Timeout()

        if not result:
            raise NotFound()

        is_premise = (
            "street_address" in result[0]["types"]
            or "establishment" in result[0]["types"]
            or "premise" in result[0]["types"]
            or "subpremise" in result[0]["types"]
        )

        if country in settings.GEO_COUNTRIES_WITH_STATES:
            # countries with states (US, CA, etc.)
            is_city = "locality" in result[0]["types"]
            is_state = "administrative_area_level_1" in result[0]["types"]
        elif country in settings.GEO_SOVEREIGN_MICROSTATES:
            # country-states where city and country are the same
            is_city = (
                "locality" in result[0]["types"] or "country" in result[0]["types"]
            )
            is_state = False
        else:
            # everything else checks for either locality or admin area level 1
            # to find a city match
            is_city = (
                "locality" in result[0]["types"]
                or "administrative_area_level_1" in result[0]["types"]
            )
            is_state = False

        is_country = "country" in result[0]["types"]

        is_postal = "postal_code" in result[0]["types"]

        if result and (
            (typ == "premise" and is_premise)
            or (typ == "city" and is_city)
            or (typ == "country" and is_country)
            or (typ == "postal" and is_postal)
            or (typ == "state" and is_state)
        ):
            return result[0].get("geometry").get("location")
        else:
            raise NotFound(_("Error in forward geocode: No results found"))

    def geocode_freeform(self, location):
        """
        Return the latitude, longitude field values of the specified
        location.
        """

        try:
            result = self.client.geocode(
                location,
            )
        except (
            googlemaps.exceptions.HTTPError,
            googlemaps.exceptions.ApiError,
            googlemaps.exceptions.TransportError,
        ) as exc:
            raise RequestError(exc)
        except googlemaps.exceptions.Timeout:
            raise Timeout()

        if not result:
            raise NotFound()

        return result[0].get("geometry").get("location")

    def build_location_dict(self, address_components):
        """
        Returns a dict containing location, state and country name
        from the address components.
        """

        locality = ""
        admin_area_level_1 = ""
        country = ""

        for component in address_components:
            if "locality" in component["types"]:
                locality = component["long_name"]
            elif "administrative_area_level_1" in component["types"]:
                admin_area_level_1 = component["short_name"]
            elif "country" in component["types"]:
                country = component["short_name"]

        if locality == admin_area_level_1:
            admin_area_level_1 = None

        return {
            "location": locality,
            "state": admin_area_level_1,
            "country": country,
        }

    def distance_from_bounds(self, bounds):
        northeast = bounds["northeast"]
        southwest = bounds["southwest"]
        point1 = (northeast["lat"], northeast["lng"])
        point2 = (southwest["lat"], southwest["lng"])
        return geodesic(point1, point2).kilometers

    def parse_results_get_country(self, results) -> str | None:
        """
        Parse the results and return the country code.
        """

        for result in results:
            for component in result["address_components"]:
                if "country" in component["types"]:
                    return component["short_name"]

        return None


class Melissa:
    """
    Handle requests to the melissa global address
    service used for geocoding and address normalization.
    """

    global_address_url = (
        "https://address.melissadata.net/v3/WEB/GlobalAddress/doGlobalAddress"
    )

    # maps peeringdb address model field to melissa
    # global address result fields

    field_map = {
        "address1": "AddressLine1",
        "address2": "AddressLine2",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "zipcode": "PostalCode",
        "state": "AdministrativeArea",
        "city": "Locality",
    }

    def __init__(self, key, timeout=5):
        self.key = key
        self.timeout = timeout

    def log_request(self, url, **kwargs):
        with current_request() as request:
            if request:
                source_url = request.build_absolute_uri()[:255]

                search = copy.deepcopy(kwargs)
                search.pop("id", None)

                logger.info("MELISSA", url=url, source=source_url, search=search)
            else:
                logger.info("MELISSA", url=url)

    def sanitize(self, **kwargs):
        """
        Take an international address and sanitize it
        using the melissa global address service.
        """

        results = self.global_address(**kwargs)
        best = self.global_address_best_result(results)

        if not best:
            return {}

        return self.apply_global_address(kwargs, best)

    def sanitize_address_model(self, instance):
        """
        Take an instance of AddressModel and
        run its address through the normalization
        process.

        Note that this will not actually change fields
        on the instance.

        Return dict with normalized address data and
        geo coordinates.
        """

        return self.sanitize(
            address1=instance.address1,
            address2=instance.address2,
            city=instance.city,
            zipcode=instance.zipcode,
            country=f"{instance.country}",
        )

    def apply_global_address(self, pdb_data, melissa_data):
        # map peeringdb address fields to melissa result fields
        faddr = melissa_data["FormattedAddress"].split(";")
        for key in self.field_map.keys():
            # melissa tends to put things it does not comprehend
            # into address line 1 - meaning aribtrary data that currently
            # exists in our address2 fields will end up there.
            #
            # however the valid address
            # can still be grabbed from the FormattedAddress
            # property, so we do this instead

            if key == "address1":
                pdb_data["address1"] = faddr[0]
            else:
                pdb_data[key] = melissa_data[self.field_map[key]]

        if pdb_data["address1"] == pdb_data["address2"]:
            pdb_data["address2"] = ""

        if pdb_data["address2"].find(f"{melissa_data['Locality']},") == 0:
            pdb_data["address2"] = ""

        return pdb_data

    def global_address_params(self, **kwargs):
        return {
            "a1": kwargs.get("address1"),
            "a2": kwargs.get("address2"),
            "ctry": kwargs.get("country"),
            "loc": kwargs.get("city"),
            "postal": kwargs.get("zipcode"),
        }

    def global_address(self, **kwargs):
        """
        Send request to the global address service.

        Keyword arguments:

        - address1
        - address2
        - city
        - country
        - zipcode
        """

        params = self.global_address_params(**kwargs)
        params.update(id=self.key)

        headers = {
            "ACCEPT": "application/json",
        }

        try:
            self.log_request(self.global_address_url, **params)

            response = requests.get(
                self.global_address_url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            raise Timeout()
        except OSError as exc:
            raise RequestError(exc)

        if response.status_code != 200:
            raise RequestError(f"Returned status {response.status_code}")

        return response.json()

    def usable_result(self, codes):
        for code in codes:
            if code[:2] == "AV":
                if int(code[3]) > 3:
                    return True
        return False

    def global_address_best_result(self, result):
        if not result:
            return None

        try:
            record = result["Records"][0]
            codes = record.get("Results", "").split(",")
            if self.usable_result(codes):
                return record
            return None

        except (KeyError, IndexError):
            return None

    def normalize_state(self, country_code, state):
        """
        Takes a 2-digit country code and a state name (e.g., "Wisconsin")
        and returns a normalized state name (e.g., "WI")

        This will use django-cache if it exists
        """

        if not state:
            return state

        # clean up state value for cache key

        state_clean = unidecode.unidecode(state.lower()).strip()
        state_clean = re.sub(r"[^a-zA-Z]+", "", state_clean)

        key = f"geo.normalize.state.{country_code}.{state_clean}"

        value = caches["geo"].get(key)
        if value is None:
            result = self.global_address(country=country_code, address1=state)

            try:
                record = result["Records"][0]
                value = record.get("AdministrativeArea") or state
            except (KeyError, IndexError):
                value = state
            caches["geo"].set(key, value, timeout=None)
        return value
