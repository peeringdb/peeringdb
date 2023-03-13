import pytest

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    ParentStatusException,
)


@pytest.mark.django_db
def test_network_parent_status_validate():
    """
    Validate parent status of Network model instance
    """
    org = Organization.objects.create(name="Test org", status="deleted")
    with pytest.raises(ParentStatusException) as exc:
        Network.objects.create(name="Test", asn=63311, status="ok", org=org)


@pytest.mark.django_db
def test_networkfacility_parent_status_validate():
    """
    Validate parent status of NetworkFacility model instance
    """
    org = Organization.objects.create(name="Test org", status="ok")
    net = Network.objects.create(name="Test", asn=63311, status="ok", org=org)
    fac = Facility.objects.create(org=org, status="deleted", name="Facility Issue 901")
    with pytest.raises(ParentStatusException) as exc:
        NetworkFacility.objects.create(facility=fac, network=net, status="ok")


@pytest.mark.django_db
def test_networkcontact_parent_status_validate():
    """
    Validate parent status of NetworkContact model instance
    """
    org = Organization.objects.create(name="Test org", status="ok")
    net = Network.objects.create(name="Test", asn=63311, status="deleted", org=org)
    with pytest.raises(ParentStatusException) as exc:
        NetworkContact.objects.create(network=net, status="ok")


@pytest.mark.django_db
def test_networkixlan_parent_status_validate():
    """
    Validate parent status of NetworkIXLan model instance
    """
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="deleted", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="deleted", org=org)
    with pytest.raises(ParentStatusException) as exc:
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ix.ixlan,
            asn=network.asn,
            speed=20000,
            ipaddr4="195.69.147.250",
            ipaddr6=None,
            status="ok",
            is_rs_peer=False,
            operational=False,
        )


@pytest.mark.django_db
def test_internetexchange_parent_status_validate():
    """
    Validate parent status of InternetExchange model instance
    """
    org = Organization.objects.create(name="Test org", status="deleted")
    with pytest.raises(ParentStatusException) as exc:
        InternetExchange.objects.create(name="Test ix", status="ok", org=org)


@pytest.mark.django_db
def test_internetexchangefacility_parent_status_validate():
    """
    Validate parent status of InternetExchangeFacility model instance
    """
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="deleted", org=org)
    fac = Facility.objects.create(org=org, status="ok", name="Facility Issue 901")
    with pytest.raises(ParentStatusException) as exc:
        InternetExchangeFacility.objects.create(facility=fac, ix=ix, status="ok")


@pytest.mark.django_db
def test_facility_parent_status_validate():
    """
    Validate parent status of Facility model instance
    """
    org = Organization.objects.create(name="Test org", status="deleted")
    with pytest.raises(ParentStatusException) as exc:
        Facility.objects.create(org=org, status="ok", name="Facility Issue 901")
