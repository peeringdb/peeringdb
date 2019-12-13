import ipaddress
import os
import pytest
import requests

from django.test import override_settings
from django.core.exceptions import ValidationError

from peeringdb_server.validators import (
    validate_address_space,
    validate_info_prefixes4,
    validate_info_prefixes6,
    validate_prefix_overlap,
)

from peeringdb_server.models import Organization, InternetExchange, IXLan, IXLanPrefix

pytestmark = pytest.mark.django_db

INVALID_ADDRESS_SPACES = [
    "0.0.0.0/1",
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    # FIXME: this fails still
    #'172.0.0.0/11',
    "172.16.0.0/12",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    # FIXME: this fails still
    #'224.0.0.0/3',
    "224.0.0.0/4",
    "240.0.0.0/4",
    "100.64.0.0/10",
    "0000::/8",
    "0064:ff9b::/96",
    "0100::/8",
    "0200::/7",
    "0400::/6",
    "0800::/5",
    "1000::/4",
    "2001::/33",
    "2001:0:8000::/33",
    "2001:0002::/48",
    "2001:0003::/32",
    "2001:10::/28",
    "2001:20::/28",
    "2001:db8::/32",
    "2002::/16",
    "3ffe::/16",
    "4000::/2",
    "4000::/3",
    "5f00::/8",
    "6000::/3",
    "8000::/3",
    "a000::/3",
    "c000::/3",
    "e000::/4",
    "f000::/5",
    "f800::/6",
    "fc00::/7",
    "fe80::/10",
    "fec0::/10",
    "ff00::/8",
]


@pytest.fixture(params=INVALID_ADDRESS_SPACES)
def prefix(request):
    return request.param


# @pytest.mark.django_db
def test_validate_address_space(prefix):
    """
    Tests peeringdb_server.validators.validate_address_space
    """
    with pytest.raises(ValidationError) as exc:
        validate_address_space(ipaddress.ip_network(str(prefix)))


@override_settings(DATA_QUALITY_MAX_PREFIX_V4_LIMIT=500000)
def test_validate_info_prefixes4():
    """
    Tests peeringdb_server.validators.validate_info_prefixes4
    """
    with pytest.raises(ValidationError):
        validate_info_prefixes4(500001)
    with pytest.raises(ValidationError):
        validate_info_prefixes4(-1)
    validate_info_prefixes4(500000)


@override_settings(DATA_QUALITY_MAX_PREFIX_V6_LIMIT=500000)
def test_validate_info_prefixes6():
    """
    Tests peeringdb_server.validators.validate_info_prefixes6
    """
    with pytest.raises(ValidationError):
        validate_info_prefixes6(500001)
    with pytest.raises(ValidationError):
        validate_info_prefixes6(-1)
    validate_info_prefixes6(500000)


@override_settings(
    DATA_QUALITY_MIN_PREFIXLEN_V4=24,
    DATA_QUALITY_MAX_PREFIXLEN_V4=24,
    DATA_QUALITY_MIN_PREFIXLEN_V6=48,
    DATA_QUALITY_MAX_PREFIXLEN_V6=48,
)
def test_validate_prefixlen():
    """
    Tests prefix length limits
    """
    with pytest.raises(ValidationError):
        validate_address_space("37.77.32.0/20")
    with pytest.raises(ValidationError):
        validate_address_space("131.72.77.240/28")
    with pytest.raises(ValidationError):
        validate_address_space("2403:c240::/32")
    with pytest.raises(ValidationError):
        validate_address_space("2001:504:0:2::/64")


@pytest.mark.django_db
def test_validate_prefix_overlap():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Text exchange", status="ok", org=org)
    ixlan = ix.ixlan

    pfx1 = IXLanPrefix.objects.create(
        ixlan=ixlan,
        protocol="IPv4",
        prefix=ipaddress.ip_network("198.32.125.0/24"),
        status="ok",
    )

    with pytest.raises(ValidationError) as exc:
        validate_prefix_overlap("198.32.124.0/23")
