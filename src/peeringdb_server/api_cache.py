"""
Handle loading of api-cache data.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Protocol

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response

from peeringdb_server.models import IXLan, NetworkContact, live_statuses
from peeringdb_server.pagination import UnlimitedIfNoPagePagination

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from rest_framework.request import Request

    class _CacheViewset(Protocol):
        """Minimal structural view of the DRF viewset APICacheLoader reads.

        The concrete viewsets are built dynamically in rest.py and carry a
        ``model`` attribute (a peeringdb handleref model class) that no base
        class declares, so a Protocol captures exactly the surface used here.
        """

        request: Request
        # peeringdb handleref model class; ``.handleref`` is a dynamic manager,
        # so the class itself stays unconstrained.
        model: Any
        kwargs: dict[str, Any]


logger = logging.getLogger(__name__)

# Rows whose visibility the serve-time permission check reads from the cache
# file itself, and the public-only contact id lists (#513): tag of the cache
# file -> lowest depth at which it embeds them. A visibility change or
# deletion after generation is applied from the database at load time (#523).
CONTACT_CACHE_DEPTHS = {"poc": 0, "net": 1, "org": 3, "ixlan": 3}
IXLAN_CACHE_DEPTHS = {"ixlan": 0, "ix": 2}

# the keys under which those files nest them
NESTED_CACHE_KEYS = ("poc_set", "net_set", "ixlan_set")

# Cached rows were rendered with every field, so a visibility is only ever
# narrowed at serve time: widening it would publish values from before the
# change.
VISIBILITY_RANK = {"public": 0, "users": 1, "private": 2}

# Rows changed shortly before the recorded generation time are re-checked as
# well, covering clock skew between hosts and long transactions that commit
# while the cache is being generated. Re-checking only ever narrows.
CHANGE_LOOKBACK = datetime.timedelta(hours=1)


def narrows(cached: str, current: str) -> bool:
    """
    Return whether visibility `current` is narrower than `cached`.
    """
    rank = VISIBILITY_RANK.get(current.lower())
    return rank is not None and rank > VISIBILITY_RANK.get(cached.lower(), rank)


class CacheRedirect(Exception):
    """
    Raise this error to redirect to cache response during viewset.get_queryset
    or viewset.list()

    Argument should be an APICacheLoader instance.
    """

    def __init__(self, loader: APICacheLoader) -> None:
        super().__init__(self, "Result to be loaded from cache")
        self.loader = loader


###############################################################################
# API CACHE LOADER


class APICacheLoader:
    """
    Checks if an API GET request qualifies for a cache load
    and if it does allows you to provide the cached result.
    """

    def __init__(
        self,
        viewset: _CacheViewset,
        qset: QuerySet[Any],
        filters: dict[str, Any],
        query_adjusted: bool = False,
    ) -> None:
        request = viewset.request
        self.request = request
        self.qset = qset
        self.filters = filters
        self.query_adjusted = query_adjusted
        self.model = viewset.model
        self.viewset = viewset
        self.depth = min(int(request.query_params.get("depth", 0)), 3)
        self.limit = int(request.query_params.get("limit", 0))
        self.skip = int(request.query_params.get("skip", 0))
        self.since = int(request.query_params.get("since", 0))
        self.page = request.query_params.get("page")
        self.fields = request.query_params.get("fields")
        if self.fields:
            self.fields = self.fields.split(",")
        self.path = os.path.join(
            settings.API_CACHE_ROOT,
            f"{viewset.model.handleref.tag}-{self.depth}.json",
        )

    def qualifies(self) -> bool:
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

        # filters have been specified or query was adjusted by serializer, no
        if self.filters or self.since or self.query_adjusted:
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

    def load(self) -> dict[str, Any] | Response:
        """
        Load the cached response according to tag and depth.
        """
        try:
            # read cache file
            with open(self.path) as f:
                cache = json.load(f)
                data = cache.get("data")

            data = self.apply_changes_since_generation(
                data, self.generated_at(cache.get("meta") or {})
            )

            # apply skip/limit pagination
            if self.skip and self.limit:
                data = data[self.skip : self.skip + self.limit]
            elif self.skip:
                data = data[self.skip :]
            elif self.limit:
                data = data[: self.limit]

            # apply page-based pagination
            meta: dict[str, Any] = {"generated": os.path.getmtime(self.path)}
            if self.page:
                paginator = UnlimitedIfNoPagePagination()
                data = paginator.paginate_queryset(data, self.request)
                if getattr(paginator, "pagination_applied", False):
                    meta["pagination"] = paginator.build_pagination_meta()

            if self.fields:
                for row in data:
                    self.filter_fields(row)

            return {
                "results": data,
                "__meta": meta,
            }
        except json.JSONDecodeError as e:
            logger.error(f"Error cache data is corrupted: {str(e)}", exc_info=True)
            return Response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data={
                    "cache_corrupted": True,
                    "detail": "Cache data is corrupted. The error has been logged, please try again later.",
                },
            )

    def generated_at(self, meta: dict[str, Any]) -> datetime.datetime:
        """
        Return when the data in the cache file was read from the database.

        This is the earlier of the generation time recorded in the file and
        the file's modification time: `pdb_api_cache --date` records a date
        that can lie after the actual read.
        """
        timestamps = [os.path.getmtime(self.path)]
        if isinstance(meta.get("generated"), int | float):
            timestamps.append(meta["generated"])
        return datetime.datetime.fromtimestamp(min(timestamps), tz=datetime.UTC)

    def changed_visibility(
        self,
        model: type[NetworkContact] | type[IXLan],
        field: str,
        since: datetime.datetime,
    ) -> dict[int, str | None]:
        """
        Return id -> current visibility of the rows of `model` updated since
        `since`, with None for rows that are no longer live.
        """
        live = live_statuses(model)
        rows = model.objects.filter(updated__gte=since - CHANGE_LOOKBACK)
        return {
            pk: (visible if row_status in live else None)
            for pk, row_status, visible in rows.values_list("id", "status", field)
        }

    def apply_changes_since_generation(
        self, data: list[Any], generated: datetime.datetime
    ) -> list[Any]:
        """
        Apply restrictions made since the file was generated to the contacts
        and exchange LANs in the cached rows: drop the ones deleted, and give
        the others their current visibility where it is narrower, so the
        permission check at serve time hides what is no longer public.
        """
        tag = self.model.handleref.tag
        contacts: dict[int, str | None] = {}
        ixlans: dict[int, str | None] = {}

        if self.depth >= CONTACT_CACHE_DEPTHS.get(tag, self.depth + 1):
            contacts = self.changed_visibility(NetworkContact, "visible", generated)
        if self.depth >= IXLAN_CACHE_DEPTHS.get(tag, self.depth + 1):
            ixlans = self.changed_visibility(
                IXLan, "ixf_ixp_member_list_url_visible", generated
            )

        if not contacts and not ixlans:
            return data
        return self._apply_visibility_to_rows(data, contacts, ixlans)

    def _apply_visibility_to_rows(
        self,
        rows: list[Any],
        contacts: dict[int, str | None],
        ixlans: dict[int, str | None],
    ) -> list[Any]:
        # list items are serialized rows (dicts) or ids at the depth limit
        kept = []
        for row in rows:
            if isinstance(row, dict) and not self._apply_visibility_to_row(
                row, contacts, ixlans
            ):
                continue
            kept.append(row)
        return kept

    def _apply_visibility_to_row(
        self,
        row: dict[str, Any],
        contacts: dict[int, str | None],
        ixlans: dict[int, str | None],
    ) -> bool:
        """
        Update the row in place and return False if it is to be dropped.
        """
        # row values are heterogeneous serialized field values
        namespace = row.get("_grainy")
        pk = row.get("id")

        # a contact's namespace ends in its visibility (NetworkContact's
        # grainy namespace_instance); an exchange LAN carries the exchange's
        # namespace and its visibility in a field of its own
        if namespace and ".poc_set." in namespace and pk in contacts:
            visible = contacts[pk]
            if visible is None:
                return False
            prefix, cached = namespace.rsplit(".", 1)
            if narrows(cached, visible):
                row["_grainy"] = f"{prefix}.{visible.lower()}"
                if "visible" in row:
                    row["visible"] = visible
        elif "ixf_ixp_member_list_url_visible" in row and pk in ixlans:
            visible = ixlans[pk]
            if visible is None:
                return False
            if narrows(row["ixf_ixp_member_list_url_visible"], visible):
                row["ixf_ixp_member_list_url_visible"] = visible

        for key in NESTED_CACHE_KEYS:
            value = row.get(key)
            if not value or not isinstance(value, list):
                continue
            if key == "poc_set" and isinstance(value[0], int):
                # an id list holds contacts that were public at generation
                row[key] = [
                    poc_id
                    for poc_id in value
                    if contacts.get(poc_id, "Public") == "Public"
                ]
            else:
                row[key] = self._apply_visibility_to_rows(value, contacts, ixlans)
        return True

    def filter_fields(self, row: dict[str, Any]) -> None:
        """
        Remove any unwanted fields from the resultset
        according to the `fields` filter specified in the request.
        """
        for field in list(row.keys()):
            if field not in self.fields and field != "_grainy":
                del row[field]
