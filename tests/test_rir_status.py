import pytest

from peeringdb_server.models import Network, Organization


@pytest.mark.django_db
def test_network_auto_initial_rir_status():
    """
    Tests `Anytime` network update logic for RIR status handling
    laid out in https://github.com/peeringdb/peeringdb/issues/1280
    """

    org = Organization.objects.create(name="Test org", status="ok")
    net = Network.objects.create(name="Test net", asn=63311, status="ok", org=org)

    assert net.rir_status == "pending"

    net.rir_status = "missing"
    net.delete()

    assert net.rir_status == "missing"

    net.status = "ok"
    net.save()

    assert net.rir_status == "pending"
