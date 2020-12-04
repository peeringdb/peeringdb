import pytest
from peeringdb_server.models import Organization, OrganizationAPIKey, OrganizationAPIPermission
import requests
from django.core.exceptions import ValidationError
from django_grainy.util import check_permissions, Permissions
from django.http.request import HttpRequest


@pytest.fixture
def org():
    org = Organization.objects.create(name="test org")
    return org


@pytest.mark.django_db
def test_create_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", organization=org
    )
    assert api_key.revoked == False
    assert api_key.name == "test key"
    assert api_key.is_valid(key) == True

    # Test foreign key
    assert org.api_keys.first() == api_key


@pytest.mark.django_db
def test_revoke_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", organization=org
    )
    api_key.revoked = True
    api_key.save()

    org.refresh_from_db()
    assert org.api_keys.get_usable_keys().count() == 0
    assert org.api_keys.count() == 1


@pytest.mark.django_db
def test_validate_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", organization=org
    )
    assert api_key.is_valid(key)
    assert api_key.is_valid("abcd") is False


@pytest.mark.django_db
def test_set_perms(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", organization=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key,
        namespace="peeringdb.organization.1.network",
        permission=15)
    assert api_key.grainy_permissions.count() == 1


@pytest.mark.django_db
def test_check_perms(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", organization=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key,
        namespace="peeringdb.organization.1.network",
        permission=5)

    assert check_permissions(api_key, "peeringdb.organization.1.network", "r")


@pytest.mark.django_db
def test_get_key_from_request():
    api_key = None
    request = HttpRequest()
    request.META.update({"X-API-KEY":"abcd"})
    print(request.headers)
    print(request.META)
    assert 0
