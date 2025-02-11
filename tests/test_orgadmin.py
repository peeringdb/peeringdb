import json
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice
from grainy.const import *

import peeringdb_server.models as models
import peeringdb_server.org_admin_views as org_admin
import peeringdb_server.views as views
from tests.util import mock_csrf_session, override_group_id


class OrgAdminTests(TestCase):
    """
    Test organization administration functionality, such as
    org admins permissioning users and approving or denying
    affiliation requests
    """

    entities = ["ix", "net", "fac", "carrier"]

    @classmethod
    def setUpTestData(cls):
        # create user and guest group
        cls.guest_group = Group.objects.create(name="guest", id=settings.GUEST_GROUP_ID)
        cls.user_group = Group.objects.create(name="user", id=settings.USER_GROUP_ID)

        settings.USER_GROUP_ID = cls.user_group.id
        settings.GUEST_GROUP_ID = cls.guest_group.id

        # create test users
        for name in [
            "org_admin",
            "user_a",
            "user_b",
            "user_c",
            "user_d",
            "user_e",
            "user_f",
        ]:
            setattr(
                cls,
                name,
                models.User.objects.create_user(name, "%s@localhost" % name, name),
            )
            getattr(cls, name).set_password(name)

        # create test org
        cls.org = models.Organization.objects.create(name="Test org", status="ok")
        cls.org_other = models.Organization.objects.create(
            name="Test org other", status="ok"
        )

        # create test entities
        for tag in cls.entities:
            kwargs = {"name": "Test %s" % tag, "status": "ok", "org": cls.org}
            if tag == "net":
                kwargs.update(asn=1)
            setattr(cls, tag, models.REFTAG_MAP[tag].objects.create(**kwargs))

        # add org_admin user to org as admin
        cls.org.admin_usergroup.user_set.add(cls.org_admin)

        # add user_a user to org as member
        cls.org.usergroup.user_set.add(cls.user_a)
        cls.org_other.usergroup.user_set.add(cls.user_b)

    def setUp(self):
        self.factory = RequestFactory()

    def test_users(self):
        """
        Tests the result of org_admin_views.users
        """
        # test #1 - return a json response with the user we added to the org's member
        # usergroup
        request = self.factory.get("/org-admin/users?org_id=%d" % (self.org.id))
        request.user = self.org_admin

        resp = json.loads(org_admin.users(request).content)

        self.assertEqual(resp["status"], "ok")
        self.assertEqual(
            resp["users"],
            [
                {
                    "id": self.user_a.id,
                    "name": "%s <%s, %s>"
                    % (self.user_a.full_name, self.user_a.email, self.user_a.username),
                }
            ],
        )

        # test #2 - return 403 response when trying to access the org where org_admin
        # is not administrator
        request = self.factory.get("/org-admin/users?org_id=%d" % (self.org_other.id))
        request.user = self.org_admin

        resp = org_admin.users(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

    def test_user_options(self):
        # test updating user options

        assert self.org.restrict_user_emails is False
        assert self.org.email_domains_list == []
        assert self.org.periodic_reauth is False
        assert self.org.periodic_reauth_period == "3m"

        url = reverse("org-admin-user-options")

        request = self.factory.post(
            url,
            data={
                "org_id": self.org.id,
                "restrict_user_emails": True,
                "email_domains": "domain.com\nexample.com",
                "periodic_reauth": True,
                "periodic_reauth_period": "1m",
            },
        )
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.update_user_options(request)
        self.assertEqual(json.loads(resp.content).get("status"), "ok")

        self.org.refresh_from_db()

        assert self.org.restrict_user_emails is True
        assert self.org.email_domains_list == ["domain.com", "example.com"]
        assert self.org.periodic_reauth is True
        assert self.org.periodic_reauth_period == "1m"

        # test org admin required

        request = self.factory.post(
            url,
            data={
                "org_id": self.org_other.id,
                "restrict_user_emails": False,
                "periodic_reauth": False,
            },
        )
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.update_user_options(request)

        assert resp.status_code == 403
        assert json.loads(resp.content) == {}

        # test validation

        request = self.factory.post(
            url,
            data={
                "org_id": self.org.id,
                "email_domains": "invalid",
                "periodic_reauth_period": "1z",
            },
        )
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.update_user_options(request)
        assert resp.status_code == 400
        assert "email_domains" in json.loads(resp.content)
        assert "periodic_reauth_period" in json.loads(resp.content)

    def test_user_email_restriction_highlight(self):
        self.org.restrict_user_emails = True
        self.org.email_domains = "example.com"
        self.org.save()

        request = self.factory.get(f"/org/{self.org.id}")
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = views.view_organization(request, self.org.id)

        assert "Email address requirements not met" in resp.content.decode("utf-8")

        self.org.restrict_user_emails = False
        self.org.save()

        resp = views.view_organization(request, self.org.id)

        assert "Email address requirements not met" not in resp.content.decode("utf-8")

    def test_load_all_user_permissions(self):
        """
        Test the result of org_admin_views.load_all_user_permissions
        """

        uid = self.user_a.id
        perms = {
            uid: {
                "perms": {"net.%d" % self.net.id: 0x01, "fac": 0x03},
                "id": self.user_a.id,
                "name": "%s <%s> %s"
                % (self.user_a.full_name, self.user_a.email, self.user_a.username),
            }
        }

        org_admin.save_user_permissions(self.org, self.user_a, perms[uid]["perms"])

        perms_all = org_admin.load_all_user_permissions(self.org)

        self.assertEqual(perms_all, perms)

    def test_user_permissions_update_remove(self):
        """
        Test the result of org_admin_views.user_permissions_update
        Test the result of org_admin_views.user_permissions_remove
        """

        # Test #1 - test updating a user a's permission to the org
        url = "/org-admin/user_permissions/update?org_id=%d&user_id=%d" % (
            self.org.id,
            self.user_a.id,
        )
        request = self.factory.post(
            url, data={"entity": "net.%d" % self.net.id, "perms": 0x03}
        )
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.user_permission_update(request)
        self.assertEqual(json.loads(resp.content).get("status"), "ok")

        # test that the perms we just updated saved correctly
        uperms, perms = org_admin.load_user_permissions(self.org, self.user_a)
        self.assertEqual(perms, {"net.%d" % self.net.id: 0x03})

        # Test #2 - should not be allowed to update user b's perms as he is not a member of
        # the org

        url = "/org-admin/user_permissions/update?org_id=%d&user_id=%d" % (
            self.org.id,
            self.user_b.id,
        )
        request = self.factory.post(
            url, data={"entity": "net.%d" % self.net.id, "perms": 0x03}
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.user_permission_update(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

        # Test #3 - should not be allowed to update user b's perms because we are not
        # the admin of his org

        url = "/org-admin/user_permissions/update?org_id=%d&user_id=%d" % (
            self.org_other.id,
            self.user_b.id,
        )
        request = self.factory.post(
            url, data={"entity": "net.%d" % self.net.id, "perms": 0x03}
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.user_permission_update(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

        # Test #4 - remove the permissions we just added
        url = "/org-admin/user_permissions/remove?org_id=%d&user_id=%d" % (
            self.org.id,
            self.user_a.id,
        )
        request = self.factory.post(url, data={"entity": "net.%d" % self.net.id})
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.user_permission_remove(request)
        self.assertEqual(json.loads(resp.content).get("status"), "ok")

        # test that the perms we just removed saved correctly
        uperms, perms = org_admin.load_user_permissions(self.org, self.user_a)
        self.assertEqual(perms, {})

        # Test #5 - should not be allowed remove user b's permissions as he
        # is not a member of the org
        url = "/org-admin/user_permissions/remove?org_id=%d&user_id=%d" % (
            self.org.id,
            self.user_b.id,
        )
        request = self.factory.post(url, data={"entity": "net.%d" % self.net.id})
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.user_permission_remove(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

        # Test #6 - should not be allowed to remove user b's permissions as we
        # are not the admin of his org
        url = "/org-admin/user_permissions/remove?org_id=%d&user_id=%d" % (
            self.org_other.id,
            self.user_b.id,
        )
        request = self.factory.post(url, data={"entity": "net.%d" % self.net.id})
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.user_permission_remove(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

        # Test #7 - should not be allowed to manage an admins permissions (#1157)
        url = "/org-admin/user_permissions/update?org_id=%d&user_id=%d" % (
            self.org.id,
            self.org_admin.id,
        )
        request = self.factory.post(
            url, data={"entity": "net.%d" % self.net.id, "perms": 0x03}
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.user_permission_update(request)
        assert resp.status_code == 400
        assert json.loads(resp.content).get("non_field_errors") == [
            "Cannot manage permissions for organization admins"
        ]

    def test_user_permissions(self):
        """
        Test the result of org_admin_views.user_permissions
        Test org_admin_views.save_user_permissions
        Test org_admin_views.load_user_permissions
        """

        # Test #1 - test user a's permission to the org
        request = self.factory.get(
            "/org-admin/user_permissions?org_id=%d" % (self.org.id)
        )
        request.user = self.org_admin

        uid = str(self.user_a.id)

        # we  make some temporary perms for user_a
        perms = {uid: {"net.%d" % self.net.id: 0x01, "fac": 0x03}}

        org_admin.save_user_permissions(self.org, self.user_a, perms[uid])

        resp = json.loads(org_admin.user_permissions(request).content)

        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["user_permissions"], perms)

        # Test #2 - clear the perms we just made for this test
        org_admin.save_user_permissions(self.org, self.user_a, {})

        resp = json.loads(org_admin.user_permissions(request).content)
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["user_permissions"], {uid: {}})

        # Test #5 - no permissions to org

        request = self.factory.get(
            "/org-admin/user_permissions?org_id=%d" % (self.org_other.id)
        )
        request.user = self.org_admin

        resp = org_admin.user_permissions(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

    def test_org_admin_tools(self):
        """
        Test that users with create / delete permissions have access to the tools
        on the org management page
        """

        for tag in ["fac", "net", "ix"]:
            org_admin.save_user_permissions(self.org, self.user_a, {tag: PERM_CREATE})
            c = Client()
            c.login(username=self.user_a.username, password="user_a")
            resp = c.get("/org/%d" % self.org.id, follow=True)
            print(resp)

            for _tag in ["fac", "net", "ix"]:
                if _tag != tag:
                    assert f"#add_{_tag}" not in resp.content.decode()
            assert f"#add_{tag}" in resp.content.decode()

    def test_manage_user_delete(self):
        """
        Test the result of org_admin_views.manager_user_delete
        """

        self.org.admin_usergroup.user_set.add(self.user_e)
        self.org.usergroup.user_set.add(self.user_f)

        # make sure that user f is currently member and not admin
        self.assertEqual(self.user_f.is_org_member(self.org), True)
        self.assertEqual(self.user_f.is_org_admin(self.org), False)
        self.assertEqual(self.user_e.is_org_member(self.org), False)
        self.assertEqual(self.user_e.is_org_admin(self.org), True)

        # test #1 - remove user f (member) from org
        request = self.factory.post(
            "/org-admin/manage_user/delete",
            {"org_id": self.org.id, "user_id": self.user_f.id},
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.manage_user_delete(request)
        self.assertEqual(json.loads(resp.content), {"status": "ok"})

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_f.is_org_member(self.org), False)
        self.assertEqual(self.user_f.is_org_admin(self.org), False)

        # test #2 - remove user e (admin) from org
        request = self.factory.post(
            "/org-admin/manage_user/delete",
            {"org_id": self.org.id, "user_id": self.user_e.id},
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.manage_user_delete(request)
        self.assertEqual(json.loads(resp.content), {"status": "ok"})

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_e.is_org_member(self.org), False)
        self.assertEqual(self.user_e.is_org_admin(self.org), False)

        # test #3 - fail on user that is not currently in org
        request = self.factory.post(
            "/org-admin/manage_user/delete",
            {"org_id": self.org.id, "user_id": self.user_d.id},
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.manage_user_delete(request)
        self.assertEqual(resp.status_code, 403)

        # test #3 - fail on org that you are not an admin of
        request = self.factory.post(
            "/org-admin/manage_user/delete",
            {"org_id": self.org_other.id, "user_id": self.user_d.id},
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.manage_user_delete(request)
        self.assertEqual(resp.status_code, 403)

    def test_manage_user_update(self):
        """
        Test the result of org_admin_views.manage_user_update
        """

        # make sure that user a is currently member and not admin
        self.assertEqual(self.user_a.is_org_member(self.org), True)
        self.assertEqual(self.user_a.is_org_admin(self.org), False)

        # test #1 - move user a to admin group
        request = self.factory.post(
            "/org-admin/manage_user/update",
            {"org_id": self.org.id, "user_id": self.user_a.id, "group": "admin"},
        )
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.manage_user_update(request)
        self.assertEqual(json.loads(resp.content), {"status": "ok"})

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.is_org_member(self.org), False)
        self.assertEqual(self.user_a.is_org_admin(self.org), True)

        # test #2 move back to member group
        request = self.factory.post(
            "/org-admin/manage_user/update",
            {"org_id": self.org.id, "user_id": self.user_a.id, "group": "member"},
        )
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.manage_user_update(request)
        self.assertEqual(json.loads(resp.content), {"status": "ok"})

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.is_org_member(self.org), True)
        self.assertEqual(self.user_a.is_org_admin(self.org), False)

        # test #3 - fail on user that is not currently in org
        request = self.factory.post(
            "/org-admin/manage_user/update",
            {"org_id": self.org.id, "user_id": self.user_d.id, "group": "member"},
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.manage_user_update(request)
        self.assertEqual(resp.status_code, 403)

        # test #3 - fail on org that you are not an admin of
        request = self.factory.post(
            "/org-admin/manage_user/update",
            {"org_id": self.org_other.id, "user_id": self.user_d.id, "group": "admin"},
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.manage_user_update(request)
        self.assertEqual(resp.status_code, 403)

    def test_permissions(self):
        """
        Test the result of org_admin_views.permissions
        """

        # Test #1 - retrieve permissioning ids for org

        request = self.factory.get("/org-admin/permissions?org_id=%d" % self.org.id)
        request.user = self.org_admin
        resp = json.loads(org_admin.permissions(request).content)

        self.assertEqual(resp["status"], "ok")

        ids = {r["id"]: r["name"] for r in resp["permissions"]}
        self.assertEqual(len(ids), 11)
        self.assertIn("org.%d" % self.org.id, ids)
        self.assertIn("ix.%d" % self.ix.id, ids)
        self.assertIn("net.%d" % self.net.id, ids)
        self.assertIn("fac.%d" % self.fac.id, ids)
        self.assertIn("carrier.%d" % self.carrier.id, ids)

        # Test #2 - cannot retrieve ids for other org as we are not admin
        request = self.factory.get(
            "/org-admin/permissions?org_id=%d" % self.org_other.id
        )
        request.user = self.org_admin
        resp = org_admin.permissions(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

    def test_permission_ids(self):
        """
        Test the result of org_admin_views.permission_ids
        """

        ids = org_admin.permission_ids(self.org)
        self.assertEqual(type(ids), dict)
        self.assertEqual(len(ids), 11)
        self.assertIn("org.%d" % self.org.id, ids)
        self.assertIn("ix.%d" % self.ix.id, ids)
        self.assertIn("net.%d" % self.net.id, ids)
        self.assertIn("fac.%d" % self.fac.id, ids)
        self.assertIn("carrier.%d" % self.carrier.id, ids)

    def test_extract_permission_id(self):
        """
        Test the result of org_admin_views.extract_permission_id
        """

        # extract permission ids to here
        dest = {}

        # prepare source dict with nsp namespaces
        source = {
            self.net.grainy_namespace: 0x01,
            self.ix.grainy_namespace: 0x01,
            self.fac.grainy_namespace: 0x01,
        }

        # extract ids

        org_admin.extract_permission_id(source, dest, self.net, self.org)
        org_admin.extract_permission_id(source, dest, self.ix, self.org)
        org_admin.extract_permission_id(source, dest, self.fac, self.org)

        self.assertEqual(
            {
                "net.%d" % self.net.id: 0x01,
                "ix.%d" % self.ix.id: 0x01,
                "fac.%d" % self.fac.id: 0x01,
            },
            dest,
        )

        # test with just the models

        # extract permission ids to here
        dest = {}

        # prepare source dict with nsp namespaces
        source = {
            self.net.Grainy.namespace_instance("*", org=self.net.org).strip(".*"): 0x01,
            self.fac.Grainy.namespace_instance("*", org=self.net.org).strip(".*"): 0x03,
            self.ix.Grainy.namespace_instance("*", org=self.net.org).strip(".*"): 0x01,
        }

        # extract ids
        org_admin.extract_permission_id(source, dest, models.Network, self.org)
        org_admin.extract_permission_id(source, dest, models.InternetExchange, self.org)
        org_admin.extract_permission_id(source, dest, models.Facility, self.org)

        self.assertEqual({"net": 0x01, "fac": 0x03, "ix": 0x01}, dest)

    def test_uoar_listing(self):
        """
        Test that affilation requests are listed correctly
        """

        # create a user-organization-affiliation-request for user c
        uoar = models.UserOrgAffiliationRequest.objects.create(
            user=self.user_c, asn=1, status="pending"
        )

        request = self.factory.get(f"/org/{uoar.org.id}/")
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = views.view_organization(request, uoar.org.id)

        assert "user_c@localhost" in resp.content.decode("utf-8")

    def test_uoar_approve(self):
        """
        Test approving of a user-org-affiliation-request
        org_admin_views.uoar_approve
        """

        # create a uoar for user c
        uoar = models.UserOrgAffiliationRequest.objects.create(
            user=self.user_c, asn=1, status="pending"
        )

        # test that org id was properly derived from network asn
        self.assertEqual(uoar.org.id, self.org.id)

        # set org.require_2fa to True
        org = self.org
        org.require_2fa = True
        org.save()

        # test approval for user without 2FA request affiliation in organization that require 2FA
        with override_group_id():
            request = self.factory.post(
                "/org-admin/uoar/approve?org_id=%d" % self.org.id, data={"id": uoar.id}
            )
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = org_admin.uoar_approve(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            json.loads(resp.content),
            {
                "message": "User   requests affiliation with Organization Test org but has "
                "not enabled 2FA. Org Test org does not allow users to affiliate "
                "unless they have enabled 2FA on their account. You will be able "
                "to approve an affiliation request from User  , and assign "
                "permissions to them, when they have enabled 2FA."
            },
        )

        # create user TOTP devices
        totpdevice = TOTPDevice.objects.create(user=self.user_c, name="default")
        totpdevice.save()

        admin = models.User.objects.create(
            username="admintest",
            first_name="test",
            last_name="admin",
        )
        self.org.admin_usergroup.user_set.add(admin)

        with patch.object(models.User, "email_user") as mock_email_user:
            # test approval
            request.user = admin
            resp = json.loads(org_admin.uoar_approve(request).content)
            self.assertEqual(
                {
                    "status": "ok",
                    "full_name": self.user_c.full_name,
                    "id": self.user_c.id,
                    "email": self.user_c.email,
                },
                resp,
            )

            mock_email_user.assert_called_once()
            # get the email content
            email_subject, email_body = mock_email_user.call_args[0][0:2]
            self.assertIn(admin.full_name, email_body)

        # check that user is now a member of the org
        self.assertEqual(
            self.org.usergroup.user_set.filter(id=self.user_c.id).exists(), True
        )

        # check that the UOAR is gone
        self.assertEqual(
            models.UserOrgAffiliationRequest.objects.filter(id=uoar.id).exists(), False
        )

        # test: we shouldnt be allowed to approve uoar's for the org we are not
        # admins of

        with override_group_id():
            request = self.factory.post(
                "/org-admin/uoar/approve?org_id=%d" % self.org_other.id,
                data={"id": uoar.id},
            )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.uoar_approve(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

        # test: trying to approve an uoar that doesn't belong to the org shouldn't
        # be allowed

        uoar_b = models.UserOrgAffiliationRequest.objects.create(
            user=self.user_d, asn=22, status="pending"
        )

        with override_group_id():
            request = self.factory.post(
                "/org-admin/uoar/approve?org_id=%d" % self.org.id,
                data={"id": uoar_b.id},
            )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.uoar_approve(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

        uoar_b.delete()

    def test_handle_2fa(self):
        """
        Test handling a user turning off 2FA while they are in an organization that requires it
        views.handle_2fa
        """
        org = self.org
        org_other = self.org_other
        member = self.user_c
        org.usergroup.user_set.add(self.user_c)
        actions = ["leave", "disable", "drop"]
        settings.CSRF_USE_SESSIONS = False

        # check if request.user is not admin of the organization and member is not the member of the organization
        request = self.factory.get(
            f"/org_admin/handle-2fa?org={org_other.id}&member={member.id}&action={actions[0]}&commit=1"
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = views.handle_2fa(request)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            f"Only admin of the {org_other} can perform the action".encode(),
            resp.content,
        )

        # confirming dialog before perform the action
        for action in actions:
            request = self.factory.get(
                f"/org_admin/handle-2fa?org={org.id}&member={member.id}&action={action}"
            )
            mock_csrf_session(request)
            request.user = self.org_admin
            resp = views.handle_2fa(request)
            self.assertEqual(resp.status_code, 200)
            if action == "leave":
                self.assertIn(
                    f"This will allow {member} to keep all privileges within {org}. This conflicts with your 2FA Policy".encode(),
                    resp.content,
                )
            if action == "disable":
                self.assertIn(
                    f"This will turn off the 2FA requirement for {org}, users will not need to use 2FA to login".encode(),
                    resp.content,
                )
            if action == "drop":
                self.assertIn(
                    f"This will completely remove {member} from {org}".encode(),
                    resp.content,
                )

        # after agree in the confirming dialog
        for action in actions:
            request = self.factory.get(
                f"/org_admin/handle-2fa?org={org.id}&member={member.id}&action={action}&commit=1"
            )
            mock_csrf_session(request)
            request.user = self.org_admin
            resp = views.handle_2fa(request)
            self.assertEqual(resp.status_code, 302)
            if action == "leave":
                self.assertIn(member, org.usergroup.user_set.all())
            if action == "disable":
                self.assertFalse(org.require_2fa)
            if action == "drop":
                self.assertNotIn(member, org.usergroup.user_set.all())
        settings.CSRF_USE_SESSIONS = True

    def test_uoar_deny(self):
        """
        Test denying of a user-org-affiliation-request
        org_admin_views.uoar_deny
        """

        # create a uoar for user d
        uoar = models.UserOrgAffiliationRequest.objects.create(
            user=self.user_d, asn=1, status="pending"
        )

        # test that org id was properly derived from network asn
        self.assertEqual(uoar.org.id, self.org.id)

        # test deny
        request = self.factory.post(
            "/org-admin/uoar/deny?org_id=%d" % self.org.id, data={"id": uoar.id}
        )
        mock_csrf_session(request)
        request.user = self.org_admin

        resp = json.loads(org_admin.uoar_deny(request).content)

        self.assertEqual(
            {
                "status": "ok",
            },
            resp,
        )

        # check that user is not a member of the org
        self.assertEqual(
            self.org.usergroup.user_set.filter(id=self.user_d.id).exists(), False
        )

        # check that the UOAR is there, but status is denyed
        uoar = models.UserOrgAffiliationRequest.objects.get(id=uoar.id)
        self.assertEqual(uoar.status, "denied")

        # test: we shouldnt be allowed to deny uoars for the org we are not
        # admins of

        request = self.factory.post(
            "/org-admin/uoar/deny?org_id=%d" % self.org_other.id, data={"id": uoar.id}
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.uoar_approve(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

        # test: trying to deny an uoar that doesn't belong to the org shouldn't
        # be allowed

        uoar_b = models.UserOrgAffiliationRequest.objects.create(
            user=self.user_d, asn=22, status="pending"
        )

        request = self.factory.post(
            "/org-admin/uoar/deny?org_id=%d" % self.org.id, data={"id": uoar_b.id}
        )
        mock_csrf_session(request)
        request.user = self.org_admin
        resp = org_admin.uoar_deny(request)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(json.loads(resp.content), {})

        uoar_b.delete()

    def test_uoar_double_affiliation_request(self):
        """
        Test that making a second affiliation request
        does nothing for normal members bc
        a signal intercepts the request (issue 930)
        """
        self.assertTrue(self.user_a.is_org_member(self.org))
        self.assertTrue(self.user_a not in self.org.admin_usergroup.user_set.all())
        self.assertTrue(self.user_a in self.org.usergroup.user_set.all())

        models.UserOrgAffiliationRequest.objects.create(
            user=self.user_a, org=self.org, status="pending"
        )
        self.assertTrue(self.user_a not in self.org.admin_usergroup.user_set.all())
        self.assertTrue(self.user_a in self.org.usergroup.user_set.all())
        self.assertEqual(models.UserOrgAffiliationRequest.objects.count(), 0)

    def test_uoar_double_deny_admin(self):
        """
        Test that making and denying a second affiliation request
        does nothing for admin members (issue 930)
        """
        self.assertTrue(self.org_admin.is_org_admin(self.org))
        self.assertTrue(self.org_admin in self.org.admin_usergroup.user_set.all())
        self.assertTrue(self.org_admin not in self.org.usergroup.user_set.all())

        uoar_admin = models.UserOrgAffiliationRequest.objects.create(
            user=self.org_admin, asn=1, status="pending"
        )
        """
        Denying an additional request should not change the affiliation
        and should delete the request
        """
        uoar_admin.deny()
        self.assertTrue(self.org_admin in self.org.admin_usergroup.user_set.all())
        self.assertTrue(self.org_admin not in self.org.usergroup.user_set.all())
        self.assertEqual(models.UserOrgAffiliationRequest.objects.count(), 0)

    def test_uoar_double_approve_admin(self):
        """
        Test that making and approving a second affiliation request
        does nothing for admin members (issue 930)
        """
        self.assertTrue(self.org_admin.is_org_admin(self.org))
        self.assertTrue(self.org_admin in self.org.admin_usergroup.user_set.all())
        self.assertTrue(self.org_admin not in self.org.usergroup.user_set.all())

        uoar_admin = models.UserOrgAffiliationRequest.objects.create(
            user=self.org_admin, asn=1, status="pending"
        )
        """
        Approving an additional request should not change the affiliation
        and should delete the request
        """
        uoar_admin.approve()
        self.assertTrue(self.org_admin in self.org.admin_usergroup.user_set.all())
        self.assertTrue(self.org_admin not in self.org.usergroup.user_set.all())
        self.assertEqual(models.UserOrgAffiliationRequest.objects.count(), 0)

    def test_uoar_cancel_on_delete(self):
        """
        Test that user affiliation requests get canceled if the
        organization is deleted
        """

        org = models.Organization.objects.create(name="TestCoD", status="ok")

        uoar = models.UserOrgAffiliationRequest.objects.create(
            user=self.user_c, org=org, status="pending"
        )

        assert uoar.status == "pending"
        assert uoar.id

        org.delete()

        with pytest.raises(models.UserOrgAffiliationRequest.DoesNotExist):
            uoar.refresh_from_db()

        org.refresh_from_db()
        assert org.status == "deleted"
