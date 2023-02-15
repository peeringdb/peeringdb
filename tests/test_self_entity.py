import pytest
from django.conf import settings
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    Network,
    Organization,
    User,
)


@pytest.fixture
def client():
    """
    Create user and login that
    """
    user = User.objects.create(username="test", email="test@localhost")
    user.set_password("test1234")
    user.save()
    client = APIClient()
    client.login(username="test", password="test1234")
    return client


@pytest.mark.django_db
def test_view_set_user_org(client):
    """
    Test case for verifying user's primary_org
    """
    data = {"organization": 2}
    response = client.post("/set-organization/", data)

    user = User.objects.get(username="test")

    assert user.primary_org == 2
    assert response.status_code == 200


@pytest.mark.django_db
def test_view_self_entity(client):
    """
    Test case for testing self identifier API
    """
    user = User.objects.get(username="test")
    org = Organization.objects.create(name="Test org", status="ok")
    org.usergroup.user_set.add(user)
    net = Network.objects.create(name="Test net", asn=63311, status="ok", org=org)
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    fac = Facility.objects.create(name="Test fac", status="ok", org=org)

    settings.DEFAULT_SELF_ORG = org.id
    settings.DEFAULT_SELF_IX = ix.id
    settings.DEFAULT_SELF_NET = net.id
    settings.DEFAULT_SELF_FAC = fac.id

    response = client.get("/org/self")

    assert response.status_code == 302
    assert response.url == f"/org/{org.id}"

    response = client.get("/net/self")

    assert response.status_code == 302
    assert response.url == f"/net/{net.id}"

    response = client.get("/ix/self")

    assert response.status_code == 302
    assert response.url == f"/ix/{ix.id}"

    response = client.get("/fac/self")

    assert response.status_code == 302
    assert response.url == f"/fac/{fac.id}"
