"""
Load and maintain global stats (displayed in peeringdb footer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from peeringdb_server.models import (
    Campus,
    Carrier,
    Facility,
    InternetExchange,
    Network,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    User,
    live_statuses,
)

if TYPE_CHECKING:
    from datetime import datetime
    from typing import TypedDict

    from django.db.models import QuerySet

    from peeringdb_server.models import InternetExchangeFacility, IXLan

    class GlobalStats(TypedDict):
        data: dict[str, int]
        mod: datetime | None


__STATS: GlobalStats = {"data": {}, "mod": None}


def reset_stats() -> None:
    """
    Resets global stats to empty. Useful to reset for testing purposes.
    """
    __STATS["data"] = {}
    __STATS["mod"] = None


def gen_stats() -> None:
    """
    Regenerates global statics to stats.__STATS['data']
    """

    __STATS["data"] = {
        Network.handleref.tag: Network.handleref.filter(status="ok").count(),
        InternetExchange.handleref.tag: InternetExchange.handleref.filter(
            status="ok"
        ).count(),
        Facility.handleref.tag: Facility.handleref.filter(status="ok").count(),
        Carrier.handleref.tag: Carrier.handleref.filter(status="ok").count(),
        Campus.handleref.tag: Campus.handleref.filter(status="ok").count(),
        # live netixlan statuses include "not-operational" (#1742)
        NetworkIXLan.handleref.tag: NetworkIXLan.handleref.filter(
            status__in=live_statuses(NetworkIXLan)
        ).count(),
        NetworkFacility.handleref.tag: NetworkFacility.handleref.filter(
            status="ok"
        ).count(),
        "automated_nets": Network.handleref.filter(
            status="ok", allow_ixp_update=True
        ).count(),
        "organizations": Organization.objects.filter(status="ok").count(),
        "registered_users": User.objects.filter(
            groups__id=settings.USER_GROUP_ID
        ).count(),
    }
    __STATS["mod"] = timezone.now()


def stats() -> dict[str, int]:
    """
    Returns dict of global statistics

    Will return cached statistics according to `GLOBAL_STATS_CACHE_DURATION` setting
    """

    if __STATS["mod"]:
        diff = timezone.now() - __STATS["mod"]
        if diff.total_seconds() < settings.GLOBAL_STATS_CACHE_DURATION:
            return __STATS["data"]

    gen_stats()
    return __STATS["data"]


def get_fac_stats(
    netfac: QuerySet[NetworkFacility], ixfac: QuerySet[InternetExchangeFacility]
) -> dict[str, int]:
    return {
        "networks": netfac.filter(status="ok").count(),
        "ix": ixfac.filter(status="ok").count(),
    }


def get_ix_stats(netixlan: QuerySet[NetworkIXLan], ixlan: IXLan) -> dict[str, int]:
    # live netixlan statuses include "not-operational" (#1742) -- those
    # members still count as peers/connections
    live = live_statuses(NetworkIXLan)
    peer_count = netixlan.values("network").distinct().filter(status__in=live).count()
    connections_count = netixlan.filter(ixlan=ixlan, status__in=live).count()
    open_peer_count = (
        netixlan.values("network")
        .distinct()
        .filter(network__policy_general="Open", status__in=live)
        .count()
    )
    ipv6_percentage = 0
    total_speed = 0

    try:
        ipv6_percentage = int(
            (
                netixlan.filter(
                    status__in=live, ixlan=ixlan, ipaddr6__isnull=False
                ).count()
                / netixlan.filter(ixlan=ixlan, status__in=live).count()
            )
            * 100
        )
    except ZeroDivisionError:
        pass

    for n in netixlan.filter(status__in=live, ixlan=ixlan):
        total_speed += n.speed

    return {
        "peer_count": peer_count,
        "connection_count": connections_count,
        "open_peer_count": open_peer_count,
        "ipv6_percentage": ipv6_percentage,
        "total_speed": total_speed,
    }
