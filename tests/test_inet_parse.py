import pytest
import pytest_filedata


@pytest.mark.django_db
def assert_parsed(data, parsed):
    # dump in json format for easily adding expected
    print(f"echo \\\n'{data.dumps(parsed)}'\\\n > {data.path}/{data.name}.expected")
    assert data.expected == parsed


@pytest.mark.django_db
@pytest_filedata.RequestsData("rdap", real_http=True)
def test_rdap_asn_lookup(rdap, data_rdap_autnum):
    print(data_rdap_autnum.name)
    # asn = rdap.get_asn(205726)
    asn = rdap.get_asn(data_rdap_autnum.name)
    assert_parsed(data_rdap_autnum, asn.parsed())
