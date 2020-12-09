import pytest
import requests

from peeringdb_server.models import (
    Organization,
    OrganizationAPIKey,
    OrganizationAPIPermission,
    Network,
    User,
    UserAPIKey,
)
from django.core.exceptions import ValidationError
from django.urls import reverse
from peeringdb_server.permissions import get_key_from_request, get_permission_holder_from_request, check_permissions
from django.conf import settings

from django_grainy.models import UserPermission

from rest_framework.test import APIClient
from django.test import RequestFactory
from grainy.const import (
    PERM_READ,
    PERM_UPDATE,
    PERM_CREATE,
    PERM_DELETE,
    PERM_CRUD
)


@pytest.fixture
def admin_user():
    admin_user = User.objects.create_user(
        "admin", "admin@localhost", first_name="admin", last_name="admin"
    )
    admin_user.is_superuser = True
    admin_user.is_staff = True
    admin_user.save()
    admin_user.set_password("admin")
    admin_user.save()
    return admin_user


@pytest.fixture
def admin_client(admin_user):
    c = APIClient()
    c.login(username="admin", password="admin")
    return c


@pytest.fixture
def user():
    user = User.objects.create_user(
        "user", "user@localhost", first_name="user", last_name="user"
    )
    user.save()
    user.set_password("user")
    user.save()
    return user


@pytest.fixture
def org():
    org = Organization.objects.create(name="test org")
    return org


@pytest.fixture
def network(org):
    net = Network.objects.create(name="test network", org=org, asn=123, status="ok")
    return net


@pytest.mark.django_db
def test_create_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    assert api_key.revoked == False
    assert api_key.name == "test key"
    assert api_key.is_valid(key) == True

    # Test foreign key
    assert org.api_keys.first() == api_key


@pytest.mark.django_db
def test_create_user_api_key(user):
    api_key, key = UserAPIKey.objects.create_key(
        name="test key", user=user,
    )
    assert api_key.revoked == False
    assert api_key.name == "test key"
    assert api_key.is_valid(key) == True

    assert api_key.readonly == False
    # Test foreign key
    assert user.api_keys.first() == api_key


@pytest.mark.django_db
def test_revoke_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    api_key.revoked = True
    api_key.save()

    org.refresh_from_db()
    assert org.api_keys.get_usable_keys().count() == 0
    assert org.api_keys.count() == 1


@pytest.mark.django_db
def test_revoke_user_api_key(user):
    api_key, key = UserAPIKey.objects.create_key(
        name="test key", user=user
    )
    api_key.revoked = True
    api_key.save()

    user.refresh_from_db()
    assert user.api_keys.get_usable_keys().count() == 0
    assert user.api_keys.count() == 1


@pytest.mark.django_db
def test_validate_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    assert api_key.is_valid(key)
    assert api_key.is_valid("abcd") is False


@pytest.mark.django_db
def test_validate_user_api_key(user):
    api_key, key = UserAPIKey.objects.create_key(
        name="test key", user=user
    )
    assert api_key.is_valid(key)
    assert api_key.is_valid("abcd") is False


@pytest.mark.django_db
def test_set_perms(org):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_CRUD
    )
    assert api_key.grainy_permissions.count() == 1


@pytest.mark.django_db
def test_check_perms(org):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )

    assert check_permissions(api_key, namespace, "r")
    assert check_permissions(api_key, namespace, "u") is False


def test_get_key_from_request():
    key = "abcd"
    factory = RequestFactory()
    request = factory.get("/api/net/1")
    # Add api key header
    request.META.update({"HTTP_X_API_KEY": key})
    assert get_key_from_request(request) == key


@pytest.mark.django_db
def test_check_permissions_on_unauth_request(org):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Check permissions without any credentials
    assert hasattr(request, "user") is False
    assert request.META.get("HTTP_X_API_KEY") is None
    perm_obj = get_permission_holder_from_request(request)
    print(perm_obj)
    assert check_permissions(perm_obj, namespace, "r") is False


@pytest.mark.django_db
def test_check_permissions_on_org_key_request_readonly(org):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Add api key header
    request.META.update({"HTTP_X_API_KEY": key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_X_API_KEY"] == key
    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c") is False
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u") is False
    assert check_permissions(perm_obj, namespace, "d") is False


@pytest.mark.django_db
def test_check_permissions_on_org_key_request_crud(org):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_CRUD
    )

    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Add api key header
    request.META.update({"HTTP_X_API_KEY": key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_X_API_KEY"] == key

    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c")
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u")
    assert check_permissions(perm_obj, namespace, "d")


@pytest.mark.django_db
def test_check_permissions_on_user_key_request_crud(user):
    namespace = "peeringdb.organization.1.network"
    api_key, key = UserAPIKey.objects.create_key(
        name="test key", user=user
    )

    UserPermission.objects.create(
        namespace=namespace,
        permission=PERM_CRUD,
        user=user
    )

    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Add api key header
    request.META.update({"HTTP_X_API_KEY": key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_X_API_KEY"] == key
    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c")
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u")
    assert check_permissions(perm_obj, namespace, "d")


@pytest.mark.django_db
def test_check_permissions_on_user_key_request_readonly(user):
    namespace = "peeringdb.organization.1.network"
    api_key, key = UserAPIKey.objects.create_key(
        name="test key",
        user=user,
        readonly=True
    )
    assert api_key.readonly

    # Define permissions as CRUD
    UserPermission.objects.create(
        namespace=namespace,
        permission=PERM_CRUD,
        user=user
    )

    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Add api key header
    request.META.update({"HTTP_X_API_KEY": key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_X_API_KEY"] == key
    # Test permissions are readonly
    perm_obj = get_permission_holder_from_request(request)
    assert perm_obj == api_key
    assert check_permissions(perm_obj, namespace, "c") is False
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u") is False
    assert check_permissions(perm_obj, namespace, "d") is False


@pytest.mark.django_db
def test_network_get_w_org_key(org, network, user, admin_client):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    assert Network.objects.count() == 1
    url = reverse("net-detail", args=(network.id,))
    client = APIClient()

    response = client.get(url, HTTP_X_API_KEY=key)
    assert response.status_code == 200

    net_from_api = response.json()["data"][0]
    assert net_from_api["name"] == network.name
    assert net_from_api["asn"] == network.asn
    assert net_from_api["org_id"] == network.org.id


# @pytest.mark.django_db
# def test_network_put_w_org_key(org, network):
#     namespace = "peeringdb.organization.1.network"
#     api_key, key = OrganizationAPIKey.objects.create_key(
#         name="test key", org=org
#     )
#     OrganizationAPIPermission.objects.create(
#         org_api_key=api_key, namespace=namespace, permission=PERM_CRUD
#     )

#     url = reverse("net-detail", args=(network.id,))
#     print(network.org.id)
#     print(network.asn)
#     data = {
#         "name": "changed name",
#         "asn": network.asn,
#         "org_id": network.org.id
#     }
#     # Unauth
#     client = APIClient()
#     response = client.put(url, data, HTTP_X_API_KEY="abcd", format='json')
#     print(response.content)
#     assert response.status_code == 401

#     response = client.put(url, data, HTTP_X_API_KEY=key, format='json')
#     print(response.content)
#     assert 0
#     # net_from_api = response.json()["data"][0]
#     assert net_from_api["name"] == "changed name"
#     assert Network.objects.first().name == "changed name"

