import pytest

from peeringdb_server.models import Network, Organization


@pytest.mark.django_db
def test_network_auto_initial_rir_status():

    """
    Tests `Anytime` network update logic for RIR status handling
    laid out in https://github.com/peeringdb/peeringdb/issues/1280

    Anytime a network is saved:

    if an ASN is added, set rir_status="ok" and set rir_status_updated=created
    if an ASN is deleted (manually), set rir_status="notok" and set rir_status_updated=updated
    if an ASN is re-added, set rir_status="ok" and set rir_status_updated=updated
    """

    org = Organization.objects.create(name="Test org", status="ok")
    net = Network.objects.create(name="Test net", asn=63311, status="ok", org=org)

    assert net.rir_status == "pending"

    net.delete()

    assert net.rir_status == ""

    net.status = "ok"
    net.save()

    assert net.rir_status == "pending"
