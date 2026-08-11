import pytest
from django.test import Client, RequestFactory
from django.urls import reverse
from django_grainy.models import UserPermission
from grainy.const import PERM_CRUD, PERM_READ
from rest_framework.test import APIClient

from peeringdb_server.api_key_views import (
    resolve_user_key_permission_id,
    save_user_key_permissions,
)
from peeringdb_server.models import (
    Carrier,
    Facility,
    Group,
    InternetExchange,
    Network,
    Organization,
    OrganizationAPIKey,
    OrganizationAPIPermission,
    User,
    UserAPIKey,
    UserAPIPermission,
)
from peeringdb_server.permissions import (
    check_permissions,
    get_key_from_request,
    get_permission_holder_from_request,
)

from .util import reset_group_ids


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
def groups():
    Group.objects.create(name="guest")
    Group.objects.create(name="user")
    reset_group_ids()


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


@pytest.fixture
def carrier(org):
    carrier = Carrier.objects.create(name="test carrier", org=org, status="ok")
    return carrier


@pytest.fixture
def facility(org):
    fac = Facility.objects.create(
        name="test facility", org=org, status="ok", city="Test City", country="US"
    )
    return fac


@pytest.fixture
def exchange(org):
    ix = InternetExchange.objects.create(
        name="test exchange", org=org, status="ok", city="Test City", country="US"
    )
    return ix


@pytest.mark.django_db
def test_create_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    assert api_key.revoked is False
    assert api_key.name == "test key"
    assert api_key.is_valid(key) is True

    # Test foreign key
    assert org.api_keys.first() == api_key


@pytest.mark.django_db
def test_create_user_api_key(user):
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)
    assert api_key.revoked is False
    assert api_key.name == "test key"
    assert api_key.is_valid(key) is True

    assert api_key.readonly is False
    # Test foreign key
    assert user.api_keys.first() == api_key


@pytest.mark.django_db
def test_revoke_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    api_key.revoked = True
    api_key.save()

    org.refresh_from_db()
    assert org.api_keys.get_usable_keys().count() == 0
    assert org.api_keys.count() == 1


@pytest.mark.django_db
def test_revoke_user_api_key(user):
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)
    api_key.revoked = True
    api_key.save()

    user.refresh_from_db()
    assert user.api_keys.get_usable_keys().count() == 0
    assert user.api_keys.count() == 1


@pytest.mark.django_db
def test_validate_org_api_key(org):
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    assert api_key.is_valid(key)
    assert api_key.is_valid("abcd") is False


@pytest.mark.django_db
def test_validate_user_api_key(user):
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)
    assert api_key.is_valid(key)
    assert api_key.is_valid("abcd") is False


@pytest.mark.django_db
def test_set_perms(org):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_CRUD
    )
    assert api_key.grainy_permissions.count() == 1


@pytest.mark.django_db
def test_check_perms(org, groups):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(name="test key", org=org)
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )

    assert check_permissions(api_key, namespace, "r")
    assert check_permissions(api_key, namespace, "u") is False


@pytest.mark.django_db
def test_get_key_from_request():
    key = "abcd"
    factory = RequestFactory()
    request = factory.get("/api/net/1")
    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})
    assert get_key_from_request(request) == key


@pytest.mark.django_db
def test_check_permissions_on_unauth_request(org):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(name="test key", org=org)
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Check permissions without any credentials
    assert hasattr(request, "user") is False
    assert request.META.get("HTTP_AUTHORIZATION") is None
    perm_obj = get_permission_holder_from_request(request)
    print(perm_obj)
    assert check_permissions(perm_obj, namespace, "r") is False


@pytest.mark.django_db
def test_check_permissions_on_org_key_request_readonly(org, groups):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key
    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c") is False
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u") is False
    assert check_permissions(perm_obj, namespace, "d") is False


@pytest.mark.django_db
def test_check_permissions_on_org_key_request_crud(org, groups):
    namespace = "peeringdb.organization.1.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_CRUD
    )

    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key

    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c")
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u")
    assert check_permissions(perm_obj, namespace, "d")


@pytest.mark.django_db
def test_check_permissions_on_user_key_request_crud(user):
    namespace = "peeringdb.organization.1.network"
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)

    UserPermission.objects.create(namespace=namespace, permission=PERM_CRUD, user=user)

    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key
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
        name="test key", user=user, readonly=True
    )
    assert api_key.readonly

    # Define permissions as CRUD
    UserPermission.objects.create(namespace=namespace, permission=PERM_CRUD, user=user)

    factory = RequestFactory()
    request = factory.get("/api/net/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key
    # Test permissions are readonly
    perm_obj = get_permission_holder_from_request(request)
    assert perm_obj == api_key
    assert check_permissions(perm_obj, namespace, "c") is False
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u") is False
    assert check_permissions(perm_obj, namespace, "d") is False


@pytest.mark.django_db
def test_get_network_w_org_key(org, network, user, groups):
    namespace = f"peeringdb.organization.{org.id}.network"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    assert Network.objects.count() == 1
    url = reverse("api:net-detail", args=(network.id,))
    client = APIClient()

    response = client.get(url, HTTP_AUTHORIZATION="Api-Key " + key)
    assert response.status_code == 200

    net_from_api = response.json()["data"][0]
    assert net_from_api["name"] == network.name
    assert net_from_api["asn"] == network.asn
    assert net_from_api["org_id"] == network.org.id


@pytest.mark.django_db
def test_get_network_w_user_key(network, user, org):
    namespace = f"peeringdb.organization.{org.id}.network"
    userperm = UserPermission.objects.create(
        namespace=namespace, permission=PERM_CRUD, user=user
    )
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)

    assert userperm == user.grainy_permissions.first()
    assert Network.objects.count() == 1
    url = reverse("api:net-detail", args=(network.id,))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    response = client.get(url)
    assert response.status_code == 200

    net_from_api = response.json()["data"][0]
    assert net_from_api["name"] == network.name
    assert net_from_api["asn"] == network.asn
    assert net_from_api["org_id"] == network.org.id


@pytest.mark.django_db
def test_bogus_api_key(network):
    url = reverse("api:net-detail", args=(network.id,))
    key = "abcd"
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    client.force_authenticate(token=key)
    response = client.get(url)
    assert response.status_code == 401


@pytest.mark.django_db
def test_key_active_user_session(network, user, org):
    namespace = f"peeringdb.organization.{org.id}.network"
    UserPermission.objects.create(namespace=namespace, permission=PERM_CRUD, user=user)
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)

    url = reverse("api:net-detail", args=(network.id,))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    client.login(username="user", password="user")
    # Save session for user
    client.session["_auth_user_id"] = user.id
    client.session.save()
    response = client.get(url)
    assert response.status_code == 400


@pytest.mark.django_db
def test_check_permissions_on_carrier_org_key_readonly(org, groups):
    namespace = "peeringdb.organization.1.carrier"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    factory = RequestFactory()
    request = factory.get("/api/carrier/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key
    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c") is False
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u") is False
    assert check_permissions(perm_obj, namespace, "d") is False


@pytest.mark.django_db
def test_check_permissions_on_carrier_org_key_crud(org, groups):
    namespace = "peeringdb.organization.1.carrier"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_CRUD
    )

    factory = RequestFactory()
    request = factory.get("/api/carrier/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key

    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c")
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u")
    assert check_permissions(perm_obj, namespace, "d")


@pytest.mark.django_db
def test_get_carrier_w_org_key(org, carrier, groups):
    namespace = f"peeringdb.organization.{org.id}.carrier"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    assert Carrier.objects.count() == 1
    url = reverse("api:carrier-detail", args=(carrier.id,))
    client = APIClient()

    response = client.get(url, HTTP_AUTHORIZATION="Api-Key " + key)
    assert response.status_code == 200

    carrier_from_api = response.json()["data"][0]
    assert carrier_from_api["name"] == carrier.name
    assert carrier_from_api["org_id"] == carrier.org.id


@pytest.mark.django_db
def test_check_permissions_on_facility_org_key_readonly(org, groups):
    namespace = "peeringdb.organization.1.facility"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    factory = RequestFactory()
    request = factory.get("/api/fac/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key
    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c") is False
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u") is False
    assert check_permissions(perm_obj, namespace, "d") is False


@pytest.mark.django_db
def test_check_permissions_on_facility_org_key_crud(org, groups):
    namespace = "peeringdb.organization.1.facility"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_CRUD
    )

    factory = RequestFactory()
    request = factory.get("/api/fac/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key

    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c")
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u")
    assert check_permissions(perm_obj, namespace, "d")


@pytest.mark.django_db
def test_get_facility_w_org_key(org, facility, groups):
    namespace = f"peeringdb.organization.{org.id}.facility"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    assert Facility.objects.count() == 1
    url = reverse("api:fac-detail", args=(facility.id,))
    client = APIClient()

    response = client.get(url, HTTP_AUTHORIZATION="Api-Key " + key)
    assert response.status_code == 200

    fac_from_api = response.json()["data"][0]
    assert fac_from_api["name"] == facility.name
    assert fac_from_api["org_id"] == facility.org.id


@pytest.mark.django_db
def test_check_permissions_on_exchange_org_key_readonly(org, groups):
    namespace = "peeringdb.organization.1.internetexchange"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    factory = RequestFactory()
    request = factory.get("/api/ix/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key
    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c") is False
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u") is False
    assert check_permissions(perm_obj, namespace, "d") is False


@pytest.mark.django_db
def test_check_permissions_on_exchange_org_key_crud(org, groups):
    namespace = "peeringdb.organization.1.internetexchange"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_CRUD
    )

    factory = RequestFactory()
    request = factory.get("/api/ix/1")

    # Add api key header
    request.META.update({"HTTP_AUTHORIZATION": "Api-Key " + key})

    # Assert we're making a request with a OrgAPIKey
    assert hasattr(request, "user") is False
    assert request.META["HTTP_AUTHORIZATION"] == "Api-Key " + key

    # Test permissions
    perm_obj = get_permission_holder_from_request(request)
    assert check_permissions(perm_obj, namespace, "c")
    assert check_permissions(perm_obj, namespace, "r")
    assert check_permissions(perm_obj, namespace, "u")
    assert check_permissions(perm_obj, namespace, "d")


@pytest.mark.django_db
def test_get_exchange_w_org_key(org, exchange, groups):
    namespace = f"peeringdb.organization.{org.id}.internetexchange"
    api_key, key = OrganizationAPIKey.objects.create_key(
        name="test key", org=org, email="test@localhost"
    )
    OrganizationAPIPermission.objects.create(
        org_api_key=api_key, namespace=namespace, permission=PERM_READ
    )
    assert InternetExchange.objects.count() == 1
    url = reverse("api:ix-detail", args=(exchange.id,))
    client = APIClient()

    response = client.get(url, HTTP_AUTHORIZATION="Api-Key " + key)
    assert response.status_code == 200

    ix_from_api = response.json()["data"][0]
    assert ix_from_api["name"] == exchange.name
    assert ix_from_api["org_id"] == exchange.org.id


"""
USER API KEY SCOPING (read-scoped keys)
"""


@pytest.mark.django_db
def test_user_api_permission_model(user):
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)
    UserAPIPermission.objects.create(
        api_key=api_key,
        namespace="peeringdb.organization.1.network.1",
        permission=PERM_READ,
    )
    assert api_key.grainy_permissions.count() == 1
    assert api_key.is_scoped is True


@pytest.mark.django_db
def test_user_api_key_unscoped_by_default(user):
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)
    assert api_key.is_scoped is False


@pytest.mark.django_db
def test_resolve_user_key_permission_id_net(user, org, network):
    UserPermission.objects.create(
        namespace=org.grainy_namespace, permission=PERM_CRUD, user=user
    )
    namespace, error = resolve_user_key_permission_id(user, f"net.{network.id}")
    assert error is None
    assert namespace == network.grainy_namespace


@pytest.mark.django_db
def test_resolve_user_key_permission_id_org(user, org):
    UserPermission.objects.create(
        namespace=org.grainy_namespace, permission=PERM_READ, user=user
    )
    namespace, error = resolve_user_key_permission_id(user, f"org.{org.id}")
    assert error is None
    assert namespace == org.grainy_namespace


@pytest.mark.django_db
def test_resolve_user_key_permission_id_denies_inaccessible_object(
    user, org, network
):
    # user has no permissions on org/network at all
    namespace, error = resolve_user_key_permission_id(user, f"net.{network.id}")
    assert namespace is None
    assert error is not None


@pytest.mark.django_db
def test_resolve_user_key_permission_id_invalid_format(user):
    namespace, error = resolve_user_key_permission_id(user, "not-a-valid-id")
    assert namespace is None
    assert error is not None


@pytest.mark.django_db
def test_resolve_user_key_permission_id_unknown_object(user, org):
    UserPermission.objects.create(
        namespace=org.grainy_namespace, permission=PERM_CRUD, user=user
    )
    namespace, error = resolve_user_key_permission_id(user, "net.999999")
    assert namespace is None
    assert error is not None


@pytest.mark.django_db
def test_user_api_key_scoping_restricts_to_named_object(user, org, network):
    """
    A key scoped to a single network can read that network but
    nothing else under the org, and only ever read (never write) -
    even though the underlying user has full CRUD on the whole org.
    """

    UserPermission.objects.create(
        namespace=org.grainy_namespace, permission=PERM_CRUD, user=user
    )
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)

    namespaces, errors = save_user_key_permissions(user, api_key, [f"net.{network.id}"])
    assert errors == {}
    assert namespaces == [network.grainy_namespace]

    # can read the scoped network
    assert check_permissions(api_key, network.grainy_namespace, "r")
    # cannot write to it, despite the user having CRUD
    assert check_permissions(api_key, network.grainy_namespace, "u") is False
    # cannot see the org-wide namespace the user actually has CRUD on
    assert check_permissions(api_key, org.grainy_namespace, "r") is False


@pytest.mark.django_db
def test_user_api_key_scoping_does_not_expand_access(user, org, network):
    """
    Scoping is a restriction, never a grant: if the user only has
    read on the network, a scoped key pointed at it stays read-only
    (this is also always true regardless, since scoping forces
    PERM_READ - but the underlying intersection logic must not
    accidentally grant more than the user has either).
    """

    UserPermission.objects.create(
        namespace=network.grainy_namespace, permission=PERM_READ, user=user
    )
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)

    namespaces, errors = save_user_key_permissions(user, api_key, [f"net.{network.id}"])
    assert errors == {}

    assert check_permissions(api_key, network.grainy_namespace, "r")
    assert check_permissions(api_key, network.grainy_namespace, "u") is False


@pytest.mark.django_db
def test_user_api_key_scoping_rejects_inaccessible_object(user, org, network):
    """
    Attempting to scope a key to an object the user can't themselves
    read fails outright rather than silently scoping to nothing.
    """

    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)

    namespaces, errors = save_user_key_permissions(user, api_key, [f"net.{network.id}"])
    assert namespaces == []
    assert f"net.{network.id}" in errors
    assert api_key.grainy_permissions.count() == 0


@pytest.mark.django_db
def test_user_api_key_scoping_superuser_not_bypassed(admin_user, org, network):
    """
    Critical case: `Permissions.check` short-circuits to True for
    superusers via `grant_all`. A scoped superuser key must still be
    bound by its declared scope - the intersection logic must not
    let grant_all leak through.
    """

    api_key, key = UserAPIKey.objects.create_key(name="test key", user=admin_user)

    namespaces, errors = save_user_key_permissions(
        admin_user, api_key, [f"net.{network.id}"]
    )
    assert errors == {}

    # scoped network: readable
    assert check_permissions(api_key, network.grainy_namespace, "r")
    # anything outside the declared scope must NOT be reachable,
    # despite the owning user being a superuser
    assert check_permissions(api_key, org.grainy_namespace, "r") is False
    assert check_permissions(api_key, "peeringdb.organization", "r") is False


@pytest.mark.django_db
def test_user_api_key_scoping_removal_restores_full_access(user, org, network):
    UserPermission.objects.create(
        namespace=org.grainy_namespace, permission=PERM_CRUD, user=user
    )
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)

    save_user_key_permissions(user, api_key, [f"net.{network.id}"])
    assert api_key.is_scoped is True
    assert check_permissions(api_key, org.grainy_namespace, "r") is False

    # remove all scoping - key falls back to the user's full permissions
    save_user_key_permissions(user, api_key, [])
    api_key.refresh_from_db()
    assert api_key.is_scoped is False
    assert check_permissions(api_key, org.grainy_namespace, "u")


@pytest.mark.django_db
def test_user_key_permission_update_view(user, org, network):
    UserPermission.objects.create(
        namespace=org.grainy_namespace, permission=PERM_CRUD, user=user
    )
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)

    client = Client()
    client.login(username="user", password="user")

    response = client.post(
        "/user_keys/permissions/update",
        {"key_prefix": api_key.prefix, "entity": f"net.{network.id}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_scoped"] is True
    assert f"net.{network.id}" in data["permissions"]


@pytest.mark.django_db
def test_user_key_permission_update_view_rejects_other_users_key(user, org, network):
    other_user = User.objects.create_user(
        "other", "other@localhost", first_name="other", last_name="other"
    )
    other_user.set_password("other")
    other_user.save()

    UserPermission.objects.create(
        namespace=org.grainy_namespace, permission=PERM_CRUD, user=other_user
    )
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=other_user)

    client = Client()
    client.login(username="user", password="user")

    response = client.post(
        "/user_keys/permissions/update",
        {"key_prefix": api_key.prefix, "entity": f"net.{network.id}"},
    )
    # `user` doesn't own this key - lookup is scoped to request.user,
    # so it should behave as "not found", not leak/modify another
    # user's key
    assert response.status_code == 404


@pytest.mark.django_db
def test_user_key_permission_remove_view(user, org, network):
    UserPermission.objects.create(
        namespace=org.grainy_namespace, permission=PERM_CRUD, user=user
    )
    api_key, key = UserAPIKey.objects.create_key(name="test key", user=user)
    save_user_key_permissions(user, api_key, [f"net.{network.id}"])

    client = Client()
    client.login(username="user", password="user")

    response = client.post(
        "/user_keys/permissions/remove",
        {"key_prefix": api_key.prefix, "entity": f"net.{network.id}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_scoped"] is False
