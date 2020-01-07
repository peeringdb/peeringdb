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

# IANA reserved ASNs
# https://www.mail-archive.com/uknof@lists.uknof.org.uk/msg03395.html
ASN_IANA_RESERVED = (65552, 131071)

ASN_TRANS = (23456, 23456)

BOGON_ASN_RANGES = [
    # RFC 5398 - documentation 16-bit
    ASN_RFC_5398_16BIT,
    # RFC 5398 - documentation 32-bit
    ASN_RFC_5398_32BIT,
    # IANA Reserved
    ASN_IANA_RESERVED,
    # RFC 6996 - private 16-bit
    ASN_RFC_6996_16BIT,
    # RFC 6996 - private 32-bit
    ASN_RFC_6996_32BIT,
    # RFC 7003 - last asn 16-bit
    ASN_LAST_16BIT,
    # RFC 7003 - last asn 32-bit
    ASN_LAST_32BIT,
    # trans
    ASN_TRANS,
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
            "name": name,
            "org_name": name,
            "org_address": None,
            "emails": [],
        }


class RdapLookup(rdap.RdapClient):
    """
    Does RDAP lookups against defined URL.
    """

    def __init__(self):
        # create rdap config
        config = dict(
            bootstrap_url=settings.RDAP_URL.rstrip("/"),
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
                raise RdapException(
                    _("ASNs in this range " "are not allowed in this environment")
                )
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
        0x3FFE,
        # fec0::/10 - RFC 4291 - Reserved by IETF
        0xFEC0,
        # ff00::/8 - RFC 4291 - Multicast
        0xFF00,
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


def renumber_ipaddress(ipaddr, old_prefix, new_prefix):

    """
    Renumber an ipaddress from old prefix to new prefix

    Arguments:
        - ipaddr (ipaddress.ip_address)
        - old_prefix (ipaddress.ip_network)
        - new_prefix (ipaddress.ip_network)

    Returns:
        - ipaddress.ip_address: renumbered ip address
    """

    # validate that old and new prefix are compatible

    if old_prefix == new_prefix:
        raise ValueError("New and old prefix are identical")

    if old_prefix.version != new_prefix.version:
        raise ValueError("New prefix needs to be the same version as old prefix")

    if new_prefix.version != ipaddr.version:
        raise ValueError("Prefix version needs to be same version as ip address")

    if old_prefix.prefixlen != new_prefix.prefixlen:
        raise ValueError("New prefix needs to be of same length")

    if ipaddr not in old_prefix:
        raise ValueError("Ip address not within old prefix")

    if ipaddr.version == 4:
        delimiter = "."
    else:
        delimiter = ":"

    # split prefixes and ipaddress into their octets

    old_octets, old_mask = old_prefix.exploded.split("/")
    new_octets, new_mask = new_prefix.exploded.split("/")
    old_octets = old_octets.split(delimiter)
    new_octets = new_octets.split(delimiter)
    ip_octets = ipaddr.exploded.split(delimiter)

    # get netmask octets so we can see which are to be replace

    netmask_octets = new_prefix.netmask.exploded.split(delimiter)

    i = 0

    for octet in netmask_octets:

        # replace any octet that is not a zero in the netmask

        if (ipaddr.version == 4 and int(octet) > 0) or (
            ipaddr.version == 6 and octet != "0000"
        ):
            ip_octets[i] = new_octets[i]
        i += 1

    # return renumbered ipaddress

    return ipaddress.ip_address(
        "{}".format(delimiter.join([str(o) for o in ip_octets]))
    )


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip
