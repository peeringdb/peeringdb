import pytest
import reversion

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    Network,
    NetworkFacility,
    NetworkIXLan,
    Organization,
)


@pytest.fixture()
def entities():
    with reversion.create_revision():
        org = Organization.objects.create(name="Netflix", status="ok")
        network = Network.objects.create(
            name="Network",
            asn=123,
            org=org,
            info_prefixes4=42,
            info_prefixes6=42,
            website="http://netflix.com/",
            policy_general="Open",
            policy_url="https://www.netflix.com/openconnect/",
            allow_ixp_update=True,
            status="ok",
            irr_as_set="AS-NFLX",
            info_unicast=True,
            info_ipv6=True,
        )

        ix = InternetExchange.objects.create(
            name="Test Exchange One",
            org=org,
            status="ok",
            tech_email="ix1@localhost",
        )

        facility = Facility.objects.create(
            name="Facility",
            status="ok",
            city="City",
            clli="CLLI",
            state="MD",
            country="US",
            zipcode=1,
            org=org,
        )

        netixlan = NetworkIXLan.objects.create(
            network=network,
            ixlan=ix.ixlan,
            asn=network.asn,
            speed=1,
            ipaddr4="195.69.147.250",
            ipaddr6="2001:7f8:1::a500:2906:1",
            status="ok",
            is_rs_peer=True,
            operational=False,
        )

        netfac = NetworkFacility.objects.create(
            network=network,
            facility=facility,
            local_asn=123,
        )

    return {
        "facility": facility,
        "org": org,
        "ix": ix,
        "network": network,
        "netixlan": netixlan,
    }


@pytest.mark.django_db
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


@pytest.mark.django_db
def test_strip_fields():
    """
    test strip string fields in save method
    """
    org = Organization.objects.create(name="  Test   ", status="ok")
    assert org.name == "Test"
    fac = Facility.objects.create(
        name="facility 123       ",
        org=org,
        zipcode="  1234  ",
        city=" las vegas        ",
    )
    assert fac.name == "facility 123"
    assert fac.zipcode == "1234"
    assert fac.city == "las vegas"


@pytest.mark.django_db
def test_strip_fields_model_clean_validation():
    """
    test strip string fields in model clean validation
    """
    org = Organization.objects.create(name="  Test   ", status="ok")
    assert org.name == "Test"
    fac_list = []
    for i in range(1, 6):
        fac = Facility(id=i, org=org, city=f"city-{i}", name=f"   fac-{i}   ")
        fac.full_clean()
        fac_list.append(fac)
    Facility.objects.bulk_create(fac_list)

    for fac in Facility.objects.all():
        assert len(fac.name) == len(fac.name.strip())
        assert len(fac.city) == len(fac.city.strip())


@pytest.mark.django_db
def test_net_side_ix_side(entities):
    fac = Facility.objects.first()
    netixlan = NetworkIXLan.objects.first()

    assert netixlan.net_side == None
    assert netixlan.ix_side == None

    netixlan.net_side = fac
    netixlan.ix_side = fac

    with reversion.create_revision():
        netixlan.save()

    assert netixlan.net_side
    assert netixlan.ix_side


@pytest.mark.django_db
def test_netixlan_save_will_sync_asn(entities):
    netixlan = NetworkIXLan.objects.first()
    assert netixlan.asn == netixlan.network.asn

    netixlan.asn = 2
    with reversion.create_revision():
        netixlan.save()

    assert netixlan.asn == netixlan.network.asn


@pytest.mark.django_db
def test_netfac_save_will_sync_asn(entities):
    netfac = NetworkFacility.objects.first()
    assert netfac.local_asn == netfac.network.asn

    netfac.local_asn = 2

    with reversion.create_revision():
        netfac.save()

    assert netfac.local_asn == netfac.network.asn
