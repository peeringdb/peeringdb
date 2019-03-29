from peeringdb_server.inet import RdapLookup, RdapNotFoundError
import pytest
import pytest_filedata


def test_rdap_asn_lookup(rdap):
    asn = rdap.get_asn(63311)
    assert asn.raw
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
    assert asn.emails == ['neteng@20c.com']


def test_recurse_contacts(rdap):
    asn = rdap.get_asn(3333)
    assert rdap == asn._rdapc
    assert len(asn.emails) > 1
    assert len(rdap.history) > len(asn.emails)
