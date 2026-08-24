"""
Minimal REST client used by the API test harness (pdb_api_test, tests/).

Vendored from twentyc.rpc (https://github.com/20c/twentyc.rpc), which is
unmaintained and calls pkg_resources.declare_namespace at import -- that made
it fail on setuptools >= 82, where pkg_resources is gone.
"""

from urllib import parse

import requests


class NotFoundException(LookupError):
    pass


class PermissionDeniedException(OSError):
    pass


class InvalidRequestException(ValueError):
    def __init__(self, msg, extra):
        super().__init__(self, msg)
        self.extra = extra


class RestClient:
    def __init__(self, url, **kwargs):
        """
        RESTful client
        """
        self.url = url
        self._url = parse.urlparse(self.url)
        self.user = None
        self.password = None
        self.timeout = None
        self.verbose = False

        # overwrite any param from keyword args
        for k in kwargs:
            if hasattr(self, k):
                setattr(self, k, kwargs[k])

    def url_update(self, **kwargs):
        return parse.urlunparse(self._url._replace(**kwargs))

    def _request(self, typ, id=0, method="GET", params=None, data=None, url=None):
        """
        send the request, return response obj
        """

        headers = {"Accept": "application/json"}
        auth = None

        if self.user:
            auth = (self.user, self.password)

        if not url:
            if id:
                url = f"{self.url}/{typ}/{id}"
            else:
                url = f"{self.url}/{typ}"

        return requests.request(
            method, url, params=params, data=data, auth=auth, headers=headers
        )

    def _throw(self, res, data):
        self.log("=====> %s" % data)
        err = data.get("meta", {}).get("error", "Unknown")
        if res.status_code < 600:
            if res.status_code == 404:
                raise NotFoundException("%d %s" % (res.status_code, err))
            elif res.status_code == 401 or res.status_code == 403:
                raise PermissionDeniedException("%d %s" % (res.status_code, err))
            elif res.status_code == 400:
                raise InvalidRequestException("%d %s" % (res.status_code, err), data)

        # Internal
        raise Exception("%d Internal error: %s" % (res.status_code, err))

    def _load(self, res):
        try:
            data = res.json()
        except ValueError:
            data = {}

        if res.status_code < 300:
            if not data:
                return []
            return data.get("data", [])

        self._throw(res, data)

    def _mangle_data(self, data):
        if "id" not in data and "pk" in data:
            data["id"] = data["pk"]
        if "_rev" in data:
            del data["_rev"]
        if "pk" in data:
            del data["pk"]
        if "_id" in data:
            del data["_id"]

    def log(self, msg):
        if self.verbose:
            print(msg)

    def all(self, typ, **kwargs):
        """
        List all of type
        Valid arguments:
            skip : number of records to skip
            limit : number of records to limit request to
        """
        return self._load(self._request(typ, params=kwargs))

    def get(self, typ, id, **kwargs):
        """
        Load type by id
        """
        return self._load(self._request(typ, id=id, params=kwargs))

    def create(self, typ, data, return_response=False):
        """
        Create new type
        Valid arguments:
            skip : number of records to skip
            limit : number of records to limit request to
        """
        res = self._request(typ, method="POST", data=data)
        if res.status_code != 201:
            try:
                data = res.json()
                self._throw(res, data)
            except ValueError as e:
                if not isinstance(e, InvalidRequestException):
                    self._throw(res, {})
                else:
                    raise

        loc = res.headers.get("location", None)
        if loc and loc.startswith("/"):
            return self._load(self._request(None, url=self.url_update(path=loc)))
        if return_response:
            return res.json()

        return self._load(self._request(None, url=loc))

    def update(self, typ, id, **kwargs):
        """
        update just fields sent by keyword args
        """
        return self._load(self._request(typ, id=id, method="PUT", data=kwargs))

    def save(self, typ, data):
        """
        Save the dataset pointed to by data (create or update)
        """
        if "id" in data:
            return self._load(
                self._request(typ, id=data["id"], method="PUT", data=data)
            )

        return self.create(typ, data)

    def rm(self, typ, id):
        """
        remove typ by id
        """
        return self._load(self._request(typ, id=id, method="DELETE"))

    def type_wrap(self, typ):
        return TypeWrap(self, typ)


class TypeWrap:
    def __init__(self, client, typ):
        self.client = client
        self.typ = typ

    def all(self, **kwargs):
        """
        List all
        """
        return self.client.all(self.typ, **kwargs)

    def get(self, id):
        """
        Load by id
        """
        return self.client.get(self.typ, id)

    def save(self, data):
        """
        Save object
        """
        return self.client.save(self.typ, data)

    def rm(self, id):
        """
        remove by id
        """
        return self.client.rm(self.typ, id)
