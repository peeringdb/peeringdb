import pytest
from django.test import Client, RequestFactory
from django.urls import reverse
from django_grainy.models import UserPermission
from django_otp.plugins.otp_totp.models import TOTPDevice
from grainy.const import PERM_CRUD, PERM_READ
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Carrier,
    Facility,
    Group,
    InternetExchange,
    Network,
    NetworkContact,
    Organization,
    OrganizationAPIKey,
    OrganizationAPIPermission,
    User,
    UserAPIKey,
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
def test_check_permissions_on_superuser_key_request_readonly(admin_user):
    """
    A readonly key of a superuser reads everything its owner reads and
    writes nothing
    """

    api_key, key = UserAPIKey.objects.create_key(
        name="test key", user=admin_user, readonly=True
    )

    request = RequestFactory().put("/api/net/1", HTTP_AUTHORIZATION="Api-Key " + key)
    perm_obj = get_permission_holder_from_request(request)
    assert perm_obj == api_key

    for namespace in [
        "peeringdb.organization.1.network.1",
        "peeringdb.organization.1.network.1.poc_set.private",
        "peeringdb.manage_organization.1",
    ]:
        assert check_permissions(perm_obj, namespace, "r")
        # the API output filter checks private fields explicitly
        assert check_permissions(perm_obj, namespace, "r", explicit=True)
        assert check_permissions(perm_obj, namespace, "c") is False
        assert check_permissions(perm_obj, namespace, "u") is False
        assert check_permissions(perm_obj, namespace, "d") is False
        assert check_permissions(perm_obj, namespace, "cr") is False


@pytest.mark.django_db
def test_read_private_data_w_superuser_readonly_key(network, exchange, admin_user):
    poc = NetworkContact.objects.create(
        network=network,
        status="ok",
        role="Abuse",
        visible="Private",
        name="private contact",
        email="private@localhost",
    )
    ixlan = exchange.ixlan
    ixlan.ixf_ixp_member_list_url = "https://example.invalid/private-feed.json"
    ixlan.ixf_ixp_member_list_url_visible = "Private"
    ixlan.save()

    _, key = UserAPIKey.objects.create_key(
        name="test key", user=admin_user, readonly=True
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)

    response = client.get(reverse("api:poc-detail", args=(poc.id,)))
    assert response.status_code == 200
    assert response.json()["data"][0]["email"] == "private@localhost"

    response = client.get(reverse("api:ixlan-detail", args=(ixlan.id,)))
    assert response.status_code == 200
    assert response.json()["data"][0]["ixf_ixp_member_list_url"] == (
        "https://example.invalid/private-feed.json"
    )


@pytest.mark.django_db
def test_check_permissions_on_superuser_key_request_crud(admin_user):
    _, key = UserAPIKey.objects.create_key(name="test key", user=admin_user)

    request = RequestFactory().put("/api/net/1", HTTP_AUTHORIZATION="Api-Key " + key)
    perm_obj = get_permission_holder_from_request(request)
    namespace = "peeringdb.organization.1.network.1"

    assert check_permissions(perm_obj, namespace, "u")
    assert check_permissions(perm_obj, namespace, "d")


@pytest.mark.django_db
def test_update_network_w_superuser_readonly_key(network, admin_user, org):
    _, key = UserAPIKey.objects.create_key(
        name="test key", user=admin_user, readonly=True
    )
    url = reverse("api:net-detail", args=(network.id,))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)

    response = client.get(url)
    assert response.status_code == 200

    response = client.put(
        url,
        {"name": "changed", "org_id": org.id, "asn": network.asn},
        format="json",
    )
    # denied API key writes answer 401 from the permission class, and 403
    # from the destroy view's own check, as they do for any other key
    assert response.status_code == 401

    response = client.delete(url)
    assert response.status_code == 403

    network.refresh_from_db()
    assert network.name == "test network"
    assert network.status == "ok"


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


@pytest.mark.django_db
@pytest.mark.parametrize("ui_next", [True, False])
def test_profile_offers_readonly_keys_to_superusers(
    admin_user, network, org, settings, ui_next
):
    admin_user.opt_flags = settings.USER_OPT_FLAG_UI_NEXT
    if not ui_next:
        admin_user.opt_flags |= settings.USER_OPT_FLAG_UI_NEXT_REJECTED
    admin_user.save()
    TOTPDevice.objects.create(user=admin_user, name="phone", confirmed=True)
    client = Client()
    client.force_login(admin_user)

    response = client.get("/profile")
    assert response.status_code == 200
    template = ("site_next" if ui_next else "site") + "/profile-api-keys.html"
    assert template in [t.name for t in response.templates]
    content = response.content.decode()
    assert 'data-edit-name="readonly"' in content
    assert "cannot be made read only" not in content

    response = client.post(
        "/user_keys/add",
        {"name": "read-only superuser key", "readonly": "true", "password": "admin"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert UserAPIKey.objects.get(prefix=data["prefix"]).readonly

    api_client = APIClient()
    api_client.credentials(HTTP_AUTHORIZATION="Api-Key " + data["key"])
    url = reverse("api:net-detail", args=(network.id,))
    assert api_client.get(url).status_code == 200
    response = api_client.put(
        url,
        {"name": "changed", "org_id": org.id, "asn": network.asn},
        format="json",
    )
    assert response.status_code == 401
    network.refresh_from_db()
    assert network.name == "test network"
