import datetime
import os
import tempfile

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django_grainy.models import GroupPermission

import peeringdb_server.management.commands.pdb_api_test as api_test
import peeringdb_server.models as models
from tests.test_api_keys import (
    DummyRestClientWithKeyAuth,
    setup_module,
    teardown_module,
)
from tests.util import reset_group_ids

URL = settings.API_URL
VERBOSE = False
USER = {"user": "api_test", "password": "89c8ec05-b897"}
USER_ORG_ADMIN = {
    "user": "api_test_org_admin",
    "password": "89c8ec05-b897",
    "email": "admin@org.com",
}
USER_ORG_MEMBER = {"user": "api_test_org_member", "password": "89c8ec05-b897"}
USER_CRUD = {
    "delete": {"user": "api_test_crud_delete", "password": "api_test_crud_delete"},
    "update": {"user": "api_test_crud_update", "password": "api_test_crud_update"},
    "create": {"user": "api_test_crud_create", "password": "api_test_crud_create"},
}


class APICacheTests(TestCase, api_test.TestJSON, api_test.Command):
    """
    API cache tests with API key authentication

    Runs the API test suite after generating cache files and enabling API cache.
    All db clients use API keys to ensure compatibility with MFA enforcement.

    You can find the logic / definition of those tests in
    peeringdb_server.manangement.commands.pdb_api_test
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

        settings.API_CACHE_ROOT = tempfile.mkdtemp()
        settings.API_CACHE_LOG = os.path.join(settings.API_CACHE_ROOT, "log.log")
        super_user = models.User.objects.create_user(
            "admin", "admin@localhost", "admin"
        )
        super_user.is_superuser = True
        super_user.is_staff = True
        super_user.save()

        # generate cache files
        now = datetime.datetime.now() + datetime.timedelta(days=1)
        call_command("pdb_api_cache", date=now.strftime("%Y%m%d"))
        settings.GENERATING_API_CACHE = False

    def setUp(self):
        settings.API_CACHE_ALL_LIMITS = True
        settings.API_CACHE_ENABLED = True
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

        # db_guest uses API key from guest user
        guest_user = models.User.objects.get(username="guest")
        guest_api_key, guest_key = models.UserAPIKey.objects.create_key(
            user=guest_user, name="Guest api key"
        )
        self.db_guest = self.rest_client(URL, verbose=VERBOSE, key=guest_key)

        for p, specs in list(USER_CRUD.items()):
            crud_user = models.User.objects.get(username=specs["user"])
            crud_api_key, crud_key = models.UserAPIKey.objects.create_key(
                user=crud_user, name=f"{specs['user']} api key"
            )
            setattr(
                self,
                f"db_crud_{p}",
                self.rest_client(URL, verbose=VERBOSE, key=crud_key, **specs),
            )

    def tearDown(self):
        settings.API_CACHE_ALL_LIMITS = False
        settings.API_CACHE_ENABLED = False
        teardown_module(self.__class__)
        super().tearDown()

    # TESTS SKIPPED OR REWRITTEN IN API KEY CONTEXT
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
        import pytest
        from twentyc.rpc.client import PermissionDeniedException

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
