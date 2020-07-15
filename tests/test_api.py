import pytest
import json
import os

from django.test import TestCase
from django.contrib.auth.models import Group
from django.conf import settings

from rest_framework.test import APIRequestFactory, force_authenticate, APIClient
from rest_framework.authtoken.models import Token

import peeringdb_server.models as models
import peeringdb_server.management.commands.pdb_api_test as api_test
from twentyc.rpc.client import RestClient

import django_namespace_perms as nsp
import peeringdb_server.inet as pdbinet

RdapLookup_get_asn = pdbinet.RdapLookup.get_asn


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

    with open(
        os.path.join(os.path.dirname(__file__), "data", "api", "rdap_override.json"),
        "r",
    ) as fh:
        pdbinet.RdapLookup.override_result = json.load(fh)

    def get_asn(self, asn):
        if asn in ASN_RANGE_OVERRIDE:
            return pdbinet.RdapAsn(self.override_result)
        elif pdbinet.asn_is_bogon(asn):
            return RdapLookup_get_asn(self, asn)
        else:
            raise pdbinet.RdapNotFoundError()

    pdbinet.RdapLookup.get_asn = get_asn


def teardown_module(module):
    pdbinet.RdapLookup.get_asn = RdapLookup_get_asn


class DummyResponse(object):
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
        super(DummyRestClient, self).__init__(*args, **kwargs)
        self.factory = APIRequestFactory()
        self.api_client = APIClient()
        self.useragent = kwargs.get("useragent")
        if self.user:
            self.user_inst = models.User.objects.get(username=self.user)
        else:
            self.user_inst = models.User.objects.get(username="guest")
        self.api_client.force_authenticate(self.user_inst)

    def _request(self, typ, id=0, method="GET", params=None, data=None, url=None):
        if not url:
            if id:
                url = "/api/%s/%s" % (typ, id)
            else:
                url = "/api/%s" % (typ,)

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

        guest_user = models.User.objects.create_user(
            "guest", "guest@localhost", "guest"
        )
        guest_group.user_set.add(guest_user)

        nsp.models.GroupPermission.objects.create(
            group=guest_group, namespace="peeringdb.organization", permissions=0x01
        )

        nsp.models.GroupPermission.objects.create(
            group=guest_group,
            namespace="peeringdb.organization.*.internetexchange.*.ixf_ixp_member_list_url.public",
            permissions=0x01,
        )

        nsp.models.GroupPermission.objects.create(
            group=user_group, namespace="peeringdb.organization", permissions=0x01
        )

        nsp.models.GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.{}".format(settings.SUGGEST_ENTITY_ORG),
            permissions=0x04,
        )

        nsp.models.GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.*.network.*.poc_set.users",
            permissions=0x01,
        )

        nsp.models.GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.*.internetexchange.*.ixf_ixp_member_list_url.public",
            permissions=0x01,
        )

        nsp.models.GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.*.internetexchange.*.ixf_ixp_member_list_url.users",
            permissions=0x01,
        )

        # prepare api test data
        cls.prepare()
