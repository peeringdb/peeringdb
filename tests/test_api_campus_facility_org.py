"""
A facility joins a campus of its own organization only (#524).

The campus add-facility endpoint always required the campus and the
facility to share an organization; the generic facility routes now apply
the same rule. A campus that is sent back unchanged is not re-checked.
"""

import pytest
import reversion
from django.contrib.auth.models import Group
from django_grainy.models import GroupPermission
from rest_framework.test import APIClient

from peeringdb_server.models import Campus, Facility, Organization, User

pytestmark = pytest.mark.django_db

POINT = (41.88, -87.63)


def make_facility(name, org, **kwargs):
    fields = dict(
        name=name,
        org=org,
        status="ok",
        address1="1 Main St",
        city="Chicago",
        zipcode="60601",
        country="US",
        latitude=POINT[0],
        longitude=POINT[1],
    )
    fields.update(kwargs)
    return Facility.objects.create(**fields)


@pytest.fixture
def campus_data(settings):
    settings.API_CACHE_ENABLED = False
    settings.RATELIMIT_ENABLE = False
    settings.MELISSA_KEY = ""
    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    settings.GUEST_GROUP_ID = guest_group.pk
    settings.USER_GROUP_ID = user_group.pk
    for group in (guest_group, user_group):
        GroupPermission.objects.create(
            group=group, namespace="peeringdb.organization", permission=0x01
        )

    with reversion.create_revision():
        campus_org = Organization.objects.create(
            name="Campus owner org", status="ok", website="https://campus.example"
        )
        fac_org = Organization.objects.create(
            name="Facility owner org", status="ok", website="https://fac.example"
        )
        campus = Campus.objects.create(name="Owned campus", org=campus_org)
        make_facility("Campus facility A", campus_org, campus=campus)
        make_facility("Campus facility B", campus_org, campus=campus)
        own_campus = Campus.objects.create(name="Facility org campus", org=fac_org)
        fac = make_facility("Foreign facility", fac_org)

    campus.refresh_from_db()
    assert campus.status == "ok"

    admin = User.objects.create(username="campus-fac-admin")
    admin.groups.add(user_group)
    admin.set_verified()
    fac_org.admin_usergroup.user_set.add(admin)

    client = APIClient()
    client.force_authenticate(user=admin)

    return {
        "campus": campus,
        "own_campus": own_campus,
        "fac": fac,
        "fac_org": fac_org,
        "client": client,
    }


def fac_data(client, fac):
    resp = client.get(f"/api/fac/{fac.id}")
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"][0]
    data.pop("_grainy", None)
    return data


def test_put_foreign_campus_refused(campus_data):
    client, fac, campus = (
        campus_data["client"],
        campus_data["fac"],
        campus_data["campus"],
    )
    data = fac_data(client, fac)
    data["campus_id"] = campus.id

    resp = client.put(f"/api/fac/{fac.id}", data, format="json")

    assert resp.status_code == 400, resp.content
    assert "campus_id" in resp.json()
    fac.refresh_from_db()
    assert fac.campus_id is None
    assert fac.id not in campus.fac_set.values_list("id", flat=True)


def test_post_foreign_campus_refused(campus_data):
    client, campus = campus_data["client"], campus_data["campus"]

    resp = client.post(
        "/api/fac",
        {
            "org_id": campus_data["fac_org"].id,
            "name": "New foreign campus facility",
            "address1": "1 Main St",
            "city": "Chicago",
            "zipcode": "60601",
            "country": "US",
            "latitude": POINT[0],
            "longitude": POINT[1],
            "campus_id": campus.id,
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert "campus_id" in resp.json()
    assert not Facility.objects.filter(name="New foreign campus facility").exists()


def test_put_own_campus_allowed(campus_data):
    client, fac, own_campus = (
        campus_data["client"],
        campus_data["fac"],
        campus_data["own_campus"],
    )
    data = fac_data(client, fac)
    data["campus_id"] = own_campus.id

    resp = client.put(f"/api/fac/{fac.id}", data, format="json")

    assert resp.status_code == 200, resp.content
    fac.refresh_from_db()
    assert fac.campus_id == own_campus.id


def test_put_unchanged_foreign_campus_allowed(campus_data):
    # attachments made before the rule (or by staff) keep the facility
    # editable through the API
    client, fac, campus = (
        campus_data["client"],
        campus_data["fac"],
        campus_data["campus"],
    )
    fac.campus = campus
    fac.save()

    data = fac_data(client, fac)
    assert data["campus_id"] == campus.id
    data["notes"] = "Edited"

    resp = client.put(f"/api/fac/{fac.id}", data, format="json")

    assert resp.status_code == 200, resp.content
    fac.refresh_from_db()
    assert fac.campus_id == campus.id
    assert fac.notes == "Edited"


def test_add_facility_endpoint_still_refuses_foreign_facility(campus_data):
    client, fac, campus = (
        campus_data["client"],
        campus_data["fac"],
        campus_data["campus"],
    )

    # the facility admin has no permission on the campus
    resp = client.post(f"/api/campus/{campus.id}/add-facility/{fac.id}")

    assert resp.status_code == 403, resp.content
    fac.refresh_from_db()
    assert fac.campus_id is None
