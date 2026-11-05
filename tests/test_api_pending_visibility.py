"""
Pending objects on the API id routes and the /data facility lists (#513).

A pending object is only returned to callers that may edit it, like on the
website. Everyone else gets the same 404 as for an id that does not exist.
List routes never return pending objects. A campus is pending while it has
fewer than two facilities and stays public.
"""

import pytest
from django.contrib.auth.models import Group
from django_grainy.models import GroupPermission
from grainy.const import PERM_CRUD, PERM_READ
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Campus,
    Carrier,
    CarrierFacility,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLanPrefix,
    Network,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    OrganizationAPIKey,
    User,
    UserAPIKey,
)

pytestmark = pytest.mark.django_db

USERS = ("authenticated", "member", "admin")

# API keys: the admin's own key, the admin's read-only key, and org keys
# with and without write permission on the orgs
KEYS = ("user_key", "readonly_user_key", "org_key", "readonly_org_key")

CALLERS = ("guest",) + USERS + KEYS

# callers allowed to read pending objects of the org
EDITORS = ("admin", "user_key", "org_key")

PENDING_TAGS = (
    "org",
    "net",
    "ix",
    "ixlan",
    "ixpfx",
    "netixlan",
    "fac",
    "netfac",
    "ixfac",
    "carrier",
    "carrierfac",
)


@pytest.fixture
def pending_data(db, settings):
    settings.API_CACHE_ENABLED = False
    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    settings.GUEST_GROUP_ID = guest_group.pk
    settings.USER_GROUP_ID = user_group.pk
    for group in (guest_group, user_group):
        GroupPermission.objects.create(
            group=group, namespace="peeringdb.organization", permission=0x01
        )

    org = Organization.objects.create(name="Pending visibility org", status="ok")
    pending_org = Organization.objects.create(
        name="Pending visibility pending org", status="pending"
    )
    net = Network.objects.create(
        name="Pending visibility net", asn=63451, org=org, status="ok"
    )
    ix = InternetExchange.objects.create(
        name="Pending visibility IX", org=org, status="ok"
    )
    fac = Facility.objects.create(
        name="Pending visibility fac",
        org=org,
        status="ok",
        city="City",
        country="US",
        latitude=41.88,
        longitude=-87.63,
    )
    carrier = Carrier.objects.create(
        name="Pending visibility carrier", org=org, status="ok"
    )

    campus = Campus.objects.create(name="Pending visibility campus", org=org)
    campus.refresh_from_db()
    assert campus.status == "pending"

    pending_ix = InternetExchange.objects.create(
        name="Pending visibility pending IX", org=org, status="pending"
    )
    ixlan = pending_ix.ixlan
    ixlan.status = "pending"
    ixlan.save()

    pending = {
        "org": pending_org,
        "net": Network.objects.create(
            name="Pending visibility pending net", asn=63452, org=org, status="pending"
        ),
        "ix": pending_ix,
        "ixlan": ixlan,
        "ixpfx": IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.100.0/24", status="pending"
        ),
        "netixlan": NetworkIXLan.objects.create(
            network=net,
            ixlan=ix.ixlan,
            asn=net.asn,
            speed=1000,
            ipaddr4="198.51.100.10",
            status="pending",
        ),
        "fac": Facility.objects.create(
            name="Pending visibility pending fac",
            org=org,
            status="pending",
            city="City",
            country="US",
            latitude=41.88,
            longitude=-87.63,
            campus=campus,
        ),
        "netfac": NetworkFacility.objects.create(
            network=net, facility=fac, status="pending"
        ),
        "ixfac": InternetExchangeFacility.objects.create(
            ix=ix, facility=fac, status="pending"
        ),
        "carrier": Carrier.objects.create(
            name="Pending visibility pending carrier", org=org, status="pending"
        ),
        "carrierfac": CarrierFacility.objects.create(
            carrier=carrier, facility=fac, status="pending"
        ),
    }
    for tag, obj in pending.items():
        obj.refresh_from_db()
        assert obj.status == "pending", tag

    users = {}
    for caller in USERS:
        users[caller] = User.objects.create(username=f"pending-visibility-{caller}")
        users[caller].groups.add(user_group)
        users[caller].set_verified()
    org.usergroup.user_set.add(users["member"])
    pending_org.usergroup.user_set.add(users["member"])
    org.admin_usergroup.user_set.add(users["admin"])
    pending_org.admin_usergroup.user_set.add(users["admin"])

    keys = {}
    for caller, readonly in (("user_key", False), ("readonly_user_key", True)):
        _, keys[caller] = UserAPIKey.objects.create_key(
            user=users["admin"], name=caller, readonly=readonly
        )
    for caller, perms in (("org_key", PERM_CRUD), ("readonly_org_key", PERM_READ)):
        api_key, keys[caller] = OrganizationAPIKey.objects.create_key(
            org=org, name=caller, email=f"{caller}@example.invalid"
        )
        for each in (org, pending_org):
            api_key.grainy_permissions.add_permission(each.grainy_namespace, perms)

    return {
        "org": org,
        "net": net,
        "fac": fac,
        "campus": campus,
        "pending": pending,
        "users": users,
        "keys": keys,
    }


def api_client(data, caller):
    client = APIClient()
    if caller in USERS:
        client.force_authenticate(user=data["users"][caller])
    elif caller in KEYS:
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {data['keys'][caller]}")
    return client


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("tag", PENDING_TAGS)
def test_pending_object_by_id(pending_data, caller, tag):
    obj = pending_data["pending"][tag]
    resp = api_client(pending_data, caller).get(f"/api/{tag}/{obj.id}")

    if caller in EDITORS:
        assert resp.status_code == 200, resp.content
        row = resp.json()["data"][0]
        assert row["id"] == obj.id
        assert row["status"] == "pending"
    else:
        assert resp.status_code == 404, resp.content
        missing = api_client(pending_data, caller).get(f"/api/{tag}/999999")
        assert missing.status_code == 404
        assert resp.json() == missing.json()


@pytest.mark.parametrize("caller", ("guest", "member", "admin"))
def test_pending_object_head(pending_data, caller):
    obj = pending_data["pending"]["fac"]
    resp = api_client(pending_data, caller).head(f"/api/fac/{obj.id}")
    assert resp.status_code == (200 if caller in EDITORS else 404)


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("tag", PENDING_TAGS)
def test_pending_object_not_listed(pending_data, caller, tag):
    obj = pending_data["pending"][tag]
    resp = api_client(pending_data, caller).get(f"/api/{tag}", {"id": obj.id})
    assert resp.status_code == 404, resp.content


@pytest.mark.parametrize("caller", CALLERS)
def test_pending_campus_stays_public(pending_data, caller):
    campus = pending_data["campus"]
    resp = api_client(pending_data, caller).get(f"/api/campus/{campus.id}")
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"][0]["status"] == "pending"


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("tag", ("org", "net", "fac"))
def test_live_object_by_id(pending_data, caller, tag):
    obj = pending_data[tag]
    resp = api_client(pending_data, caller).get(f"/api/{tag}/{obj.id}")
    assert resp.status_code == 200, resp.content


def pending_carrier_payload(data, notes):
    obj = data["pending"]["carrier"]
    resp = api_client(data, "admin").get(f"/api/carrier/{obj.id}")
    assert resp.status_code == 200, resp.content
    payload = resp.json()["data"][0]
    payload["notes"] = notes
    payload["website"] = "https://example.invalid"
    return obj, payload


def test_editor_can_update_pending_object(pending_data):
    obj, payload = pending_carrier_payload(pending_data, "updated while pending")
    resp = api_client(pending_data, "admin").put(
        f"/api/carrier/{obj.id}", payload, format="json"
    )
    assert resp.status_code == 200, resp.content
    obj.refresh_from_db()
    assert obj.notes == "updated while pending"
    assert obj.status == "pending"


@pytest.mark.parametrize("caller", ("authenticated", "member"))
def test_non_editor_cannot_update_pending_object(pending_data, caller):
    obj, payload = pending_carrier_payload(pending_data, "not allowed")
    resp = api_client(pending_data, caller).put(
        f"/api/carrier/{obj.id}", payload, format="json"
    )
    assert resp.status_code == 403, resp.content
    obj.refresh_from_db()
    assert obj.notes != "not allowed"


def test_data_campus_facilities_hides_pending(pending_data):
    pending_fac = pending_data["pending"]["fac"]
    ok_fac = pending_data["fac"]
    ok_fac.campus = pending_data["campus"]
    ok_fac.save()

    resp = APIClient().get("/data/campus_facilities")
    assert resp.status_code == 200
    listed = resp.json()["campus_facilities"]
    assert str(ok_fac.id) in listed
    assert str(pending_fac.id) not in listed


def test_data_facilities_hides_pending(pending_data):
    client = APIClient()
    client.force_login(pending_data["users"]["authenticated"])
    resp = client.get("/data/facilities")
    assert resp.status_code == 200
    listed = [row["id"] for row in resp.json()["facilities"]]
    assert pending_data["fac"].id in listed
    assert pending_data["pending"]["fac"].id not in listed


NON_EDITORS = tuple(caller for caller in CALLERS if caller not in EDITORS)


@pytest.fixture
def campusless_pending_fac(pending_data):
    return Facility.objects.create(
        name="Pending visibility campusless fac",
        org=pending_data["org"],
        status="pending",
        city="City",
        country="US",
    )


@pytest.mark.parametrize("caller", NON_EDITORS)
def test_campus_remove_facility_hides_pending(
    pending_data, campusless_pending_fac, caller
):
    client = api_client(pending_data, caller)
    campus = pending_data["campus"]

    for fac in (campusless_pending_fac, pending_data["pending"]["fac"]):
        resp = client.post(f"/api/campus/{campus.id}/remove-facility/{fac.id}")
        assert resp.status_code == 403, resp.content
        assert fac.name.encode() not in resp.content

    pending_data["pending"]["fac"].refresh_from_db()
    assert pending_data["pending"]["fac"].campus_id == campus.id

    resp = client.post(f"/api/campus/{campus.id}/remove-facility/999999")
    assert resp.status_code == 404, resp.content


def test_campus_remove_facility_editor(pending_data, campusless_pending_fac):
    client = api_client(pending_data, "admin")
    campus = pending_data["campus"]

    resp = client.post(
        f"/api/campus/{campus.id}/remove-facility/{campusless_pending_fac.id}"
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"][0]["id"] == campusless_pending_fac.id

    fac = pending_data["pending"]["fac"]
    resp = client.post(f"/api/campus/{campus.id}/remove-facility/{fac.id}")
    assert resp.status_code == 200, resp.content
    fac.refresh_from_db()
    assert fac.campus_id is None
