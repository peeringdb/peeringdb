"""
load and maintain global stats (displayed in peeringdb footer)
"""

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    Network,
    NetworkFacility,
    NetworkIXLan,
)


def stats():
    return {
        Network.handleref.tag: Network.handleref.filter(status="ok").count(),
        InternetExchange.handleref.tag: InternetExchange.handleref.filter(
            status="ok"
        ).count(),
        Facility.handleref.tag: Facility.handleref.filter(status="ok").count(),
        NetworkIXLan.handleref.tag: NetworkIXLan.handleref.filter(status="ok").count(),
        NetworkFacility.handleref.tag: NetworkFacility.handleref.filter(
            status="ok"
        ).count(),
        "automated_nets": Network.handleref.filter(allow_ixp_update=True).count(),
    }
