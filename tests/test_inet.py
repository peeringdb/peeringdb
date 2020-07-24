import pytest
import pytest_filedata
import ipaddress

from peeringdb_server.inet import RdapLookup, RdapNotFoundError, renumber_ipaddress


def test_rdap_asn_lookup(rdap):
    asn = rdap.get_asn(63311)
    assert asn.data
    assert asn.name
    assert asn.emails
    assert asn.org_name
    assert asn.org_address


def test_rdap_asn_lookup_not_found(rdap):
    with pytest.raises(RdapNotFoundError):
        rdap.get_asn(65535)


def test_rdap_asn_lookup_not_found(rdap):
    with pytest.raises(RdapNotFoundError):
        rdap.get_asn(9999999)


def test_mocker(rdap):
    with pytest_filedata.RequestsData("rdap"):
        asn = rdap.get_asn(63311)


@pytest_filedata.RequestsData("rdap")
def test_arin0(rdap):
    asn = rdap.get_asn(63311)
    assert asn.emails == ["neteng@20c.com"]


def test_recurse_contacts(rdap):
    asn = rdap.get_asn(3333)
    assert rdap == asn._rdapc
    assert len(asn.emails) > 1
    assert len(rdap.history) > 1


def test_renumber_ipaddress():
    ip4 = renumber_ipaddress(
        ipaddress.ip_address("206.41.110.48"),
        ipaddress.ip_network("206.41.110.0/24"),
        ipaddress.ip_network("206.41.111.0/24"),
    )

    assert ip4.compressed == "206.41.111.48"

    ip6 = renumber_ipaddress(
        ipaddress.ip_address("2001:504:41:110::20"),
        ipaddress.ip_network("2001:504:41:110::/64"),
        ipaddress.ip_network("2001:504:41:111::/64"),
    )

    assert ip6.compressed == "2001:504:41:111::20"

    with pytest.raises(ValueError):
        renumber_ipaddress(
            ipaddress.ip_address("2001:504:41:110::20"),
            ipaddress.ip_network("206.41.110.0/24"),
            ipaddress.ip_network("206.41.111.0/24"),
        )

    with pytest.raises(ValueError):
        renumber_ipaddress(
            ipaddress.ip_address("2001:504:41:110::20"),
            ipaddress.ip_network("2001:504:41:110::/64"),
            ipaddress.ip_network("206.41.111.0/24"),
        )

    with pytest.raises(ValueError):
        renumber_ipaddress(
            ipaddress.ip_address("206.41.110.48"),
            ipaddress.ip_network("206.41.0.0/21"),
            ipaddress.ip_network("206.41.111.0/24"),
        )
