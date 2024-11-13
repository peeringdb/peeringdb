import re

import pytest
from allauth.account.models import EmailAddress
from django.test import Client
from django.urls import reverse
from django_grainy.models import Group
from rest_framework import status
from rest_framework.test import APIClient

from peeringdb_server import settings as pdb_settings
from peeringdb_server.models import (
    EnvironmentSetting,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    Network,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    User,
    UserAPIKey,
    UserOrgAffiliationRequest,
)
from peeringdb_server.permissions import check_permissions_from_request
from peeringdb_server.views import BASE_ENV
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


def assert_failing_affiliation_request_because_of_deletion(data, client, content):
    response = client.post(URL, data)
    assert response.status_code == 400
    assert content in str(response.content)


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
    assert_failing_affiliation_request_because_of_deletion(
        {"org": org.id},
        client,
        content="Unable to affiliate as this organization has been deleted",
    )


@pytest.mark.django_db
def test_affiliate_to_deleted_org_via_network(client, network):
    network.org.delete()
    assert_failing_affiliation_request_because_of_deletion(
        {"asn": 123},
        client,
        content="Unable to affiliate as this network has been deleted. Please reach out to PeeringDB support if you wish to resolve this.",
    )


@pytest.mark.django_db
def test_affiliate_to_deleted_network(client, network):
    network.delete()
    assert_failing_affiliation_request_because_of_deletion(
        {"asn": 123},
        client,
        content="Unable to affiliate as this network has been deleted. Please reach out to PeeringDB support if you wish to resolve this.",
    )


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


@pytest.mark.django_db
def test_healthcheck():
    client = Client()

    response = client.get("/healthcheck")
    assert response.status_code == 200


@pytest.mark.django_db
def test_post_ix_side_net_side(network, org):
    client = APIClient()

    # Setup data
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    netixlan = NetworkIXLan.objects.create(
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

    fac = Facility.objects.create(name="Test Facility", status="ok", org=org)

    # Check that no facilities are linked initially
    assert not ix.ixfac_set.filter(status="ok").exists()
    assert not network.netfac_set.filter(status="ok").exists()

    # Create InternetExchangeFacility and NetworkFacility
    ix_facility = InternetExchangeFacility.objects.create(
        facility=fac, ix=ix, status="ok"
    )
    net_facility = NetworkFacility.objects.create(
        facility=fac, network=network, status="ok"
    )

    assert ix_facility.status == "ok"
    assert net_facility.status == "ok"

    # Helper function for posting and checking response status
    def post_and_check(url, fac_id, expected_status):
        response = client.post(
            url,
            {"fac_id": fac_id},
            format="json",
        )
        assert response.status_code == expected_status

    # Helper function to determine expected status based on permissions for network/ix
    def expected_status(obj, permission_code):
        request = client.request().wsgi_request
        if not check_permissions_from_request(request, obj, permission_code):
            return status.HTTP_403_FORBIDDEN
        return status.HTTP_200_OK

    # Test set ix_side with permission
    ix_side_url = f"/api/netixlan/{netixlan.id}/set-ix-side"
    post_and_check(
        ix_side_url, fac.id, expected_status(ix, "c")
    )  # Check permission on IX (InternetExchange)

    # Test set net_side with permission
    net_side_url = f"/api/netixlan/{netixlan.id}/set-net-side"
    post_and_check(
        net_side_url, fac.id, expected_status(network, "c")
    )  # Check permission on Network

    # Simulate permission denied by removing access
    client.force_authenticate(user=None)  # Simulate unauthorized user

    # Test setting ix_side with permission denied
    post_and_check(ix_side_url, fac.id, status.HTTP_403_FORBIDDEN)

    # Test setting net_side with permission denied
    post_and_check(net_side_url, fac.id, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
def test_view_profile_two_factor_email_not_confirmed(client):
    assert not EmailAddress.objects.filter(
        email="test@localhost", verified=True
    ).exists()

    payload = {
        "two_factor_setup_view-current_step": "welcome",
    }

    response = client.post(reverse("two_factor:setup"), data=payload)

    assert response.status_code == 403
    assert response.json() == {
        "error": "Your email must be confirmed before enabling two-factor authentication."
    }


@pytest.mark.django_db
def test_view_profile_two_factor_email_confirmed(client):
    user = User.objects.get(username="test")
    EmailAddress.objects.create(
        user=user, email="test@localhost", verified=True, primary=True
    )

    assert EmailAddress.objects.filter(email="test@localhost", verified=True).exists()

    payload = {
        "two_factor_setup_view-current_step": "welcome",
    }

    response = client.post(reverse("two_factor:setup"), data=payload)

    assert response.status_code == 200


@pytest.mark.django_db
def test_view_tutorial_banner(client, settings):
    """
    Tests that the tutorial banner is shown when TUTORIAL_MODE is True
    """

    try:
        settings.TUTORIAL_MODE = True
        pdb_settings.TUTORIAL_MODE = True
        BASE_ENV["TUTORIAL_MODE"] = True
        response = client.get("/")
        assert response.status_code == 200
        assert "TUTORIAL MODE" in response.content.decode("utf-8")
    finally:
        BASE_ENV["TUTORIAL_MODE"] = False
        settings.TUTORIAL_MODE = False
        pdb_settings.TUTORIAL_MODE = False


@pytest.mark.django_db
def test_view_tutorial_banner_text_override(client, settings):
    """
    Test that the tutorial banner message can be overridden

    It is overwritten by setting the EnvironmentSetting for TUTORIAL_MODE_MESSAGE
    """

    try:
        BASE_ENV["TUTORIAL_MODE"] = True
        settings.TUTORIAL_MODE = True
        pdb_settings.TUTORIAL_MODE = True

        EnvironmentSetting.objects.create(
            setting="TUTORIAL_MODE_MESSAGE",
            value_str="This is a test message",
        )

        response = client.get("/")

        assert response.status_code == 200

        assert "TUTORIAL MODE" in response.content.decode("utf-8")
        assert "This is a test message" in response.content.decode("utf-8")
    finally:
        BASE_ENV["TUTORIAL_MODE"] = False
        settings.TUTORIAL_MODE = False
        pdb_settings.TUTORIAL_MODE = False
