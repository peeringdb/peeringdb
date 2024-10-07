"""
Load and maintain global stats (displayed in peeringdb footer).
"""

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
)

__STATS = {"data": {}, "mod": None}


def reset_stats():
    """
    Resets global stats to empty. Useful to reset for testing purposes.
    """
    __STATS["data"] = {}
    __STATS["mod"] = None


def gen_stats():
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
        NetworkIXLan.handleref.tag: NetworkIXLan.handleref.filter(status="ok").count(),
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


def stats():
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


def get_fac_stats(netfac, ixfac):
    return {
        "networks": netfac.filter(status="ok").count(),
        "ix": ixfac.filter(status="ok").count(),
    }


def get_ix_stats(netixlan, ixlan):
    peer_count = netixlan.values("network").distinct().filter(status="ok").count()
    connections_count = netixlan.filter(ixlan=ixlan, status="ok").count()
    open_peer_count = (
        netixlan.values("network")
        .distinct()
        .filter(network__policy_general="Open", status="ok")
        .count()
    )
    ipv6_percentage = 0
    total_speed = 0

    try:
        ipv6_percentage = int(
            (
                netixlan.filter(status="ok", ixlan=ixlan, ipaddr6__isnull=False).count()
                / netixlan.filter(ixlan=ixlan, status="ok").count()
            )
            * 100
        )
    except ZeroDivisionError:
        pass

    for n in netixlan.filter(status="ok", ixlan=ixlan):
        total_speed += n.speed

    return {
        "peer_count": peer_count,
        "connection_count": connections_count,
        "open_peer_count": open_peer_count,
        "ipv6_percentage": ipv6_percentage,
        "total_speed": total_speed,
    }
