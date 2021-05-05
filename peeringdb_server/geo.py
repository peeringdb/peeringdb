"""
Utilties for geocoding and geo normalization
"""

import requests

class Timeout(IOError):
    def __init__(self):
        super().__init__("Geo location lookup has timed out")

class RequestError(IOError):
    def __init__(self, exc):
        super().__init__(f"{exc}")

class Melissa:

    global_address_url = "https://address.melissadata.net/v3/WEB/GlobalAddress/doGlobalAddress"

    # maps peeringdb address model field to melissa
    # global address result fields

    field_map = {
        "address1": "AddressLine1",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "zipcode": "PostalCode",
        "city": "Locality"
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
            return

        return self.apply_global_address(kwargs, best)


    def sanitize_address_model(self, instance):
        return self.sanitize(
            address1=instance.address1,
            city=instance.city,
            zipcode=instance.zipcode,
            country=instance.country
        )

    def apply_global_address(pdb_data, melissa_data):

        # map peeringdb address fields to melissa result fields

        for key in pdb_data.items():
            pdb_data[key] = melissa_data[self.field_map[key]]

        return pdb_data

    def global_address_params(**kwargs):

        return {
            "a1" : kwargs.get("address1"),
            "ctry": kwargs.get("country"),
            "loc": kwargs.get("city"),
            "postal": kwargs.get("zipcode"),
        }


    def global_address(**kwargs):

        params = self.global_address_params(**kwargs)
        params.update(id=self.key)

        headers = {
            "ACCEPT": "application/json",
        }


        try:
            response = requests.get(self.global_address_url, params=params, headers=headers, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise Timeout()
        except IOError as exc:
            raise RequestError(exc)

        if response.status != 200:
            raise RequestError(f"Returned status {response.status}")

        return response.json()

    def global_address_best_result(result):
        try:
            return result["Records"][0]
        except (KeyError, IndexError):
            return None

