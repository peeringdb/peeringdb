import json

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

OAUTH2_PROVIDER = {
    "OIDC_ENABLED": settings.OIDC_ENABLED,
    "OIDC_RSA_PRIVATE_KEY": settings.OIDC_RSA_PRIVATE_KEY,
    "PKCE_REQUIRED": settings.PKCE_REQUIRED,
    "OAUTH2_VALIDATOR_CLASS": "mainsite.oauth2.validators.OIDCValidator",
    "SCOPES": {
        "openid": "OpenID Connect scope",
        "profile": "user profile",
        "email": "email address",
        "networks": "list of user networks and permissions",
        "amr": "authentication method reference",
    },
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https"],
    "REQUEST_APPROVAL_PROMPT": "auto",
}


@pytest.fixture
def current_oauth_metadata(client: Client):
    """Fixture to get the current OAuth metadata from the view."""
    response = client.get(reverse("oauth2_provider_metadata"))
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def test_data():
    """Fixture to load the test data from the file."""
    with open("tests/data/oauth/metadata.json") as f:
        return json.load(f)


@pytest.mark.django_db
def test_oauth_metadata_view(current_oauth_metadata, test_data):
    """Test against expected metadata from a file."""

    # Check oidc_claims_supported using sets to fix order issue
    oidc_claims = current_oauth_metadata.get("oidc_claims_supported")
    data_oauth_claims = test_data.get("oidc_claims_supported")

    # uncomment following line and use -s on pytest command to see and verify the output
    # print(f'oidc_claims: {set(oidc_claims)} data_oauth_claims: {set(data_oauth_claims)}')

    assert set(oidc_claims) == set(data_oauth_claims)

    # Check each key individually
    for key, expected_value in test_data.items():
        if key == "oidc_claims_supported":
            continue  # Skip the claims
        actual_value = current_oauth_metadata.get(key)

        # uncomment following line and use -s on pytest command to see and verify the output
        # print(f'actual_value: {actual_value} expected_value: {expected_value}')

        assert actual_value == expected_value
