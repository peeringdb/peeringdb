"""
Utilties for geocoding and geo normalization
"""

from django.utils.translation import ugettext_lazy as _
import requests
import googlemaps


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
        returns the latitude, longitude field values of the specified
        address
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

        is_premise = (
            "street_address" in result[0]["types"]
            or "establishment" in result[0]["types"]
            or "premise" in result[0]["types"]
            or "subpremise" in result[0]["types"]
        )

        is_city = "locality" in result[0]["types"]

        is_state = "administrative_area_level_1" in result[0]["types"]

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


class Melissa:

    """
    Handles requests to the melissa global address
    service used for geocoding and address normalization
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

    def sanitize(self, **kwargs):

        """
        Takes an international address and sanitizes it
        using the melissa global address service
        """

        results = self.global_address(**kwargs)
        best = self.global_address_best_result(results)

        if not best:
            return {}

        return self.apply_global_address(kwargs, best)

    def sanitize_address_model(self, instance):

        """
        Takes an instance of AddressModel and
        runs it's address through the normalization
        process.

        Note that his will not actually change fields
        on the instance.

        Returns dict with normalized address data and
        geo coordinates
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
        Sends request to the global address service

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
            response = requests.get(
                self.global_address_url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            raise Timeout()
        except IOError as exc:
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
