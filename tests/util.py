from django.test import TestCase
from django.contrib.auth.models import Group, AnonymousUser
import peeringdb_server.models as models
import django_namespace_perms as nsp


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
