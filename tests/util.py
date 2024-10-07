import json
import os
from importlib import import_module

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.sessions.models import Session
from django.middleware.csrf import CSRF_SESSION_KEY, _get_new_csrf_string
from django.test import TestCase
from django_grainy.models import GroupPermission, UserPermission

import peeringdb_server.models as models
from peeringdb_server import settings as pdb_settings


class ClientCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # create user and guest group

        cls.guest_group = guest_group = Group.objects.create(
            name="guest", id=settings.GUEST_GROUP_ID
        )
        cls.user_group = user_group = Group.objects.create(
            name="user", id=settings.USER_GROUP_ID
        )

        settings.USER_GROUP_ID = cls.user_group.id
        settings.GUEST_GROUP_ID = cls.guest_group.id

        cls.guest_user = models.User.objects.create_user(
            username="guest", email="guest@localhost", password="guest"
        )
        models.EmailAddress.objects.create(user=cls.guest_user, email="guest@localhost")

        cls.guest_group.user_set.add(cls.guest_user)

        GroupPermission.objects.create(
            group=guest_group, namespace="peeringdb.organization", permission=0x01
        )

        GroupPermission.objects.create(
            group=user_group, namespace="peeringdb.organization", permission=0x01
        )

        GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.*.network.*.poc_set.users",
            permission=0x01,
        )

        GroupPermission.objects.create(
            group=guest_group,
            namespace="peeringdb.organization.*.network.*.poc_set.public",
            permission=0x01,
        )


class SettingsCase(ClientCase):
    """
    Since we read settings from peeringdb_server.settings
    we can't use the `settings` fixture from pytest-django

    This class instead does something similar for peeringdb_server.settings,
    where it will override settings specified and then reset after test case
    is finished
    """

    settings = {}

    @classmethod
    def setUp(cls):
        cls._restore = {}
        for k, v in list(cls.settings.items()):
            cls._restore[k] = getattr(pdb_settings, k, getattr(settings, k, None))
            setattr(pdb_settings, k, v)
            setattr(settings, k, v)

    @classmethod
    def tearDown(cls):
        for k, v in list(cls._restore.items()):
            setattr(pdb_settings, k, v)
            setattr(settings, k, v)


def reset_group_ids():
    """
    Guest and user groups will get recreated for each tests,
    however mysql sequential ids wont be reset between tests.

    Tests that require USER_GROUP_ID and GUEST_GROUP_ID to
    point to to correct groups should call this function
    to make sure the settings are updated
    """

    try:
        settings.USER_GROUP_ID = Group.objects.get(name="user").id
    except Group.DoesNotExist:
        Group.objects.create(name="user", id=settings.USER_GROUP_ID)

    try:
        settings.GUEST_GROUP_ID = Group.objects.get(name="guest").id
    except Group.DoesNotExist:
        Group.objects.create(name="guest", id=settings.GUEST_GROUP_ID)


def override_group_id():
    from django.test import override_settings

    return override_settings(
        USER_GROUP_ID=Group.objects.get(name="user").id,
        GUEST_GROUP_ID=Group.objects.get(name="guest").id,
    )


# For IXF member tests
def setup_test_data(filename):
    json_data = {}
    entities = {}

    with open(
        os.path.join(
            os.path.dirname(__file__),
            "data",
            "json_members_list",
            f"{filename}.json",
        ),
    ) as fh:
        json_data = json.load(fh)

    return json_data


def mock_csrf_session(request):
    engine = import_module(settings.SESSION_ENGINE)
    request.session = engine.SessionStore("deadbeef")
    request.session[CSRF_SESSION_KEY] = _get_new_csrf_string()
    request._dont_enforce_csrf_checks = True
