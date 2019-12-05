"""
load and maintain global stats
"""

from peeringdb_server.models import (
    Network,
    InternetExchange,
    Facility,
    NetworkIXLan,
    NetworkFacility,
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
    }
