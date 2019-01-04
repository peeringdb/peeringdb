from django.test import TestCase
from django.contrib.auth import get_user_model
from django.conf import settings


from util import ClientCase
from peeringdb_server import signals, models, serializers
from peeringdb_server import settings as pdb_settings


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


class TestAutoVerifyUser(SettingsCase):
    settings = {"AUTO_VERIFY_USERS":True}

    def test_setting(self):
        user = get_user_model().objects.create_user("user_a", "user_a@localhost", "user_a")
        signals.new_user_to_guests(None, user)
        assert user.is_verified == True
        assert user.status == "ok"


class TestAutoApproveAffiliation(SettingsCase):
    settings = {"AUTO_APPROVE_AFFILIATION":True}

    def test_setting(self):

        org = models.Organization.objects.create(name="Test Org", status="ok")
        net = models.Network.objects.create(name="Test Net", org=org, asn=63311, status="ok")
        user = get_user_model().objects.create_user("user_a", "user_a@localhost", "user_a")
        user_b = get_user_model().objects.create_user("user_b", "user_b@localhost", "user_b")
        user.set_verified()
        user_b.set_verified()

        uoar = models.UserOrgAffiliationRequest.objects.create(user=user, org=org, asn=net.asn)
        assert user.is_org_admin(org) == True

        uoar = models.UserOrgAffiliationRequest.objects.create(user=user, asn=63312)
        net = models.Network.objects.get(asn=63312)
        assert user.is_org_admin(net.org) == True

        uoar = models.UserOrgAffiliationRequest.objects.create(user=user, org_name="Test Org 2")
        org = models.Organization.objects.get(name="Test Org 2")
        assert user.is_org_admin(org) == True

        uoar = models.UserOrgAffiliationRequest.objects.create(user=user_b, asn=63312)
        assert user_b.is_org_admin(net.org) == False
        assert user_b.is_org_member(net.org) == False


