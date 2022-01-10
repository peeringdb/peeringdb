import re

from django.http import response

import pytest
from django.test import Client
from rest_framework.test import APIClient

from tests.util import reset_group_ids

from peeringdb_server.models import (
    Network,
    Organization,
    User,
    UserOrgAffiliationRequest,
)
from tests.util import reset_group_ids

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


def assert_passing_affiliation_request(data, client):
    response = client.post(URL, data)
    assert response.status_code == 200
    assert UserOrgAffiliationRequest.objects.count() == 1


def assert_failing_affiliation_request(data, client):
    response = client.post(URL, data)
    assert response.status_code == 400
    assert "You already requested affiliation to this ASN/org" in str(response.content)
    assert UserOrgAffiliationRequest.objects.count() == 1


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
def test_affiliate_to_nonexisting_org_multiple(client):
    """
    Multiple affiliations to nonexisting orgs should still get
    caught if the provided org name is repetitive
    """
    data = {
        "org": "Nonexistent org",
    }
    assert_passing_affiliation_request(data, client)
    assert_failing_affiliation_request(data, client)

    # If we change the org name we can affiliate to that one as well
    other_data = {
        "org": "Second nonexistent org",
    }
    response = client.post(URL, other_data)
    assert response.status_code == 200
    assert UserOrgAffiliationRequest.objects.count() == 2


@pytest.mark.django_db
def test_adv_search_init():
    reset_group_ids()
    client = Client()
    response = client.get("/advanced_search")
    assert response.status_code == 200

    user = User.objects.create(
        username="test",
        email="test@localhost",
    )
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

    user = User.objects.create(
        username="test",
        email="test@localhost",
    )
    user.set_password("test1234")
    user.save()

    client = Client()
    client.login(username="test", password="test1234")

    response = client.post("/user_keys/add")

    assert response.status_code == 400
    assert "This field is required." in str(response.content.decode("utf-8"))

    response = client.post("/user_keys/add", {"name": "test key"})

    assert response.status_code == 200
