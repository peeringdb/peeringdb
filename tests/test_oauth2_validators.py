import pytest
from django.contrib.auth.models import Group
from oauthlib.common import Request

from mainsite.oauth2 import validators
from peeringdb_server import models

from .util import reset_group_ids


@pytest.fixture
def organization():
    reset_group_ids()
    return models.Organization.objects.create(name="test org", status="ok")


@pytest.fixture(autouse=True)
def network(organization):
    return models.Network.objects.create(
        name="test network", org=organization, asn=123, status="ok"
    )


@pytest.fixture
def verified_user(organization):
    user_group = Group.objects.get(name="user")

    user = models.User.objects.create_user(
        "testuser", "testuser@example.net", first_name="Test", last_name="User"
    )

    # This makes the user verified
    user_group.user_set.add(user)

    organization.usergroup.user_set.add(user)
    return user


@pytest.fixture
def oauth_request(verified_user):
    request = Request("/")
    request.user = verified_user
    request.scopes = []
    request.client = None
    request.decoded_body = [("code", "testcode")]
    return request


@pytest.mark.django_db
def test_oidc_validator_produces_profile_claims(oauth_request):
    oauth_request.scopes = ["openid", "profile"]
    validator = validators.OIDCValidator()
    claims = validator.get_oidc_claims(None, None, oauth_request)

    assert claims == {
        "sub": f"{oauth_request.user.id}",
        "id": oauth_request.user.id,
        "family_name": "User",
        "given_name": "Test",
        "name": "Test User",
        "verified_user": True,
        "email": None,
        "email_verified": None,
        "networks": None,
        "amr": [],
    }


@pytest.mark.django_db
def test_oidc_validator_produces_email_claims(oauth_request):
    oauth_request.scopes = ["openid", "email"]
    validator = validators.OIDCValidator()
    claims = validator.get_oidc_claims(None, None, oauth_request)

    assert claims == {
        "sub": f"{oauth_request.user.id}",
        "id": None,
        "family_name": None,
        "given_name": None,
        "verified_user": None,
        "name": None,
        "email": "testuser@example.net",
        "email_verified": False,
        "networks": None,
        "amr": [],
    }


@pytest.mark.django_db
def test_oidc_validator_produces_network_claims(oauth_request, network):
    oauth_request.scopes = ["openid", "networks"]
    validator = validators.OIDCValidator()
    claims = validator.get_oidc_claims(None, None, oauth_request)

    assert claims == {
        "sub": f"{oauth_request.user.id}",
        "id": None,
        "family_name": None,
        "given_name": None,
        "verified_user": None,
        "name": None,
        "email": None,
        "email_verified": None,
        "networks": [
            {
                "id": network.id,
                "asn": 123,
                "name": "test network",
                "perms": 1,
            },
        ],
        "amr": [],
    }
