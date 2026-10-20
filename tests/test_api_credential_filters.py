"""
Filters must not let a caller test values the API does not show them (#489).

Each excluded relation or field is queried with its real value and with a
value that matches nothing: both must return the unfiltered list.
"""

import re
import time

import pytest
from django.contrib.auth.models import Group
from django_grainy.models import GroupPermission
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXFImportEmail,
    IXFMemberData,
    Network,
    NetworkFacility,
    NetworkIXLan,
    OAuthApplication,
    Organization,
    OrganizationAPIKey,
    User,
    UserOrgAffiliationRequest,
)
from peeringdb_server.rest import REFTAG_MAP
from peeringdb_server.serializers import (
    FILTER_EXCLUDE,
    FacilitySerializer,
    InternetExchangeSerializer,
    IXLanSerializer,
    NetworkSerializer,
    OrganizationSerializer,
    filter_name_forms,
    get_relation_filters,
    is_filter_excluded,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def filter_data(db, settings):
    settings.API_CACHE_ENABLED = False
    for group_id_setting, name in (
        ("GUEST_GROUP_ID", "guest"),
        ("USER_GROUP_ID", "user"),
    ):
        group = Group.objects.create(name=name)
        setattr(settings, group_id_setting, group.pk)
        GroupPermission.objects.create(
            group=group, namespace="peeringdb.organization", permission=0x01
        )

    user = User.objects.create(username="filter-fixture-user")
    user.groups.add(Group.objects.get(name="user"))
    requester = User.objects.create(
        username="filter-fixture-requester", email="requester@example.invalid"
    )

    org = Organization.objects.create(
        name="Filter fixture org",
        status="ok",
        email_domains="example.invalid",
        restrict_user_emails=True,
    )
    other_org = Organization.objects.create(
        name="Other filter fixture org", status="ok"
    )
    api_key, _ = OrganizationAPIKey.objects.create_key(
        org=org, name="fixture key", email="key-contact@example.invalid"
    )
    app = OAuthApplication.objects.create(
        org=org,
        name="Fixture OAuth app",
        client_id="fixture-client-id",
        client_secret="fixture-client-secret",
        client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://example.invalid/callback",
    )
    affiliation = UserOrgAffiliationRequest.objects.create(
        user=requester, org=org, asn=63399, status="pending"
    )

    net = Network.objects.create(
        name="Filter fixture net",
        asn=63311,
        org=org,
        status="ok",
        notes_private="fixture private note",
    )
    # editable=False, so set outside of create()
    Network.objects.filter(pk=net.pk).update(irr_as_set_status="gone")
    net.refresh_from_db()
    other_net = Network.objects.create(
        name="Other filter fixture net", asn=63312, org=other_org, status="ok"
    )
    ix = InternetExchange.objects.create(
        name="Filter fixture IX",
        org=org,
        status="ok",
        ixf_import_request_user=requester,
    )
    other_ix = InternetExchange.objects.create(
        name="Other filter fixture IX", org=other_org, status="ok"
    )
    fac = Facility.objects.create(
        name="Filter fixture fac", org=org, status="ok", city="City", country="US"
    )
    other_fac = Facility.objects.create(
        name="Other filter fixture fac",
        org=other_org,
        status="ok",
        city="City",
        country="US",
    )
    email = IXFImportEmail.objects.create(
        subject="Fixture IX-F subject",
        message="Fixture IX-F message",
        recipients="ixf-recipient@example.invalid",
        net=net,
        ix=ix,
    )
    member_data = IXFMemberData.instantiate(
        63311, "195.69.144.1", "2001:7f8:1::a500:2906:1", ix.ixlan, data={}
    )
    member_data.ix_side = fac
    member_data.error = "fixture import error"
    member_data.save()

    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://example.invalid/private-feed.json"
    ixlan.ixf_ixp_member_list_url_visible = "Private"
    ixlan.ixf_ixp_import_error = "fixture import error"
    ixlan.descr = "fixture descr"
    ixlan.save()

    # the related_to_* filter route only matches through these links
    netixlan = NetworkIXLan.objects.create(
        network=net,
        ixlan=ixlan,
        asn=net.asn,
        speed=1000,
        ipaddr4="195.69.144.10",
        ipaddr6="2001:7f8:1::a506:3311:1",
        status="ok",
    )
    NetworkFacility.objects.create(network=net, facility=fac, status="ok")
    ixfac = InternetExchangeFacility.objects.create(ix=ix, facility=fac, status="ok")

    return {
        "user": user,
        "requester": requester,
        "org": (org, other_org),
        "net": (net, other_net),
        "ix": (ix, other_ix),
        "fac": (fac, other_fac),
        "ixlan": (ix.ixlan, other_ix.ixlan),
        "api_key": api_key,
        "app": app,
        "affiliation": affiliation,
        "email": email,
        "member_data": member_data,
        "netixlan": netixlan,
        "ixfac": ixfac,
    }


def api_clients(data):
    guest = APIClient()
    authenticated = APIClient()
    authenticated.force_authenticate(user=data["user"])
    return {"guest": guest, "authenticated": authenticated}


@pytest.mark.parametrize(
    "serializer,excluded",
    [
        (
            OrganizationSerializer,
            (
                "api_keys",
                "oauth_applications",
                "affiliation_requests",
                "net_set__notes_private",
            ),
        ),
        (NetworkSerializer, ("network_email_set",)),
        (InternetExchangeSerializer, ("ix_email_set", "ixf_import_request_user")),
        (FacilitySerializer, ("ixf_member_data_set",)),
        (IXLanSerializer, ("ixf_set",)),
    ],
)
def test_queryable_relations_exclude_private_relations(serializer, excluded):
    fields = dict(serializer.queryable_relations())
    for name in excluded:
        assert not any(f == name or f.startswith(f"{name}__") for f in fields)


# (endpoint, parameter, fixture attribute holding a matching value)
EXCLUDED_FILTERS = [
    ("org", "api_keys", "api_key.pk"),
    ("org", "api_keys__in", "api_key.pk"),
    ("org", "api_keys__startswith", "api_key.prefix"),
    ("org", "api_keys__contains", "api_key.prefix"),
    ("org", "api_keys__id__startswith", "api_key.prefix"),
    ("org", "api_keys__prefix", "api_key.prefix"),
    ("org", "api_keys__prefix__startswith", "api_key.prefix"),
    ("org", "api_keys__hashed_key", "api_key.hashed_key"),
    ("org", "api_keys__hashed_key__startswith", "api_key.hashed_key"),
    ("org", "api_keys__email", "api_key.email"),
    ("org", "api_keys__email__contains", "api_key.email"),
    ("org", "api_keys__name", "api_key.name"),
    ("org", "oauth_applications", "app.pk"),
    ("org", "oauth_applications__in", "app.pk"),
    ("org", "oauth_applications__client_secret__startswith", "app.client_secret"),
    ("org", "oauth_applications__name", "app.name"),
    ("org", "oauth_applications__redirect_uris__contains", "app.redirect_uris"),
    ("org", "affiliation_requests", "affiliation.pk"),
    ("org", "affiliation_requests__in", "affiliation.pk"),
    ("org", "affiliation_requests__asn", "affiliation.asn"),
    ("net", "notes_private", "net.0.notes_private"),
    ("net", "notes_private__contains", "net.0.notes_private"),
    ("net", "network_email_set", "email.pk"),
    ("net", "network_email_set__in", "email.pk"),
    ("net", "network_email_set__recipients__contains", "email.recipients"),
    ("net", "network_email_set__subject", "email.subject"),
    ("net", "network_email_set__message__contains", "email.message"),
    ("ix", "ix_email_set", "email.pk"),
    ("ix", "ix_email_set__in", "email.pk"),
    ("ix", "ix_email_set__recipients__contains", "email.recipients"),
    ("ix", "ix_email_set__subject", "email.subject"),
    ("ix", "ix_email_set__message__contains", "email.message"),
    ("ix", "ixf_import_request_user", "requester.pk"),
    ("ix", "ixf_import_request_user_id", "requester.pk"),
    ("ix", "ixf_import_request_user__in", "requester.pk"),
    ("fac", "ixf_member_data_set", "member_data.pk"),
    ("fac", "ixf_member_data_set__in", "member_data.pk"),
    ("fac", "ixf_member_data_set__error__contains", "member_data.error"),
    ("fac", "ixf_member_data_set__ipaddr4", "member_data.ipaddr4"),
    ("ixlan", "ixf_set", "member_data.pk"),
    ("ixlan", "ixf_set__in", "member_data.pk"),
    ("ixlan", "ixf_set__error__contains", "member_data.error"),
    ("ixlan", "ixf_set__ipaddr4", "member_data.ipaddr4"),
    ("ixlan", "ixf_ixp_member_list_url", "ixlan.0.ixf_ixp_member_list_url"),
    (
        "ixlan",
        "ixf_ixp_member_list_url__startswith",
        "ixlan.0.ixf_ixp_member_list_url",
    ),
    ("ix", "ixlan_set__ixf_ixp_member_list_url", "ixlan.0.ixf_ixp_member_list_url"),
    # handled by prepare_query / get_relation_filters rather than rest.py
    ("ix", "ixlan__ixf_ixp_member_list_url", "ixlan.0.ixf_ixp_member_list_url"),
    (
        "ix",
        "ixlan__ixf_ixp_member_list_url__startswith",
        "ixlan.0.ixf_ixp_member_list_url",
    ),
    ("net", "ixlan__ixf_ixp_member_list_url", "ixlan.0.ixf_ixp_member_list_url"),
    ("ix", "net__notes_private", "net.0.notes_private"),
    ("ix", "net__notes_private__contains", "net.0.notes_private"),
    ("fac", "net__notes_private__contains", "net.0.notes_private"),
    # a doubled `_id` used to survive one round of translation, and the ORM
    # takes the foreign key's attname
    ("net", "ix__ixf_import_request_user_id_id", "requester.pk"),
    ("net", "ix__ixf_import_request_user_id_id__in", "requester.pk"),
    ("fac", "ix__ixf_import_request_user_id_id", "requester.pk"),
    ("fac", "ix__ixf_import_request_user_id_id__in", "requester.pk"),
    # compound entry with a third segment the relation route used to drop
    ("net", "ixlan__descr__iexact", "ixlan.0.descr"),
    # model fields the api never serializes
    ("org", "email_domains__contains", "org.0.email_domains"),
    ("org", "restrict_user_emails", "org.0.restrict_user_emails"),
    ("net", "org__email_domains__contains", "org.0.email_domains"),
    ("net", "irr_as_set_status", "net.0.irr_as_set_status"),
    ("ixlan", "ixf_ixp_import_error__contains", "ixlan.0.ixf_ixp_import_error"),
    (
        "ix",
        "ixlan_set__ixf_ixp_import_error__contains",
        "ixlan.0.ixf_ixp_import_error",
    ),
    ("ix", "ixlan__ixf_ixp_import_error__contains", "ixlan.0.ixf_ixp_import_error"),
]


def resolve(data, path):
    """
    `"api_key.prefix"` -> `data["api_key"].prefix`, and `"net.0.notes_private"`
    picks the first object of a (target, other) pair.
    """
    name, *rest = path.split(".")
    value = data[name]
    for part in rest:
        value = value[int(part)] if part.isdigit() else getattr(value, part)
    return str(value)


@pytest.mark.parametrize("client_name", ["guest", "authenticated"])
@pytest.mark.parametrize("endpoint,parameter,path", EXCLUDED_FILTERS)
def test_excluded_filters_are_ignored(
    filter_data, client_name, endpoint, parameter, path
):
    client = api_clients(filter_data)[client_name]
    expected = {obj.pk for obj in filter_data[endpoint]}

    baseline = client.get(f"/api/{endpoint}")
    assert baseline.status_code == 200
    assert {row["id"] for row in baseline.json()["data"]} == expected

    for value in (resolve(filter_data, path), "no-such-value"):
        response = client.get(f"/api/{endpoint}", {parameter: value})
        assert response.status_code == 200
        assert {row["id"] for row in response.json()["data"]} == expected


@pytest.mark.parametrize("client_name", ["guest", "authenticated"])
@pytest.mark.parametrize(
    "parameter,path",
    [
        ("ixlan__ixlan_ixf_ixp_member_list_url", "ixlan.0.ixf_ixp_member_list_url"),
        (
            "ixlan__ixlan_ixf_ixp_member_list_url__startswith",
            "ixlan.0.ixf_ixp_member_list_url",
        ),
        (
            "ixlan__ixlan_ixf_ixp_import_error__contains",
            "ixlan.0.ixf_ixp_import_error",
        ),
    ],
)
def test_relation_prefix_does_not_reach_excluded_fields(
    filter_data, client_name, parameter, path
):
    """
    make_relation_filter used to strip a second `ixlan_` prefix, turning these
    into filters on excluded ixlan fields. They are now invalid field names,
    which the relation filter route rejects as an invalid query.
    """
    client = api_clients(filter_data)[client_name]
    for value in (resolve(filter_data, path), "no-such-value"):
        response = client.get("/api/ix", {parameter: value})
        assert response.status_code == 400


@pytest.mark.parametrize("client_name", ["guest", "authenticated"])
@pytest.mark.parametrize(
    "endpoint,parameter,value",
    [
        ("org", "name", "Filter fixture org"),
        ("org", "ix_set__name", "Filter fixture IX"),
        ("org", "ix_set__name__startswith", "Filter fixture"),
        ("net", "org__name", "Filter fixture org"),
        ("net", "asn__in", "63311"),
        ("ix", "org_id", "@ix.0.org_id"),
        ("fac", "name", "Filter fixture fac"),
        ("ixlan", "ix_id", "@ixlan.0.ix_id"),
        # relation filter forms handled by prepare_query / make_relation_filter
        ("net", "ixlan", "@ixlan.0.pk"),
        ("net", "netixlan__id", "@netixlan.pk"),
        ("ix", "ixfac", "@ixfac.pk"),
        ("ix", "fac__in", "@fac.0.pk"),
        ("fac", "ix_id", "@ix.0.pk"),
    ],
)
def test_supported_filters_still_apply(
    filter_data, client_name, endpoint, parameter, value
):
    client = api_clients(filter_data)[client_name]
    target = filter_data[endpoint][0]
    if value.startswith("@"):
        value = resolve(filter_data, value[1:])
    for extra in (
        {},
        {"api_keys__email": "not-found@example.invalid"},
        {"notes_private": "not-found"},
    ):
        response = client.get(f"/api/{endpoint}", {parameter: value, **extra})
        assert response.status_code == 200
        assert [row["id"] for row in response.json()["data"]] == [target.pk]


@pytest.mark.parametrize("tag", sorted(REFTAG_MAP))
def test_filterable_fields_exclude_filter_exclude(tag):
    """
    Covers every FILTER_EXCLUDE name on every endpoint, including the ones
    without an API row above: no filterable name may be, or pass through,
    an excluded name.
    """
    names = [name for name, _ in REFTAG_MAP[tag].serializer_class.filterable_fields()]
    assert names
    leaked = sorted(name for name in names if is_filter_excluded(name))
    assert not leaked


BARE_EXCLUDED = sorted(name for name in FILTER_EXCLUDE if "__" not in name)
COMPOUND_EXCLUDED = sorted(name for name in FILTER_EXCLUDE if "__" in name)


def test_filter_exclude_shape():
    """
    is_filter_excluded matches compound entries as consecutive segment pairs
    and strips every trailing `_id`; both are only exact while entries look
    like this.
    """
    assert all(name.count("__") == 1 for name in COMPOUND_EXCLUDED)
    assert not any(
        part.endswith("_id") for name in FILTER_EXCLUDE for part in name.split("__")
    )


@pytest.mark.parametrize(
    "shape",
    [
        "{}",
        "{}_id",
        "{}_id_id",
        "{}__in",
        "rel__{}",
        "rel__{}_id",
        "rel__{}_id_id",
        "rel__{}__startswith",
        "rel__{}__iexact",
        "rel__{}_id_id__in",
        "net__{}",
        "fac_set__{}_id",
    ],
)
@pytest.mark.parametrize("name", BARE_EXCLUDED)
def test_relation_route_drops_every_form(name, shape):
    """
    get_relation_filters (the prepare_query route) must emit nothing for any
    translated form of an excluded name, whichever branch handles the key.
    """
    key = shape.format(name)
    flds = [key.split("__")[0]]
    assert get_relation_filters(flds, NetworkSerializer, **{key: ["1"]}) == {}


@pytest.mark.parametrize(
    "key",
    [f"{name}__iexact" for name in COMPOUND_EXCLUDED]
    + [f"{name}__regex" for name in COMPOUND_EXCLUDED]
    + [name.replace("__", "_id__", 1) for name in COMPOUND_EXCLUDED],
)
def test_relation_route_drops_compound_entries(key):
    flds = [key.split("__")[0]]
    assert get_relation_filters(flds, NetworkSerializer, **{key: ["1"]}) == {}


@pytest.mark.parametrize(
    "key,flds",
    [
        ("ix__name", ["ix"]),
        ("ix__name__startswith", ["ix"]),
        ("ix_id", ["ix_id"]),
        ("ixlan_id__in", ["ixlan_id"]),
        ("netixlan__id", ["netixlan"]),
        ("fac__in", ["fac"]),
        ("ixlan__ixf_ixp_member_list_url_visible", ["ixlan"]),
    ],
)
def test_relation_route_keeps_supported_keys(key, flds):
    assert get_relation_filters(flds, NetworkSerializer, **{key: ["1"]})


@pytest.mark.parametrize(
    "key",
    [
        "__".join(["fac_id"] * 50),
        "__".join(["net_set_id_id"] * 2000),
        "ix__" + "_id" * 3000,
        "x" * 8000,
        # within the segment cap, so every segment is normalised
        "ix__a" + "_id" * 2600 + "x",
        "ix__a" + "_id" * 1300 + "x__b" + "_id" * 1300 + "x",
    ],
)
def test_filter_exclusion_check_is_linear(key):
    """
    The check runs on every query-string key, guests included; a long key
    must not cost more than a long key.
    """
    start = time.monotonic()
    is_filter_excluded(key)
    get_relation_filters(["fac_id", "ix"], NetworkSerializer, **{key: ["1"]})
    assert time.monotonic() - start < 0.05


@pytest.mark.parametrize(
    "name",
    ["_id", "id", "x_id", "a_idx_id", "ixf_import_request_user_id_id", "_id" * 3000],
)
def test_filter_name_forms_strip_every_trailing_id(name):
    base = re.sub(r"(_id)+$", "", name) or name
    assert base in filter_name_forms(name)


@pytest.mark.parametrize("client_name", ["guest", "authenticated"])
def test_long_filter_key_is_cheap(filter_data, client_name):
    client = api_clients(filter_data)[client_name]
    key = "__".join(["fac_id"] * 50)
    start = time.monotonic()
    response = client.get("/api/net", {key: "1"})
    assert time.monotonic() - start < 5
    assert response.status_code == 200
    assert {row["id"] for row in response.json()["data"]} == {
        obj.pk for obj in filter_data["net"]
    }
