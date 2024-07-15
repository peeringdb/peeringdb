import ipaddress

import pytest
import pytest_filedata

from peeringdb_server.inet import RdapNotFoundError, renumber_ipaddress


@pytest.mark.django_db
def test_rdap_asn_lookup(rdap):
    asn = rdap.get_asn(63311)
    assert asn.data
    assert asn.name
    assert asn.emails
    assert asn.org_name
    assert asn.org_address


@pytest.mark.django_db
def test_rdap_asn_lookup_not_found(rdap):
    with pytest.raises(RdapNotFoundError):
        rdap.get_asn(9999999)


@pytest.mark.django_db
def test_mocker(rdap):
    with pytest_filedata.RequestsData("rdap"):
        asn = rdap.get_asn(63311)


@pytest.mark.django_db
@pytest_filedata.RequestsData("rdap")
def test_arin0(rdap):
    asn = rdap.get_asn(63311)
    assert asn.emails == ["neteng@20c.com"]


# looks like this ASN no longer provides the required condition for testing.
# this should be tested in the RDAP module anyhow
# skipping for now, but should probably just remove
# TODO
@pytest.mark.django_db
@pytest.mark.skip(
    reason="looks like this ASN no longer provides the required condition for testing."
)
def test_recurse_contacts(rdap):
    asn = rdap.get_asn(3333)
    assert rdap == asn._rdapc
    assert len(asn.emails) > 1
    assert len(rdap.history) > 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "ip,old_prefix,new_prefix,valid",
    [
        # Test successes
        ("206.41.110.48", "206.41.110.0/24", "206.41.111.0/24", "206.41.111.48"),
        ("206.41.110.48", "206.41.110.0/25", "206.41.111.0/24", "206.41.111.48"),
        ("206.41.110.48", "206.41.110.0/25", "206.41.111.0/25", "206.41.111.48"),
        ("206.41.116.101", "206.41.116.0/23", "206.42.116.0/23", "206.42.116.101"),
        ("206.41.116.101", "206.41.116.0/23", "206.42.116.0/24", "206.42.116.101"),
        ("206.41.116.101", "206.41.116.0/23", "206.42.116.0/25", "206.42.116.101"),
        (
            "2001:504:41:110::20",
            "2001:504:41:110::/64",
            "2001:504:41:111::/64",
            "2001:504:41:111::20",
        ),
        (
            "2001:504:41:110::20",
            "2001:504:41:110::/64",
            "2001:504:42:110::/60",
            "2001:504:42:110::20",
        ),
        (
            "2001:504:41:110::20",
            "2001:504:41:110::/64",
            "2001:504:42::/48",
            "2001:504:42:110::20",
        ),
        # Test failures
        ("2001:504:41:110::20", "206.41.110.0/24", "206.41.111.0/24", False),
        ("2001:504:41:110::20", "2001:504:41:110::/64", "206.41.111.0/24", False),
        ("206.41.110.48", "206.41.110.0/25", "206.41.111.128/25", False),
        ("206.41.116.101", "206.41.116.0/23", "206.41.110.0/23", False),
    ],
)
def test_renumber_ipaddress(ip, old_prefix, new_prefix, valid):
    ip = ipaddress.ip_address(ip)
    old_prefix = ipaddress.ip_network(old_prefix)
    new_prefix = ipaddress.ip_network(new_prefix)

    if valid:
        renumbered = renumber_ipaddress(ip, old_prefix, new_prefix)
        assert renumbered.compressed == valid
    else:
        with pytest.raises(ValueError):
            renumber_ipaddress(ip, old_prefix, new_prefix)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "input_str,compressed",
    [
        ("2001:0db8::0001", "2001:db8::1"),
        ("2001:db8:0:0:0:0:2:1", "2001:db8::2:1"),
        ("2001:db8::0:1", "2001:db8::1"),
        ("2001:7f8:f2:e1::af21:3376:1", "2001:7f8:f2:e1:0:af21:3376:1"),
        ("2001:db8::1:1:1:1:1", "2001:db8:0:1:1:1:1:1"),
        ("2001:db8:0:0:1:0:0:1", "2001:db8::1:0:0:1"),
        ("2001:7F8:F2:E1:0:AF21:3376:1", "2001:7f8:f2:e1:0:af21:3376:1"),
    ],
    ids=[
        "4.1 handling leading zeros",
        "4.2.1 shorten as much as possible (1)",
        "4.2.1 shorten as much as possible (2)",
        "4.2.2 handling one 16-bit 0 field (1)",
        "4.2.2 handling one 16-bit 0 field (2)",
        "4.2.3 choice in placement of ::",
        "4.3 lowercase",
    ],
)
def test_ipaddress6_compression(input_str, compressed):
    """
    Testing if the ipaddress string formatting
    is compliant with RFC 5952
    https://tools.ietf.org/html/rfc5952#section-4

    Ids of parameters denote which rule in the spec
    the test is demonstrating
    """
    ipv6 = ipaddress.ip_address(input_str)
    assert str(ipv6) == compressed
