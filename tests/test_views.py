import pytest
from rest_framework.test import APIClient

from peeringdb_server.models import (Network, Organization, User,
                                     UserOrgAffiliationRequest)

URL = "/affiliate-to-org"


@pytest.fixture
def client():
    user = User.objects.create(
        username="test",
        email="test@localhost",
    )
    user.set_password("test1234")
    user.save()
    client = APIClient()
    client.login(username="test", password="test1234")
    return client


@pytest.fixture
def org():
    org = Organization.objects.create(
        name="Test Org",
    )
    return org


@pytest.fixture
def network(org):
    net = Network.objects.create(name="test network", org=org, asn=123, status="ok")
    return net


@pytest.mark.django_db
def test_affiliate_to_org_multiple(client, org):
    """
    Issue 931, Limit the number of requests
    for affiliation to an ASN/org to 1
    """
    user = User.objects.get(username="test")

    data = {
        "org": org.id,
    }
    response = client.post(URL, data)
    assert response.status_code == 200
    assert UserOrgAffiliationRequest.objects.filter(user=user).count() == 1

    response = client.post(URL, data)
    assert response.status_code == 400
    assert "You already requested affiliation to this ASN/org" in str(response.content)
    assert UserOrgAffiliationRequest.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_affiliate_to_asn_multiple(client, network):
    """
    Issue 931, Limit the number of requests
    for affiliation to an ASN/org to 1
    """
    user = User.objects.get(username="test")

    # Create request w asn
    data = {"asn": network.asn}
    response = client.post(URL, data)
    assert response.status_code == 200
    assert UserOrgAffiliationRequest.objects.filter(user=user).count() == 1
    # Second request w asn
    data = {"asn": network.asn}
    response = client.post(URL, data)

    assert response.status_code == 400
    assert "You already requested affiliation to this ASN/org" in str(response.content)
    assert UserOrgAffiliationRequest.objects.filter(user=user).count() == 1
