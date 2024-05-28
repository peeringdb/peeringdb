import base64
import json
import os

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase
from django_grainy.models import GroupPermission
from rest_framework.test import APIClient, APIRequestFactory
from twentyc.rpc.client import PermissionDeniedException, RestClient

import peeringdb_server.inet as pdbinet
import peeringdb_server.management.commands.pdb_api_test as api_test
import peeringdb_server.models as models

from .test_api import setup_module, teardown_module
from .util import reset_group_ids


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


class DummyRestClientWithKeyAuth(RestClient):
    """
    An extension of the twentyc.rpc RestClient that goes to the
    django rest framework testing api instead
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.factory = APIRequestFactory()
        self.api_client = APIClient()
        self.useragent = kwargs.get("useragent")

        # Set up with users
        if self.user:
            self.user_inst = models.User.objects.get(username=self.user)
        elif kwargs.get("anon"):
            self.user_inst = None
        else:
            self.user_inst = models.User.objects.get(username="guest")

        # But auth with the Key if it's provided
        if kwargs.get("key") is not None:
            self.key = kwargs.get("key")
            self.api_client.credentials(HTTP_AUTHORIZATION="Api-Key " + self.key)
        elif self.user_inst:
            self.api_client.credentials(
                HTTP_AUTHORIZATION="Basic "
                + base64.b64encode(
                    f"{self.user_inst.username}:{self.user_inst.username}".encode()
                ).decode("utf-8")
            )

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

        res = fnc(url, data, format="json", **self.api_client._credentials)

        assert res.charset == "utf-8"

        return DummyResponse(res.status_code, res.content)


URL = settings.API_URL
VERBOSE = False
USER = {"user": "api_test", "password": "89c8ec05-b897"}
USER_ORG_ADMIN = {
    "user": "api_test_org_admin",
    "password": "89c8ec05-b897",
    "email": "admin@org.com",
}
USER_ORG_MEMBER = {"user": "api_test_org_member", "password": "89c8ec05-b897"}


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
    rest_client = DummyRestClientWithKeyAuth

    # The db will be empty and at least one of the tests
    # requires there to be >100 organizations in the database
    # this tells the test to create them
    create_extra_orgs = 110

    @classmethod
    def setUpTestData(cls):
        # create user and guest group
        guest_group, _ = Group.objects.get_or_create(name="guest")
        user_group, _ = Group.objects.get_or_create(name="user")

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

    def setUp(self):
        super().setUp()
        setup_module(self.__class__)

        # db_user becomes the tester for user key
        api_test_user = models.User.objects.get(username=USER["user"])
        api_key, user_key = models.UserAPIKey.objects.create_key(
            user=api_test_user, name="User api key"
        )
        self.db_user = self.rest_client(URL, verbose=VERBOSE, key=user_key, **USER)
        self.user_key = api_key

        # db_org_admin becomes the tester for rw org api key
        rw_org = models.Organization.objects.get(name="API Test Organization RW")
        rw_api_key, rw_org_key = models.OrganizationAPIKey.objects.create_key(
            name="test key", org=rw_org, email=USER_ORG_ADMIN.get("email")
        )
        self.org_key = rw_api_key

        # Transfer group permissions to org key
        for perm in rw_org.admin_usergroup.grainy_permissions.all():
            rw_api_key.grainy_permissions.add_permission(
                perm.namespace, perm.permission
            )

        self.db_org_admin = self.rest_client(
            URL, verbose=VERBOSE, key=rw_org_key, **USER_ORG_ADMIN
        )

        # db_org_member becomes the tester for r org api key
        r_org = models.Organization.objects.get(name="API Test Organization R")
        r_api_key, r_org_key = models.OrganizationAPIKey.objects.create_key(
            name="test key", org=r_org, email="test@localhost"
        )

        # Transfer group permissions to org key
        for perm in r_org.usergroup.grainy_permissions.all():
            r_api_key.grainy_permissions.add_permission(perm.namespace, perm.permission)

        self.db_org_member = self.rest_client(
            URL, verbose=VERBOSE, key=r_org_key, **USER_ORG_MEMBER
        )

    def tearDown(self):
        teardown_module(
            self.__class__
        )  # Call the teardown_module function from your setup file
        super().tearDown()

    # TESTS WE SKIP OR REWRITE IN API KEY CONTEXT
    def test_org_member_001_POST_ix_with_perms(self):
        """
        We skip this test because there isn't an org admin key equivalent
        of an org-admin user that has access to everything.
        """
        pass

    def test_zz_org_admin_004_DELETE_org(self):
        """
        We rewrite this test because it involves creating an
        additional org key and then using it to delete an org.
        """
        org = models.Organization.objects.create(name="Deletable org", status="ok")
        org_key, key = models.OrganizationAPIKey.objects.create_key(
            name="new key", org=org, email="test@localhost"
        )
        for perm in org.admin_usergroup.grainy_permissions.all():
            org_key.grainy_permissions.add_permission(perm.namespace, perm.permission)
        new_org_admin = self.rest_client(
            URL, verbose=VERBOSE, key=key, **USER_ORG_ADMIN
        )

        self.assert_delete(
            new_org_admin,
            "org",
            # can delete the org we just made
            test_success=org.id,
        )

    def test_org_admin_002_POST_PUT_DELETE_as_set(self):
        """
        The as-set endpoint is readonly, so all of these should
        fail
        """
        data = self.make_data_net(asn=9000900)

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.assert_create(self.db_org_admin, "as_set", data)
        assert "401 Authentication credentials were not provided" in str(excinfo.value)

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_org_admin.update("as_set", {"9000900": "AS-ZZZ"})
        assert "401 Authentication credentials were not provided" in str(excinfo.value)

        net = models.Network.objects.filter(status="ok").first()

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_org_admin.rm("as_set", net.asn)
        assert "401 Authentication credentials were not provided" in str(excinfo.value)

    # TESTS WE ADD FOR ORGANIZATION API KEY
    def test_org_key_admin_002_GET_as_set(self):
        """
        GET requests on the "as_set" endpoint should work with
        any org api key
        """

        data = self.db_org_admin.all("as_set")
        networks = models.Network.objects.filter(status="ok")
        for net in networks:
            self.assertEqual(data[0].get(f"{net.asn}"), net.irr_as_set)

    def test_org_key_member_002_GET_as_set(self):
        """
        GET requests on the "as_set" endpoint should work with
        any org api key
        """

        data = self.db_org_member.all("as_set")
        networks = models.Network.objects.filter(status="ok")
        for net in networks:
            self.assertEqual(data[0].get(f"{net.asn}"), net.irr_as_set)

    def test_org_key_002_inactive(self):
        """
        Test that inactive org keys are blocked
        """

        self.org_key.status = "inactive"
        self.org_key.save()

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_org_admin.all("net")
        assert "Inactive API key" in str(excinfo.value)

    # TESTS WE ADD FOR USER API KEY
    def test_user_key_002_GET_as_set(self):
        """
        GET requests on the "as_set" endpoint should work with
        any user api key
        """

        data = self.db_user.all("as_set")
        networks = models.Network.objects.filter(status="ok")
        for net in networks:
            self.assertEqual(data[0].get(f"{net.asn}"), net.irr_as_set)

    def test_user_key_002_inactive_key(self):
        """
        Test that inactive user keys are blocked
        """

        self.user_key.status = "inactive"
        self.user_key.save()

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_user.all("net")
        assert "Inactive API key" in str(excinfo.value)

    def test_user_key_002_inactive_user(self):
        """
        Test that keys of inactive users are blocked
        """
        self.user_key.user.is_active = False
        self.user_key.user.save()

        with pytest.raises(PermissionDeniedException) as excinfo:
            self.db_user.all("net")
        assert "Inactive API key" in str(excinfo.value)
