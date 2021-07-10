import pytest
from django.core.management import call_command
from django.test import Client

from peeringdb_server.models import (
    Organization,
    Sponsorship,
    SponsorshipOrganization,
    User,
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name",
    [
        "RATIOS",
        "RATIOS_TRUNC",
        "RATIOS_ADVS",
        "TRAFFIC",
        "SCOPES",
        "SCOPES_TRUNC",
        "SCOPES_ADVS",
        "NET_TYPES",
        "NET_TYPES_TRUNC",
        "NET_TYPES_ADVS",
        "POLICY_GENERAL",
        "POLICY_LOCATIONS",
        "POLICY_CONTRACTS",
        "REGIONS",
        "POC_ROLES",
        "MEDIA",
        "PROTOCOLS",
        "ORG_GROUPS",
        "BOOL_CHOICE_STR",
        "VISIBILITY",
    ],
)
def test_enum(name):
    client = Client()
    response = client.get(f"/data/enum/{name}")
    assert response.status_code == 200
    assert len(response.json()[f"enum/{name}"]) > 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,user,count,status",
    [
        ("countries_b", "user", 1, 200),
        ("countries", "user", 1, 200),
        ("sponsors", "user", 1, 200),
        ("facilities", "user", 4, 200),
        ("organizations", "user", 0, 403),
        ("organizations", "su", 1, 200),
    ],
)
def test_generic(name, user, count, status):
    call_command("pdb_generate_test_data", limit=3, commit=True)

    org = Organization.objects.first()

    sponsorship = Sponsorship.objects.create(level=1)
    SponsorshipOrganization.objects.create(
        org=org, sponsorship=sponsorship, logo="fake.png"
    )

    _user = User.objects.create_user(
        username="user_a", password="user_a", email="user_a@localhost"
    )

    if user == "su":
        _user.is_superuser = True
        _user.is_staff = True
        _user.save()

    org.usergroup.user_set.add(_user)

    client = Client()
    client.login(username="user_a", password="user_a")
    response = client.get(f"/data/{name}")

    assert response.status_code == status
    if status == 200:
        assert len(response.json()[name]) >= count


@pytest.mark.django_db
def test_my_organizations():
    call_command("pdb_generate_test_data", limit=3, commit=True)

    org = Organization.objects.first()
    _user = User.objects.create_user(
        username="user_a", password="user_a", email="user_a@localhost"
    )
    org.usergroup.user_set.add(_user)

    client = Client()
    client.login(username="user_a", password="user_a")
    response = client.get("/data/my_organizations")

    assert response.status_code == 200
    assert len(response.json()["my_organizations"]) == 1


@pytest.mark.django_db
def test_my_organizations_anon():
    call_command("pdb_generate_test_data", limit=3, commit=True)

    client = Client()
    response = client.get("/data/my_organizations")

    assert response.status_code == 200
    assert len(response.json()["my_organizations"]) == 0
