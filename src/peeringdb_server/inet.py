"""
RDAP lookup and validation.

Network validation.

Prefix renumbering.
"""

import ipaddress

import rdap
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from rdap.exceptions import RdapException, RdapNotFoundError

from peeringdb_server import settings

RdapAsn = rdap.RdapAsn  # noqa
RdapNetwork = rdap.objects.RdapNetwork  # noqa

# Valid IRR Source values
# reference: http://www.irr.net/docs/list.html
IRR_SOURCE = (
    "AFRINIC",
    "ALTDB",
    "APNIC",
    "ARIN",
    "BELL",
    "BBOI",
    "CANARIE",
    "IDNIC",
    "JPIRR",
    "LACNIC",
    "LEVEL3",
    "NESTEGG",
    "NTTCOM",
    "PANIX",
    "RADB",
    "REACH",
    "RIPE",
    "TC",
)

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


class RdapInvalidRange(RdapException):
    pass


class BogonAsn(rdap.RdapAsn):
    """
    On tutorial mode environments, return an instance
    of this to provide an rdapasn result for asns in the
    private and documentation ranges.
    """

    def __init__(self, asn):
        name = f"AS{asn}"
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
            self_bootstrap=settings.RDAP_SELF_BOOTSTRAP,
            bootstrap_dir=settings.RDAP_BOOTSTRAP_DIR,
            ignore_recurse_errors=settings.RDAP_IGNORE_RECURSE_ERRORS,
            lacnic_apikey=settings.RDAP_LACNIC_APIKEY,
            timeout=10,
        )
        super().__init__(config)

    def get_asn(self, asn):
        """
        Handle asns that fall into the private/documentation ranges
        manually - others are processed normally through rdap lookup.
        """

        if asn_is_bogon(asn):
            if settings.TUTORIAL_MODE and asn_is_in_ranges(asn, TUTORIAL_ASN_RANGES):
                return BogonAsn(asn)
            else:
                # Issue 995: Block registering private ASN ranges
                # raise RdapInvalidRange if ASN is in private or reserved range
                raise RdapInvalidRange()
        return super().get_asn(asn)


def rir_status_is_ok(rir_status: str) -> bool:
    """
    Returns True if the rir_status is ok (allocated or assigned) or not
    """
    return rir_status in [
        # actual rir statuses returned via rdap rir assigment check
        # that we consider 'ok'
        "assigned",
        "allocated",
        # peeringdb initial status (after creation or undeletion)
        # should be treated as `ok`
        "pending",
        "ok",
    ]


def rdap_pretty_error_message(exc):
    """
    Take an RdapException instance and return a customer friendly
    error message (str).
    """

    if isinstance(exc, RdapNotFoundError):
        return _("This ASN is not assigned by any RIR")
    if isinstance(exc, RdapInvalidRange):
        return _("ASNs in this range are private or reserved")  #
    if isinstance(exc, RdapException):
        return f"{exc}"

    return _(
        "Unable to retrieve RDAP data. If the issue persists, please contact {support_email}."
    ).format(
        support_email=django_settings.DEFAULT_FROM_EMAIL,
    )


def asn_is_bogon(asn):
    """
    Test if an asn is bogon by being either in the documentation
    or private asn ranges.

    Arguments:
        - asn<int>

    Return:
        - bool: True if in bogon range
    """
    return asn_is_in_ranges(asn, BOGON_ASN_RANGES)


def asn_is_in_ranges(asn, ranges):
    """
    Test if an asn falls within any of the ranges provided.

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
    Return if the passed ipaddress network is a bogon.

    Arguments:
        - network <ipaddress.IPv4Network|ipaddress.IPv6Network>

    Return:
        - bool
    """

    return not network.is_global or network.is_reserved


def network_is_pdb_valid(network):
    """
    Return if the passed ipaddress network is in pdb valid
    address space.

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
    Take a network address space prefix string and return
    a string describing the protocol.

    Will raise a ValueError if it cannot determine protocol.

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
    Renumber an ipaddress from old prefix to new prefix.

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

    if ipaddr not in old_prefix:
        raise ValueError("Ip address not within old prefix")

    if ipaddr.version == 4:
        delimiter = "."
    else:
        delimiter = ":"

    ip_octets = ipaddr.exploded.split(delimiter)
    net_octets = new_prefix.network_address.exploded.split(delimiter)
    hostmask = [o for o in new_prefix.hostmask.exploded.split(delimiter)]

    i = 0
    for octet in hostmask:
        if (ipaddr.version == 4 and int(octet) == 0) or (
            ipaddr.version == 6 and octet == "0000"
        ):
            ip_octets[i] = net_octets[i]
        i += 1

    new_ip = ipaddress.ip_address(f"{delimiter.join([str(o) for o in ip_octets])}")

    if new_ip not in new_prefix:
        raise ValueError(
            f"Altered ip address `{new_ip}` not contained in `{new_prefix}`"
        )

    return new_ip


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip
