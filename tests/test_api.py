import base64
import json
import os

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase
from django_grainy.models import GroupPermission, UserPermission
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from twentyc.rpc.client import RestClient

import peeringdb_server.inet as pdbinet
import peeringdb_server.management.commands.pdb_api_test as api_test
import peeringdb_server.models as models

from .util import reset_group_ids

RdapLookup_get_asn = pdbinet.RdapLookup.get_asn
RdapLookup_get_ip = pdbinet.RdapLookup.get_ip


def setup_module(module):
    # RDAP LOOKUP OVERRIDE
    # Since we are working with fake ASNs throughout the api tests
    # we need to make sure the RdapLookup client can fake results
    # for us

    # These ASNs will be seen as valid and a prepared json object
    # will be returned for them (data/api/rdap_override.json)
    #
    # ALL ASNs outside of this range will raise a RdapNotFoundError
    ASN_RANGE_OVERRIDE = list(range(9000000, 9000999))
    PREFIX_RANGE_OVERRIDE = [
        f"206.41.{ip_suffix}.0/24" for ip_suffix in range(110, 226)
    ]

    with open(
        os.path.join(os.path.dirname(__file__), "data", "api", "rdap_override.json"),
    ) as fh:
        pdbinet.RdapLookup.override_result = json.load(fh)

    with open(
        os.path.join(
            os.path.dirname(__file__), "data", "api", "rdap_prefix_override.json"
        ),
    ) as fh:
        pdbinet.RdapLookup.override_prefix_result = json.load(fh)

    def get_asn(self, asn):
        if asn in ASN_RANGE_OVERRIDE:
            return pdbinet.RdapAsn(self.override_result)
        elif pdbinet.asn_is_bogon(asn):
            return RdapLookup_get_asn(self, asn)
        else:
            raise pdbinet.RdapNotFoundError()

    def get_ip(self, prefix):
        if prefix in PREFIX_RANGE_OVERRIDE:
            return pdbinet.RdapNetwork(self.override_prefix_result)
        else:
            raise pdbinet.RdapNotFoundError()

    pdbinet.RdapLookup.get_ip = get_ip
    pdbinet.RdapLookup.get_asn = get_asn


def teardown_module(module):
    pdbinet.RdapLookup.get_asn = RdapLookup_get_asn
    pdbinet.RdapLookup.get_ip = RdapLookup_get_ip


class APIClientWithIdenity(APIClient):
    def __init__(self, identity, **kwargs):
        super().__init__(**kwargs)

        if identity:
            credentials = f"{identity.username}:{identity.username}"
            base64_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
                "utf-8"
            )
            self.credentials(HTTP_AUTHORIZATION=f"Basic {base64_credentials}")


class DummyResponse:
    """
    Simulate requests response object
    """

    def __init__(self, status_code, content, headers={}):
        self.status_code = status_code
        self.content = content
        self.headers = headers

    @property
    def data(self):
        return json.loads(self.content)

    def read(self, *args, **kwargs):
        return self.content

    def getheader(self, name):
        return self.headers.get(name)

    def json(self):
        return self.data


class DummyRestClient(RestClient):
    """
    An extension of the twentyc.rpc RestClient that goes to the
    django rest framework testing api instead
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.factory = APIRequestFactory()
        self.useragent = kwargs.get("useragent")
        if self.user:
            self.user_inst = models.User.objects.get(username=self.user)
        elif kwargs.get("anon"):
            self.user_inst = None
        else:
            self.user_inst = models.User.objects.get(username="guest")

        self.api_client = APIClientWithIdenity(self.user_inst)

    def _request(self, typ, id=0, method="GET", params=None, data=None, url=None):
        if not url:
            if id:
                url = f"/api/{typ}/{id}"
            else:
                url = f"/api/{typ}"

        fnc = getattr(self.api_client, method.lower())
        if not data:
            data = {}
        if params:
            data.update(**params)
        res = fnc(url, data, format="json")

        assert res.charset == "utf-8"

        return DummyResponse(res.status_code, res.content)


class APITests(TestCase, api_test.TestJSON, api_test.Command):
    """
    API tests

    You can find the logic / definition of those tests in
    peeringdb_server.manangement.commands.pdb_api_test

    This simply extends the command and testcase defined for it
    but uses a special RestClient that sends requests to the
    rest_framework testing api instead of a live server.
    """

    # we want to use this rest-client for our requests
    rest_client = DummyRestClient

    # The db will be empty and at least one of the tests
    # requires there to be >100 organizations in the database
    # this tells the test to create them
    create_extra_orgs = 110

    @classmethod
    def setUpTestData(cls):
        # create user and guest group
        guest_group = Group.objects.create(name="guest")
        user_group = Group.objects.create(name="user")
        reset_group_ids()
        guest_user = models.User.objects.create_user(
            "guest", "guest@localhost", "guest"
        )
        guest_group.user_set.add(guest_user)

        GroupPermission.objects.create(
            group=guest_group, namespace="peeringdb.organization", permission=0x01
        )

        GroupPermission.objects.create(
            group=guest_group,
            namespace="peeringdb.organization.*.internetexchange.*.ixf_ixp_member_list_url.public",
            permission=0x01,
        )

        GroupPermission.objects.create(
            group=user_group, namespace="peeringdb.organization", permission=0x01
        )

        GroupPermission.objects.create(
            group=user_group,
            namespace=f"peeringdb.organization.{settings.SUGGEST_ENTITY_ORG}",
            permission=0x04,
        )

        GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.*.network.*.poc_set.users",
            permission=0x01,
        )

        GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.*.internetexchange.*.ixf_ixp_member_list_url.public",
            permission=0x01,
        )

        GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.*.internetexchange.*.ixf_ixp_member_list_url.users",
            permission=0x01,
        )

        # prepare api test data
        cls.prepare()
