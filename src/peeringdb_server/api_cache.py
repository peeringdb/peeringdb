"""
Handle loading of api-cache data.
"""

import json
import os

from django.conf import settings


class CacheRedirect(Exception):
    """
    Raise this error to redirect to cache response during viewset.get_queryset
    or viewset.list()

    Argument should be an APICacheLoader instance.
    """

    def __init__(self, loader):
        super().__init__(self, "Result to be loaded from cache")
        self.loader = loader


###############################################################################
# API CACHE LOADER


class APICacheLoader:
    """
    Checks if an API GET request qualifies for a cache load
    and if it does allows you to provide the cached result.
    """

    def __init__(self, viewset, qset, filters):
        request = viewset.request
        self.request = request
        self.qset = qset
        self.filters = filters
        self.model = viewset.model
        self.viewset = viewset
        self.depth = min(int(request.query_params.get("depth", 0)), 3)
        self.limit = int(request.query_params.get("limit", 0))
        self.skip = int(request.query_params.get("skip", 0))
        self.since = int(request.query_params.get("since", 0))
        self.fields = request.query_params.get("fields")
        if self.fields:
            self.fields = self.fields.split(",")
        self.path = os.path.join(
            settings.API_CACHE_ROOT,
            f"{viewset.model.handleref.tag}-{self.depth}.json",
        )

    def qualifies(self):
        """
        Check if request qualifies for a cache load.
        """

        # api cache use is disabled, no
        if not getattr(settings, "API_CACHE_ENABLED", False):
            return False
        # no depth and a limit lower than 251 seems like a tipping point
        # were non-cache retrieval is faster still
        if (
            not self.depth
            and self.limit
            and self.limit <= 250
            and getattr(settings, "API_CACHE_ALL_LIMITS", False) is False
        ):
            return False

        # filters have been specified, no
        if self.filters or self.since:
            return False
        # spatial search, no
        if getattr(self.qset, "spatial", False):
            return False
        # cache file non-existant, no
        if not os.path.exists(self.path):
            return False
        # request method is anything but GET, no
        if self.request.method != "GET":
            return False
        # primary key set in request, no
        if self.viewset.kwargs:
            return False

        return True

    def load(self):
        """
        Load the cached response according to tag and depth.
        """

        # read cache file
        with open(self.path) as f:
            data = json.load(f)

        data = data.get("data")

        # apply pagination
        if self.skip and self.limit:
            data = data[self.skip : self.skip + self.limit]
        elif self.skip:
            data = data[self.skip :]
        elif self.limit:
            data = data[: self.limit]

        if self.fields:
            for row in data:
                self.filter_fields(row)

        return {"results": data, "__meta": {"generated": os.path.getmtime(self.path)}}

    def filter_fields(self, row):
        """
        Remove any unwanted fields from the resultset
        according to the `fields` filter specified in the request.
        """
        for field in list(row.keys()):
            if field not in self.fields and field != "_grainy":
                del row[field]
