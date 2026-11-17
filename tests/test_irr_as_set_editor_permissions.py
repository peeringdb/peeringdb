"""
#2036: the IRR AS-SET editor script (checkAsSet) must run wherever an irr_as_set
editor is rendered. On the org page that includes the add-network form, which
needs network-create permission on the org rather than org update.
"""

from django.conf import settings
from django.test import Client
from django_grainy.models import UserPermission
from grainy.const import PERM_CREATE, PERM_READ

from peeringdb_server.models import Network, Organization, User
from tests.util import ClientCase

IRR_EDITOR = 'data-edit-name="irr_as_set"'


class TestIrrAsSetEditorOnOrgPage(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org = Organization.objects.create(name="Editor perms org", status="ok")
        cls.net_creator = User.objects.create_user(
            "irr_net_creator", "irr_net_creator@localhost", "irr_net_creator"
        )
        cls.user_group.user_set.add(cls.net_creator)
        UserPermission.objects.create(
            user=cls.net_creator,
            namespace=Network.Grainy.namespace_instance("*", org=cls.org),
            permission=PERM_CREATE | PERM_READ,
        )
        cls.plain = User.objects.create_user(
            "irr_plain", "irr_plain@localhost", "irr_plain"
        )
        cls.user_group.user_set.add(cls.plain)

    def org_page(self, user, next_ui):
        user.opt_flags = settings.USER_OPT_FLAG_UI_NEXT if next_ui else 0
        user.save()
        client = Client()
        client.force_login(user)
        return client.get(f"/org/{self.org.id}").content.decode()

    def test_net_creator_without_org_update_gets_editor_script(self):
        for next_ui in (False, True):
            html = self.org_page(self.net_creator, next_ui)
            assert IRR_EDITOR in html, next_ui
            assert html.count("checkAsSet") == 1, next_ui

    def test_user_without_permissions_gets_no_editor_script(self):
        for next_ui in (False, True):
            html = self.org_page(self.plain, next_ui)
            assert IRR_EDITOR not in html, next_ui
            assert "checkAsSet" not in html, next_ui
