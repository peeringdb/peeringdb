import pytest

from peeringdb_server.models import Facility, Network, Organization


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
