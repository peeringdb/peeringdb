import ipaddress
import re

import rdap
from rdap import RdapAsn
from rdap.exceptions import RdapException, RdapHTTPError, RdapNotFoundError
import requests
from django.utils.translation import ugettext_lazy as _

from peeringdb_server import settings

# RFC 5398 documentation asn range
ASN_RFC_5398_16BIT = (64496, 64511)
ASN_RFC_5398_32BIT = (65536, 65551)

# RFC 6996 private asn range
ASN_RFC_6996_16BIT = (64512, 65534)
ASN_RFC_6996_32BIT = (4200000000, 4294967294)

# RFC 7003 last asn
ASN_LAST_16BIT = (65535, 65535)
ASN_LAST_32BIT = (4294967295, 4294967295)

ASN_TRANS = (23456, 23456)

BOGON_ASN_RANGES = [
    # RFC 5398 - documentation 16-bit
    ASN_RFC_5398_16BIT,
    # RFC 5398 - documentation 32-bit
    ASN_RFC_5398_32BIT,
    # RFC 6996 - private 16-bit
    ASN_RFC_6996_16BIT,
    # RFC 6996 - private 32-bit
    ASN_RFC_6996_32BIT,
    # RFC 7003 - last asn 16-bit
    ASN_LAST_16BIT,
    # RFC 7003 - last asn 32-bit
    ASN_LAST_32BIT,
    # trans
    ASN_TRANS
]

# the following bogon asn ranges are allowed on envionments
# where TUTORIAL_MODE is set to True

TUTORIAL_ASN_RANGES = [
    # RFC 5398 - documentation 16-bit
    ASN_RFC_5398_16BIT,
    # RFC 5398 - documentation 32-bit
    ASN_RFC_5398_32BIT,
    # RFC 6996 - private 16-bit
    ASN_RFC_6996_16BIT,
    # RFC 6996 - private 32-bit
    ASN_RFC_6996_32BIT,
]


class BogonAsn(rdap.RdapAsn):

    """
    On tutorial mode environments we will return an instance
    of this to provide an rdapasn result for asns in the
    private and documentation ranges
    """

    def __init__(self, asn):
        name = "AS{}".format(asn)
        self._parsed = {
            "name":name,
            "org_name":name,
            "org_address":None,
            "emails":[]
        }


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


    def get_asn(self, asn):
        """
        We handle asns that fall into the private/documentation ranges
        manually - others are processed normally through rdap lookup
        """

        if asn_is_bogon(asn):
            if settings.TUTORIAL_MODE and asn_is_in_ranges(asn, TUTORIAL_ASN_RANGES):
                return BogonAsn(asn)
            else:
                raise RdapException(_("ASNs in this range " \
                                   "are not allowed in this environment"))
        return super(RdapLookup, self).get_asn(asn)



def asn_is_bogon(asn):
    """
    Test if an asn is bogon by being either in the documentation
    or private asn ranges

    Arguments:
        - asn<int>

    Return:
        - bool: True if in bogon range
    """
    return asn_is_in_ranges(asn, BOGON_ASN_RANGES)


def asn_is_in_ranges(asn, ranges):
    """
    Test if an asn falls within any of the ranges provided

    Arguments:
        - asn<int>
        - ranges<list[tuple(min,max)]>

    Return:
        - bool
    """
    asn = int(asn)
    for as_range in ranges:
        if asn >= as_range[0] and asn <= as_range[1]:
            return True
    return False


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


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


