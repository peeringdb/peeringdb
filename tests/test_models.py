import pytest

from peeringdb_server.models import Network


def test_network_legacy_info_type():

    network = Network(
        asn=1, name="Test Network", irr_as_set="AS-TEST", info_types=["Content", "NSP"]
    )

    # legacy field mapped to info_type (first element)
    assert network.info_type == "Content"
    assert network.info_types == ["Content", "NSP"]

    # trying to instantiate a model with `info_type` should
    # raise an error

    with pytest.raises(AttributeError):
        Network(asn=1, name="Test Network", irr_as_set="AS-TEST", info_type="Content")
