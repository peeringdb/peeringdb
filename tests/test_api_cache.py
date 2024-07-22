import datetime
import json
import os
import re
import tempfile

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django_grainy.models import GroupPermission, UserPermission

import peeringdb_server.management.commands.pdb_api_test as api_test
import peeringdb_server.models as models
from peeringdb_server.api_cache import APICacheLoader

from . import test_api as api_tests
from .util import reset_group_ids


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

    def tearDown(self):
        settings.API_CACHE_ALL_LIMITS = False
        settings.API_CACHE_ENABLED = False
        super().tearDown()


@pytest.mark.django_db
def test_no_api_throttle():
    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    reset_group_ids()

    models.EnvironmentSetting.objects.create(
        setting="API_THROTTLE_REPEATED_REQUEST_ENABLED_IP", value_bool=True
    )
    models.EnvironmentSetting.objects.create(
        setting="API_THROTTLE_REPEATED_REQUEST_THRESHOLD_IP", value_int=1
    )
    models.EnvironmentSetting.objects.create(
        setting="API_THROTTLE_REPEATED_REQUEST_RATE_IP", value_str="1/minute"
    )

    models.EnvironmentSetting.objects.create(
        setting="API_THROTTLE_REPEATED_REQUEST_ENABLED_CIDR", value_bool=True
    )
    models.EnvironmentSetting.objects.create(
        setting="API_THROTTLE_REPEATED_REQUEST_THRESHOLD_CIDR", value_int=1
    )
    models.EnvironmentSetting.objects.create(
        setting="API_THROTTLE_REPEATED_REQUEST_RATE_CIDR", value_str="1/minute"
    )

    models.EnvironmentSetting.objects.create(
        setting="API_THROTTLE_RATE_ANON", value_str="1/minute"
    )

    call_command("pdb_generate_test_data", limit=2, commit=True)
    now = datetime.datetime.now() + datetime.timedelta(days=1)
    call_command("pdb_api_cache", date=now.strftime("%Y%m%d"))
    settings.GENERATING_API_CACHE = False

    for dirpath, dirnames, filenames in os.walk(settings.API_CACHE_ROOT):
        for f in filenames:
            if f in ["log.log"]:
                continue
            path = os.path.join(settings.API_CACHE_ROOT, f)
            with open(path) as fh:
                data_raw = fh.read()
                data = json.loads(data_raw)
                assert not data.get("message")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "api_cache_enabled,api_cache_all_limits,depth,limit,filters,spatial,since,method,viewset_kwargs,file_exists,expected",
    [
        # All conditions met for caching: use cache
        (True, True, 1, 300, False, False, False, "GET", {}, True, True),
        # API cache disabled: don't use cache
        (False, True, 1, 300, False, False, False, "GET", {}, True, False),
        # Low limit and no depth: don't use cache
        (True, False, 0, 200, False, False, False, "GET", {}, True, False),
        # Limit just above the threshold: don't use cache
        (True, True, 0, 251, False, False, False, "GET", {}, True, True),
        # Filters specified: don't use cache
        (True, True, 1, 300, True, False, False, "GET", {}, True, False),
        # Spatial search don't use cache
        (True, True, 1, 300, False, True, False, "GET", {}, True, False),
        # Since parameter specified don't use cache
        (True, True, 1, 300, False, False, True, "GET", {}, True, False),
        # Non-GET method (POST) don't use cache
        (True, True, 1, 300, False, False, False, "POST", {}, True, False),
        # Primary key in viewset kwargs don't use cache
        (True, True, 1, 300, False, False, False, "GET", {"pk": 1}, True, False),
        # Cache file doesn't exist don't use cache
        (True, True, 1, 300, False, False, False, "GET", {}, False, False),
    ],
)
def test_api_cache_loader_qualifies(
    api_cache_enabled,
    api_cache_all_limits,
    depth,
    limit,
    filters,
    spatial,
    since,
    method,
    viewset_kwargs,
    file_exists,
    expected,
    settings,
    mocker,
):
    settings.API_CACHE_ENABLED = api_cache_enabled
    settings.API_CACHE_ALL_LIMITS = api_cache_all_limits

    filters_dict = {"some_filter": "value"} if filters else {}
    qset = models.Organization.objects.all()
    request = type("Request", (), {"method": method, "query_params": {}})
    viewset = type(
        "ViewSet",
        (),
        {"request": request, "model": models.Organization, "kwargs": viewset_kwargs},
    )
    loader = APICacheLoader(viewset, qset, filters_dict)

    loader.depth = depth
    loader.limit = limit
    loader.since = since if since else None
    if spatial:
        setattr(qset, "spatial", True)

    # Mock the os.path.exists function
    mocker.patch("os.path.exists", return_value=file_exists)

    # Mock the path attribute of the loader
    mocker.patch.object(loader, "path", "mocked/cache/path")

    assert loader.qualifies() == expected
