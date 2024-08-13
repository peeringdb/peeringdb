import pytest
from django.core.management import call_command

from peeringdb_server.models import Network, NetworkContact, ProtectedAction


def assert_protected(entity):
    """
    helper function to test that an object is currently
    not deletable
    """
    with pytest.raises(ProtectedAction):
        entity.delete()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [
        ("Technical"),
        ("Policy"),
        ("NOC"),
    ],
)
def test_delete_network(role):
    """
    Test deleting the network if there are still poc and netixlan
    """

    call_command("pdb_generate_test_data", limit=2, commit=True)

    net = Network.objects.first()

    poc = NetworkContact.objects.create(status="ok", role=role, network=net)
    assert poc.status == "ok"

    assert_protected(poc)

    for netixlan in net.netixlan_set_active.all():
        assert netixlan.status == "ok"

    net.delete()
    assert net.status == "deleted"
