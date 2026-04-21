import pytest
import reversion
from django.core.exceptions import ValidationError

from peeringdb_server.models import (
    Carrier,
    CarrierFacility,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    ProtectedAction,
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

        NetworkFacility.objects.create(
            network=network,
            facility=facility,
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
        fac = Facility(
            id=i, org=org, city=f"city-{i}", name=f"   fac-{i}   ", status="ok"
        )
        fac.full_clean()
        fac_list.append(fac)
    Facility.objects.bulk_create(fac_list)

    for fac in Facility.objects.all():
        assert len(fac.name) == len(fac.name.strip())
        assert len(fac.city) == len(fac.city.strip())


@pytest.mark.django_db
def test_network_irr_as_set_validation():
    """
    Test that Network.clean() validates and normalizes the irr_as_set field.

    The validator is tested in isolation in test_validators.py; here we verify
    the model wires it up correctly: normalization is written back to the field,
    and errors are raised under the "irr_as_set" key.
    """
    org = Organization.objects.create(name="Test Org", status="ok")

    # valid value gets normalized (lowercase -> uppercase, comma -> space)
    net = Network(
        asn=1,
        name="Test Network",
        org=org,
        status="ok",
        irr_as_set="ripe::as-foo, radb::as-bar",
    )
    net.clean()
    assert net.irr_as_set == "RIPE::AS-FOO RADB::AS-BAR"

    # invalid value raises ValidationError
    net2 = Network(
        asn=2,
        name="Test Network 2",
        org=org,
        status="ok",
        irr_as_set="AS-Resound Networks,LLC",
    )
    with pytest.raises(ValidationError) as exc:
        net2.clean()
    assert "irr_as_set" in exc.value.message_dict

    # empty value
    net3 = Network(asn=3, name="Test Network 3", org=org, status="ok", irr_as_set="")
    net3.clean()


@pytest.mark.django_db
def test_net_side_ix_side(entities):
    fac = Facility.objects.first()
    netixlan = NetworkIXLan.objects.first()

    assert netixlan.net_side is None
    assert netixlan.ix_side is None

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
def test_facility_delete_cascades_to_carrierfac():
    """
    When a Facility is soft-deleted, all related CarrierFacility records
    must also be soft-deleted (status="deleted").
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Test Org Cascade", status="ok")
        carrier = Carrier.objects.create(name="Test Carrier", status="ok", org=org)
        fac = Facility.objects.create(
            name="Test Facility Cascade",
            status="ok",
            org=org,
            city="City",
            country="US",
        )
        carrierfac = CarrierFacility.objects.create(
            carrier=carrier,
            facility=fac,
            status="ok",
        )

    assert carrierfac.status == "ok"

    with reversion.create_revision():
        fac.delete()

    fac.refresh_from_db()
    carrierfac.refresh_from_db()

    assert fac.status == "deleted"
    assert (
        carrierfac.status == "deleted"
    ), "CarrierFacility should be soft-deleted when its parent Facility is deleted."


@pytest.mark.django_db
def test_network_delete_cascades():
    """
    When a Network is soft-deleted, all related poc, netfac and netixlan
    records must also be soft-deleted.
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Test Org Net Cascade", status="ok")
        ix = InternetExchange.objects.create(
            name="Test IX Net Cascade", org=org, status="ok", tech_email="ix@test.com"
        )
        fac = Facility.objects.create(
            name="Test Fac Net Cascade", org=org, status="ok", city="City", country="US"
        )
        net = Network.objects.create(
            name="Test Net Cascade", asn=64500, org=org, status="ok"
        )
        poc = NetworkContact.objects.create(network=net, status="ok", role="Technical")
        netfac = NetworkFacility.objects.create(network=net, facility=fac, status="ok")
        netixlan = NetworkIXLan.objects.create(
            network=net, ixlan=ix.ixlan, asn=net.asn, speed=1, status="ok"
        )

    with reversion.create_revision():
        net.delete()

    poc.refresh_from_db()
    netfac.refresh_from_db()
    netixlan.refresh_from_db()

    assert poc.status == "deleted"
    assert netfac.status == "deleted"
    assert netixlan.status == "deleted"


@pytest.mark.django_db
def test_ix_delete_cascades():
    """
    When an InternetExchange is soft-deleted, all related ixfac and ixlan
    records must also be soft-deleted.
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Test Org IX Cascade", status="ok")
        fac = Facility.objects.create(
            name="Test Fac IX Cascade", org=org, status="ok", city="City", country="US"
        )
        ix = InternetExchange.objects.create(
            name="Test IX Cascade", org=org, status="ok", tech_email="ix@test.com"
        )
        ixfac = InternetExchangeFacility.objects.create(
            ix=ix, facility=fac, status="ok"
        )

    ixlan = ix.ixlan

    with reversion.create_revision():
        ix.delete(force=True)

    ixfac.refresh_from_db()
    ixlan.refresh_from_db()

    assert ixfac.status == "deleted"
    assert ixlan.status == "deleted"


@pytest.mark.django_db
def test_ixlan_delete_cascades():
    """
    When an IXLan is soft-deleted, all related ixpfx and netixlan
    records must also be soft-deleted.
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Test Org IXLan Cascade", status="ok")
        ix = InternetExchange.objects.create(
            name="Test IX IXLan Cascade",
            org=org,
            status="ok",
            tech_email="ix@test.com",
        )
        net = Network.objects.create(
            name="Test Net IXLan Cascade", asn=64501, org=org, status="ok"
        )
        ixlan = ix.ixlan
        ixpfx = IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="192.0.2.0/24", protocol="IPv4"
        )
        netixlan = NetworkIXLan.objects.create(
            network=net, ixlan=ixlan, asn=net.asn, speed=1, status="ok"
        )

    with reversion.create_revision():
        ixlan.delete()

    ixpfx.refresh_from_db()
    netixlan.refresh_from_db()

    assert netixlan.status == "deleted"
    assert ixpfx.status == "deleted"


@pytest.mark.django_db
def test_ixpfx_delete_protected_while_netixlan_active():
    """
    Standalone ixpfx.delete() must raise ProtectedAction when there are
    active netixlans with IPs inside the prefix.

    The ixlan_deletion context is NOT set here, so IXLanPrefix.deletable
    runs its full check and blocks the deletion — confirming the context
    manager does not disable protection globally.
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Test Org IXPfx Protected", status="ok")
        ix = InternetExchange.objects.create(
            name="Test IX IXPfx Protected",
            org=org,
            status="ok",
            tech_email="ixpfx@test.com",
        )
        net = Network.objects.create(
            name="Test Net IXPfx Protected", asn=64502, org=org, status="ok"
        )
        ixlan = ix.ixlan
        ixpfx = IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="192.0.2.0/24", protocol="IPv4"
        )
        NetworkIXLan.objects.create(
            network=net,
            ixlan=ixlan,
            asn=net.asn,
            speed=1,
            status="ok",
            ipaddr4="192.0.2.1",
        )

    with pytest.raises(ProtectedAction):
        ixpfx.delete()


@pytest.mark.django_db
def test_carrier_delete_cascades():
    """
    When a Carrier is soft-deleted, all related carrierfac records
    must also be soft-deleted.
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Test Org Carrier Cascade", status="ok")
        carrier = Carrier.objects.create(
            name="Test Carrier Cascade", status="ok", org=org
        )
        fac = Facility.objects.create(
            name="Test Fac Carrier Cascade",
            org=org,
            status="ok",
            city="City",
            country="US",
        )
        carrierfac = CarrierFacility.objects.create(
            carrier=carrier, facility=fac, status="ok"
        )

    with reversion.create_revision():
        carrier.delete()

    carrierfac.refresh_from_db()

    assert carrierfac.status == "deleted"


@pytest.mark.django_db
def test_org_delete_cascades():
    """
    When an Organization is soft-deleted, all related fac, net, ix and carrier
    records must also be soft-deleted.

    Previously, carrier_set was missing from OrganizationBase.HandleRef.delete_cascade
    in django-peeringdb, causing carrier records to remain status="ok" after the
    parent org was deleted. This resulted in "dangling relationship" warnings
    during peeringdb-py syncs (issue #91).
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Test Org Delete Cascade", status="ok")
        fac = Facility.objects.create(
            name="Test Fac Org Cascade", org=org, status="ok", city="City", country="US"
        )
        net = Network.objects.create(
            name="Test Net Org Cascade", asn=64502, org=org, status="ok"
        )
        ix = InternetExchange.objects.create(
            name="Test IX Org Cascade",
            org=org,
            status="ok",
            tech_email="ix@test.com",
        )
        carrier = Carrier.objects.create(
            name="Test Carrier Org Cascade", status="ok", org=org
        )

    with reversion.create_revision():
        org.delete(force=True)

    fac.refresh_from_db()
    net.refresh_from_db()
    ix.refresh_from_db()
    carrier.refresh_from_db()

    assert fac.status == "deleted"
    assert net.status == "deleted"
    assert ix.status == "deleted"
    assert (
        carrier.status == "deleted"
    ), "Carrier should be soft-deleted when its parent Organization is deleted."


@pytest.mark.django_db
def test_netfac_save_will_sync_asn(entities):
    netfac = NetworkFacility.objects.first()
    assert netfac.local_asn == netfac.network.asn

    original_asn = netfac.network.asn
    new_asn = original_asn + 2

    with reversion.create_revision():
        netfac.network.asn = new_asn
        netfac.network.save()

    netfac.refresh_from_db()

    assert netfac.local_asn == new_asn
    assert netfac.local_asn == netfac.network.asn
