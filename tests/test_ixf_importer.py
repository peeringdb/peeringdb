import json
from pprint import pprint

import pytest

from peeringdb_server import ixf


@pytest.mark.django_db
def test_vlan_sanitize(data_ixf_vlan):
    """
    test that various vlan_list setups are sanitized correctly
    """
    importer = ixf.Importer()
    sanitized = importer.sanitize_vlans(json.loads(data_ixf_vlan.input)["vlan_list"])
    assert sanitized == data_ixf_vlan.expected["vlan_list"]


@pytest.mark.django_db
def test_connections_match(data_ixf_connections_match):
    importer = ixf.Importer()
    connection_list = json.loads(data_ixf_connections_match.input)["connection_list"]
    cxn_match = importer.connections_match(connection_list[0], connection_list[1])
    assert cxn_match == data_ixf_connections_match.expected


@pytest.mark.django_db
def test_match_vlans_across_connections(data_ixf_connections):
    """
    test that various vlan_list setups are sanitized correctly
    """
    importer = ixf.Importer()
    sanitized = importer.match_vlans_across_connections(
        json.loads(data_ixf_connections.input)["connection_list"]
    )
    pprint(sanitized)
    assert sanitized == data_ixf_connections.expected["connection_list"]
