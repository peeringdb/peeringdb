import pytest
import requests

from peeringdb_server.models import (
    Organization,
    OrganizationAPIKey,
    OrganizationAPIPermission,
    Network,
    User,
)
from django.core.exceptions import ValidationError
from django.urls import reverse
from peeringdb_server.permissions import get_key_from_request, get_permission_holder_from_request, check_permissions
from django.conf import settings

from django.test import RequestFactory, Client
from grainy.const import (
    PERM_READ,
    PERM_UPDATE,
    PERM_CREATE,
    PERM_DELETE,
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
    c = Client()
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
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", organization=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=15
    )
    assert api_key.grainy_permissions.count() == 1


@pytest.mark.django_db
def test_check_perms(org):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", organization=org
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
        name="test key", organization=org
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
        name="test key", organization=org
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
        name="test key", organization=org
    )
    for perm in [PERM_READ, PERM_UPDATE, PERM_CREATE, PERM_DELETE]:
        OrganizationAPIPermission.objects.create(
            org_api_key=api_key, namespace=namespace, permission=perm
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
def test_network_get_org_key(org, network, user, admin_client):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", organization=org
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    assert Network.objects.count() == 1
    url = reverse("net-detail", args=(network.id,))
    # url = reverse("net-list")
    client = Client()
    print("unauth")
    response = client.get(url, HTTP_X_API_KEY="abcd")
    print(response)
    print(response.content)
    print("")

    print("api key")
    response = client.get(url, HTTP_X_API_KEY=key)
    print(response)
    print(response.content)
    print("")

    print("logged in")
    client.login(username="user", password="user")
    response = client.get(url)
    print(response)
    print(response.content)
    print("")

    print("admin")
    response = admin_client.get(url)
    print(response)
    print(response.content)
    print("")

    assert 0


# @pytest.mark.django_db
# def test_network_put_org_key(org, network):
#     namespace = "peeringdb.organization.1.network"
#     api_key, key = OrganizationAPIKey.objects.create_key(
#         name="test key", organization=org
#     )
#     OrganizationAPIPermission.objects.create(
#         org_api_key=api_key, namespace=namespace, permission=PERM_READ
#     )

#     url = reverse("net-detail", args=(network.id,))
#     # Unauthenticated
#     data = {
#         "name": "changed name",
#         "asn": network.asn,
#         "org": network.org,
#     }
#     response = requests.put(url, data=data, headers={"X-API-KEY": "abcd"})
#     print(response.content)
