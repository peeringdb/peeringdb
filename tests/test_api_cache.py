import pytest
import json
import tempfile
import os
import datetime
import re

from django.test import TestCase
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.conf import settings

import peeringdb_server.models as models
import peeringdb_server.management.commands.pdb_api_test as api_test

from . import test_api as api_tests
import django_namespace_perms as nsp


def setup_module(module):
    api_tests.setup_module(module)


def teardown_module(module):
    api_tests.teardown_module(module)


class APICacheTests(TestCase, api_test.TestJSON, api_test.Command):
    """
    Runs the api test after generating cache files and enabling
    api cache

    You can find the logic / definition of those tests in
    peeringdb_server.manangement.commands.pdb_api_test

    This simply extends the command and testcase defined for it
    but uses a special RestClient that sends requests to the
    rest_framework testing api instead of a live server.
    """

    # we want to use this rest-client for our requests
    rest_client = api_tests.DummyRestClient

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
            namespace=f"peeringdb.organization.{settings.SUGGEST_ENTITY_ORG}",
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

    def setUp(self):
        settings.API_CACHE_ALL_LIMITS = True
        settings.API_CACHE_ENABLED = True
        super().setUp()

    def tearDown(self):
        settings.API_CACHE_ALL_LIMITS = False
        settings.API_CACHE_ENABLED = False
        super().tearDown()
