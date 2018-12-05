import ipaddress
import re

import rdap
from rdap import RdapAsn
from rdap.exceptions import RdapException, RdapHTTPError, RdapNotFoundError
import requests

from peeringdb_server import settings


class RdapLookup(rdap.RdapClient):
    """
    Does RDAP lookups against defined URL.
    """

    def __init__(self):
        # create rdap config
        config = dict(
            bootstrap_url=settings.RDAP_URL.rstrip('/'),
            lacnic_apikey=settings.RDAP_LACNIC_APIKEY,
        )
        super(RdapLookup, self).__init__(config)


def network_is_bogon(network):
    """
    Returns if the passed ipaddress network is a bogon

    Arguments:
        - network <ipaddress.IPv4Network|ipaddress.IPv6Network>

    Return:
        - bool
    """

    return not network.is_global or network.is_reserved


def network_is_pdb_valid(network):
    """
    Return if the passed ipaddress network is in pdb valid
    address space

    Arguments:
        - network <ipaddress.IPv4Network|ipaddress.IPv6Network>

    Return:
        - bool
    """

    if network.is_multicast or network_is_bogon(network):
        return False

    if network.version == 4:
        return True

    # not allowed v6 blocks
    v6_invalid = [
        # 2002::/16 - RFC 3068 - 6to4 prefix
        0x2002,
        # 3ffe::/16 - RFC 5156 - used for the 6bone but was returned
        0x3ffe,
        # fec0::/10 - RFC 4291 - Reserved by IETF
        0xfec0,
        # ff00::/8 - RFC 4291 - Multicast
        0xff00,
    ]

    if int(network.network_address) >> 112 in v6_invalid:
        return False

    return True


def get_prefix_protocol(prefix):
    """
    Takes a network address space prefix string and returns
    a string describing the protocol

    Will raise a ValueError if it cannot determine protocol

    Returns:
        str: IPv4 or IPv6
    """

    try:
        ipaddress.IPv4Network(prefix)
        return "IPv4"
    except ipaddress.AddressValueError:
        try:
            ipaddress.IPv6Network(prefix)
            return "IPv6"
        except ipaddress.AddressValueError:
            raise ValueError("Prefix invalid")
