from django.test import TestCase
from django.contrib.auth.models import Group, AnonymousUser
from django.conf import settings
import peeringdb_server.models as models
import django_namespace_perms as nsp
from peeringdb_server import settings as pdb_settings


class ClientCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # create user and guest group

        guest_group = Group.objects.create(name="guest")
        user_group = Group.objects.create(name="user")

        cls.guest_user = models.User.objects.create_user(
            "guest", "guest@localhost", "guest")
        guest_group.user_set.add(cls.guest_user)

        nsp.models.GroupPermission.objects.create(
            group=guest_group, namespace="peeringdb.organization",
            permissions=0x01)

        nsp.models.GroupPermission.objects.create(
            group=user_group, namespace="peeringdb.organization",
            permissions=0x01)

        nsp.models.GroupPermission.objects.create(
            group=user_group,
            namespace="peeringdb.organization.*.network.*.poc_set.users",
            permissions=0x01)

        nsp.models.GroupPermission.objects.create(
            group=guest_group,
            namespace="peeringdb.organization.*.network.*.poc_set.public",
            permissions=0x01)


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
        for k,v in cls.settings.items():
            cls._restore[k] = getattr(pdb_settings, k)
            setattr(pdb_settings, k, v)

    @classmethod
    def tearDown(cls):
        for k,v in cls._restore.items():
            setattr(pdb_settings, k, v)


