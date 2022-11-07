import base64
import re

import pytest
from allauth.account.models import EmailAddress
from django.http import response
from django.test import Client
from django_grainy.models import Group
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    Network,
    Organization,
    User,
    UserAPIKey,
    UserOrgAffiliationRequest,
)
from tests.util import reset_group_ids

URL = "/affiliate-to-org"


@pytest.fixture
def client():
    user = User.objects.create(username="test", email="test@localhost")
    user.set_password("test1234")
    user.save()
    client = APIClient()
    client.login(username="test", password="test1234")
    return client


@pytest.fixture
def org():
    org = Organization.objects.create(name="Test Org")
    return org


@pytest.fixture
def network(org):
    net = Network.objects.create(name="test network", org=org, asn=123, status="ok")
    return net


def assert_passing_affiliation_request(data, client):
    response = client.post(URL, data)
    assert response.status_code == 200
    assert UserOrgAffiliationRequest.objects.count() == 1


def assert_failing_affiliation_request(data, client):
    response = client.post(URL, data)
    assert response.status_code == 400
    assert "You already requested affiliation to this ASN/org" in str(response.content)
    assert UserOrgAffiliationRequest.objects.count() == 1


def assert_failing_affiliation_request_because_of_deletion(data, client):
    response = client.post(URL, data)
    assert response.status_code == 400
    assert "Unable to affiliate as this organization has been deleted" in str(
        response.content
    )


"""
The following tests are for issue 931:
Limit the number of requests
for affiliation to an ASN/org to 1
"""


@pytest.mark.django_db
def test_affiliate_to_org_multiple(client, org):
    assert_passing_affiliation_request({"org": org.id}, client)
    assert_failing_affiliation_request({"org": org.id}, client)


@pytest.mark.django_db
def test_affiliate_to_asn_multiple(client, network):
    assert_passing_affiliation_request({"asn": 123}, client)
    assert_failing_affiliation_request({"asn": 123}, client)


@pytest.mark.django_db
def test_affiliate_to_org_then_asn(client, network, org):
    assert_passing_affiliation_request({"org": org.id}, client)
    assert_failing_affiliation_request({"asn": 123}, client)


@pytest.mark.django_db
def test_affiliate_to_asn_then_org(client, network, org):
    assert_passing_affiliation_request({"org": org.id}, client)
    assert_failing_affiliation_request({"asn": 123}, client)


@pytest.mark.django_db
def test_affiliate_to_org_id_takes_precedence_over_asn(client, org):
    assert_passing_affiliation_request({"org": org.id, "asn": 2020}, client)
    assert_failing_affiliation_request({"org": org.id, "asn": 2111}, client)


@pytest.mark.django_db
def test_affiliate_to_asn_takes_precendence_over_org_name(client, network, org):
    assert_passing_affiliation_request({"org": "test name", "asn": 123}, client)
    assert_failing_affiliation_request({"org": "different", "asn": 123}, client)


@pytest.mark.django_db
def test_affiliate_to_deleted_org(client, org):
    org.delete()
    assert_failing_affiliation_request_because_of_deletion({"org": org.id}, client)


@pytest.mark.django_db
def test_affiliate_to_deleted_org_via_network(client, network):
    network.org.delete()
    assert_failing_affiliation_request_because_of_deletion({"asn": 123}, client)


@pytest.mark.django_db
def test_affiliate_to_nonexisting_org_multiple(client):
    """
    Multiple affiliations to nonexisting orgs should still get
    caught if the provided org name is repetitive
    """
    data = {"org": "Nonexistent org"}
    assert_passing_affiliation_request(data, client)
    assert_failing_affiliation_request(data, client)

    # If we change the org name we can affiliate to that one as well
    other_data = {"org": "Second nonexistent org"}
    response = client.post(URL, other_data)
    assert response.status_code == 200
    assert UserOrgAffiliationRequest.objects.count() == 2


@pytest.mark.django_db
def test_adv_search_init():
    reset_group_ids()
    client = Client()
    response = client.get("/advanced_search")
    assert response.status_code == 200

    user = User.objects.create(username="test", email="test@localhost")
    user.set_password("test1234")
    user.save()

    client.login(username="test", password="test1234")

    response = client.get("/advanced_search")
    assert response.status_code == 200


@pytest.mark.django_db
def test_signup_page():
    client = Client()

    # test page load
    response = client.get("/register")
    content = response.content.decode("utf-8")
    assert response.status_code == 200

    # test fallback captcha load
    m = re.search(r"\/captcha\/image\/([^\/]+)\/", content)
    assert m
    response = client.get(m[0])
    assert response.status_code == 200


@pytest.mark.django_db
def test_user_api_key_generation():

    user = User.objects.create(username="test", email="test@localhost")
    user.set_password("test1234")
    user.save()

    client = Client()
    client.login(username="test", password="test1234")

    response = client.post("/user_keys/add")

    assert response.status_code == 400
    assert "This field is required." in str(response.content.decode("utf-8"))

    response = client.post("/user_keys/add", {"name": "test key"})

    assert response.status_code == 200


@pytest.mark.django_db
def test_close_account():
    reset_group_ids()
    user = User.objects.create_user(
        username="test",
        email="test@localhost",
        password="test1234",
        first_name="Test",
        last_name="User",
        status="ok",
    )

    group = Group(name="test group")
    group.save()

    # add user to group
    group.user_set.add(user)

    user.set_verified()

    user.status = "ok"
    user.save()

    assert user.status == "ok"

    client = Client()
    client.login(username="test", password="test1234")

    response = client.post("/user_keys/add", {"name": "test key"})
    response = client.post("/profile/close", {"password": "test1234"})

    user = User.objects.get(username=f"closed-account-{user.id}")
    assert user.is_active is False
    assert client.login(username="test", password="test1234") is False
    assert UserAPIKey.objects.filter(user=user).count() == 0
    assert EmailAddress.objects.filter(user=user).count() == 0
    assert user.groups.count() == 0
    assert user.email is None
    assert user.first_name == ""
    assert user.last_name == ""


@pytest.mark.django_db
def test_close_account_pending_user():
    reset_group_ids()
    user = User.objects.create_user(
        username="test",
        email="test@localhost",
        password="test1234",
        first_name="Test",
        last_name="User",
    )

    group = Group(name="test group")
    group.save()

    # add user to group
    group.user_set.add(user)

    client = Client()
    client.login(username="test", password="test1234")

    response = client.post("/user_keys/add", {"name": "test key"})
    response = client.post("/profile/close", {"password": "test1234"})

    assert not User.objects.filter(username="test").exists()


@pytest.mark.django_db
def test_bogus_basic_auth():
    auth_string = "Basic YmFkOmJhZA=="
    auth_headers = {"HTTP_AUTHORIZATION": auth_string}
    client = Client()
    response = client.get("/", **auth_headers)
    assert response.status_code == 401


@pytest.mark.django_db
def test_pending_view():
    client = Client()

    org = Organization.objects.create(name="test org")
    org.save()

    ix = InternetExchange.objects.create(name="test ix", org_id=org.id)
    ix.save()

    fac = Facility.objects.create(name="test fac", org_id=org.id)
    fac.save()

    # set object status to pending

    org.status = "pending"
    org.save()

    ix.status = "pending"
    ix.save()

    fac.status = "pending"
    fac.save()

    # assert that pending objects returns 404

    response = client.get(f"/org/{org.id}")
    assert response.status_code == 404

    response = client.get(f"/ix/{ix.id}")
    assert response.status_code == 404

    response = client.get(f"/fac/{fac.id}")
    assert response.status_code == 404
