import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django_grainy.util import Permissions
from grainy.const import (
    PERM_CREATE,
    PERM_CRUD,
    PERM_DELETE,
    PERM_READ,
    PERM_UPDATE,
)
from rest_framework.test import APIClient
from reversion.models import Revision

from peeringdb_server.models import (
    Organization,
    OrganizationAPIKey,
    OrganizationAPIPermission,
    User,
    UserAPIKey,
    UserOrgAffiliationRequest,
)
from peeringdb_server.rest import ADD_ORGANIZATION_USER_NO_REQUEST
from peeringdb_server.rest_throttles import OrganizationUsersThrottle


class OrganizationUsersViewSetTests(TestCase):
    def setUp(self):
        """Set up test client and common headers"""
        self.client = APIClient()

        # approving an affiliation request moves the user to the user group
        Group.objects.get_or_create(name="guest", id=settings.GUEST_GROUP_ID)
        Group.objects.get_or_create(name="user", id=settings.USER_GROUP_ID)
        self.admin_user = User.objects.create_user(
            "admin", "admin@localhost", first_name="admin", last_name="admin"
        )

        self.member1 = User.objects.create_user(
            "member", "member@localhost", first_name="member", last_name="member"
        )

        self.org = Organization.objects.create(name="Test", status="ok")

        self.org.admin_usergroup.user_set.add(self.admin_user)
        self.org.usergroup.user_set.add(self.member1)

        api_admin_key, admin_key = UserAPIKey.objects.create_key(
            name="admin key", user=self.admin_user
        )
        self.admin_key = admin_key

        api_member_key, member_key = UserAPIKey.objects.create_key(
            name="member key", user=self.member1
        )
        self.member_key = member_key

        org_key, api_org = OrganizationAPIKey.objects.create_key(
            name="org key", org=self.org, email="admin@localhost"
        )
        self.org_key = api_org
        self.org_key_instance = org_key

        self.headers_admin = {
            "HTTP_AUTHORIZATION": f"api-key {self.admin_key}",
        }
        self.headers_org = {
            "HTTP_AUTHORIZATION": f"api-key {self.org_key}",
        }
        self.headers_member = {
            "HTTP_AUTHORIZATION": f"api-key {self.member_key}",
        }

        self.namespace = f"peeringdb.organization.{self.org.id}.users"

    def _org_namespaces(self, user, org):
        """
        The namespaces `user` holds that belong to `org`, boundary-tested in
        python rather than through the filter under test.
        """

        root = org.grainy_namespace
        prefix = f"{root}."
        return {
            perm.namespace
            for perm in user.grainy_permissions.all()
            if perm.namespace == root or perm.namespace.startswith(prefix)
        }

    def _seed_org_permissions(self, user, org, permission):
        """
        Give `user` their own grainy rows for `org`: the org root grant plus one
        row below it. Written directly, so the test does not depend on the
        helper the fix routes through.
        """

        user.grainy_permissions.create(
            namespace=org.grainy_namespace, permission=permission
        )
        user.grainy_permissions.create(
            namespace=f"{org.grainy_namespace}.network", permission=permission
        )

    def _request_affiliation(self, user, org=None):
        """
        File a pending affiliation request from `user` to `org` (default: the
        test org).
        """

        return UserOrgAffiliationRequest.objects.create(
            org=org or self.org, user=user, status="pending"
        )

    def _can(self, user, namespace, flag):
        """
        Effective permission for `user` at `namespace`, own rows merged with
        group rows as at request time.
        """

        return Permissions(User.objects.get(id=user.id)).check(namespace, flag)

    def test_admin_api_list_users_(self):
        url = reverse("api:organization-users-list", kwargs={"org_id": self.org.id})
        response = self.client.get(url, **self.headers_admin)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("meta", data)
        self.assertIn("data", data)
        self.assertTrue(isinstance(data["data"], list))

        if data["data"]:
            user = data["data"][0]
            expected_fields = {
                "id",
                "first_name",
                "last_name",
                "full_name",
                "is_active",
                "date_joined",
                "status",
                "role",
            }
            self.assertEqual(set(user.keys()), expected_fields)

    def test_org_api_list_users_(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_READ,
        )
        url = reverse("api:organization-users-list", kwargs={"org_id": self.org.id})
        response = self.client.get(url, **self.headers_org)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("meta", data)
        self.assertIn("data", data)
        self.assertTrue(isinstance(data["data"], list))

        if data["data"]:
            user = data["data"][0]
            expected_fields = {
                "id",
                "first_name",
                "last_name",
                "full_name",
                "is_active",
                "date_joined",
                "status",
                "role",
            }
            self.assertEqual(set(user.keys()), expected_fields)

    def test_admin_api_add_user(self):
        member = User.objects.create_user(
            "member2", "member2@localhost", first_name="member2", last_name="member"
        )
        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        data = {"user_email": "member2@localhost"}

        EmailAddress.objects.create(
            user=member, email="member2@localhost", primary=True, verified=True
        )
        self._request_affiliation(member)

        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("data", data)
        self.assertIn("meta", data)

    def test_org_api_add_user(self):
        member = User.objects.create_user(
            "member2", "member2@localhost", first_name="member2", last_name="member"
        )

        EmailAddress.objects.create(
            user=member, email="member2@localhost", primary=True, verified=True
        )
        self._request_affiliation(member)

        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_CREATE,
        )
        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        data = {"user_email": "member2@localhost"}

        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("data", data)
        self.assertIn("meta", data)

    def test_admin_api_update_role(self):
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        data = {"role": "admin"}

        response = self.client.put(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("data", data)
        self.assertIn("meta", data)

    def test_org_api_update_role(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_UPDATE,
        )
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        data = {"role": "admin"}

        response = self.client.put(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("data", data)
        self.assertIn("meta", data)

    def test_admin_api_remove_user(self):
        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        data = {"user_email": "member@localhost"}

        response = self.client.delete(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 204)

    def test_org_api_remove_user(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_DELETE,
        )
        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        data = {"user_email": "member@localhost"}

        response = self.client.delete(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 204)

    def test_admin_api_update_role_clears_user_permissions(self):
        """
        Test that promoting a member over the API clears their own grainy rows
        for the org (#2038)

        The role change only moved group membership, so the member's org root
        row survived and shadowed the admin group's CRUD grant.
        """

        self._seed_org_permissions(self.member1, self.org, PERM_CREATE | PERM_READ)
        self.assertFalse(
            self._can(self.member1, self.org.grainy_namespace, PERM_UPDATE)
        )

        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        response = self.client.put(
            url,
            data=json.dumps({"role": "admin"}),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._org_namespaces(self.member1, self.org), set())
        self.assertTrue(self._can(self.member1, self.org.grainy_namespace, PERM_CRUD))

    def test_admin_api_update_role_demote_clears_user_permissions(self):
        """
        Test the demotion direction of the same wipe (#2038): an admin moved
        back to member must not keep the capabilities their own rows granted.
        """

        self.org.usergroup.user_set.remove(self.member1)
        self.org.admin_usergroup.user_set.add(self.member1)
        self._seed_org_permissions(self.member1, self.org, PERM_CRUD)

        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        response = self.client.put(
            url,
            data=json.dumps({"role": "member"}),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._org_namespaces(self.member1, self.org), set())
        self.assertTrue(self._can(self.member1, self.org.grainy_namespace, PERM_READ))
        self.assertFalse(
            self._can(self.member1, self.org.grainy_namespace, PERM_UPDATE)
        )

    def test_admin_api_update_role_member_to_member_keeps_permissions(self):
        """
        Test that a role update that changes nothing leaves the member's
        granular permissions alone (#2038)

        An API client that sets every user's role on each run would otherwise
        wipe an org's per-entity permissioning wholesale.
        """

        self._seed_org_permissions(self.member1, self.org, PERM_CRUD)
        expected = self._org_namespaces(self.member1, self.org)

        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        response = self.client.put(
            url,
            data=json.dumps({"role": "member"}),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._org_namespaces(self.member1, self.org), expected)

    def test_admin_api_add_user_clears_user_permissions(self):
        """
        Test that adding a user over the API clears any grainy rows they still
        hold for the org (#2038)

        A user already in either group is refused, so whoever gets added held
        no role here -- and `pdb_fix_org_admin_perms --list-unaffiliated`
        exists because that population does hold rows. Without the wipe such a
        row shadows the group grant the new role is supposed to give them.
        """

        member = User.objects.create_user(
            "member2", "member2@localhost", first_name="member2", last_name="member"
        )
        EmailAddress.objects.create(
            user=member, email="member2@localhost", primary=True, verified=True
        )
        self._request_affiliation(member)
        self._seed_org_permissions(member, self.org, PERM_CRUD)

        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        response = self.client.post(
            url,
            data=json.dumps({"user_email": "member2@localhost", "role": "member"}),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self._org_namespaces(member, self.org), set())

        # the member group's READ grant is all that is left

        self.assertTrue(self._can(member, self.org.grainy_namespace, PERM_READ))
        self.assertFalse(self._can(member, self.org.grainy_namespace, PERM_UPDATE))

    def test_admin_api_remove_user_clears_user_permissions(self):
        """
        Test that removing a user over the API clears their own grainy rows for
        the org (#2038)

        Grainy rows outlive group membership, so a user removed this way kept
        working permissions on the org's entities. The UI's
        `manage_user_delete` has always wiped them.
        """

        self._seed_org_permissions(self.member1, self.org, PERM_CRUD)
        self.assertTrue(self._can(self.member1, self.org.grainy_namespace, PERM_DELETE))

        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        response = self.client.delete(
            url,
            data=json.dumps({"user_email": "member@localhost"}),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self._org_namespaces(self.member1, self.org), set())
        self.assertFalse(self._can(self.member1, self.org.grainy_namespace, PERM_READ))

    def test_org_api_list_users_no_permission(self):
        url = reverse("api:organization-users-list", kwargs={"org_id": self.org.id})
        response = self.client.get(url, **self.headers_org)

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn(
            "Insufficient permissions for this operation", data["meta"]["error"]
        )

    def test_list_users_not_admin(self):
        url = reverse("api:organization-users-list", kwargs={"org_id": self.org.id})
        response = self.client.get(url, **self.headers_member)

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn(
            "User is not an admin of this organization", data["meta"]["error"]
        )

    def test_list_users_invalid_api(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_READ,
        )
        headers = {"Authorization": "api-key " + self.org_key + "fail"}
        url = reverse("api:organization-users-list", kwargs={"org_id": self.org.id})
        response = self.client.get(url, **headers)

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn("Invalid authentication", data["meta"]["error"])

    def test_add_user_no_permission(self):
        member = User.objects.create_user(
            "member5", "member5@localhost", first_name="member5", last_name="member"
        )

        EmailAddress.objects.create(
            user=member, email="member5@localhost", primary=True, verified=True
        )

        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        data = {"user_email": "member5@localhost"}

        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn(
            "Insufficient permissions for this operation", data["meta"]["error"]
        )

    def test_add_user_no_email(self):
        member = User.objects.create_user(
            "member3", "member3@localhost", first_name="member3", last_name="member"
        )

        EmailAddress.objects.create(
            user=member, email="member3@localhost", primary=True, verified=True
        )

        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_CREATE,
        )
        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})

        response = self.client.post(
            url, content_type="application/json", **self.headers_org
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("user_email is required", data["meta"]["error"])

    def test_add_existing_user(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_CREATE,
        )
        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        data = {"user_email": "member@localhost"}

        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn(ADD_ORGANIZATION_USER_NO_REQUEST, data["meta"]["error"])

    def test_add_user_unverified_email(self):
        """
        Tests that member2 cannot be added to the organization since
        their email is not verified, even with a pending request
        """
        member = User.objects.create_user(
            "member2", "member2@localhost", first_name="member2", last_name="member"
        )
        self._request_affiliation(member)

        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_CREATE,
        )
        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        data = {"user_email": "member2@localhost"}

        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn(ADD_ORGANIZATION_USER_NO_REQUEST, data["meta"]["error"])

    def test_add_user_invalid_role(self):
        member = User.objects.create_user(
            "member4", "member4@localhost", first_name="member4", last_name="member"
        )
        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        data = {"user_email": "member4@localhost", "role": "user"}

        EmailAddress.objects.create(
            user=member, email="member4@localhost", primary=True, verified=True
        )

        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_admin,
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("Invalid role. Must be admin or member", data["meta"]["error"])

    def test_add_user_not_admin(self):
        member = User.objects.create_user(
            "member8", "member8@localhost", first_name="member8", last_name="member"
        )

        EmailAddress.objects.create(
            user=member, email="member8@localhost", primary=True, verified=True
        )

        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        data = {"user_email": "member8@localhost"}

        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_member,
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn(
            "User is not an admin of this organization", data["meta"]["error"]
        )

    def test_add_user_no_api(self):
        member = User.objects.create_user(
            "member9", "member9@localhost", first_name="member9", last_name="member"
        )

        EmailAddress.objects.create(
            user=member, email="member9@localhost", primary=True, verified=True
        )

        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        data = {"user_email": "member9@localhost"}

        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn("Invalid authentication", data["meta"]["error"])

    def test_update_role_no_api(self):
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        data = {"role": "admin"}

        response = self.client.put(
            url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn("Invalid authentication", data["meta"]["error"])

    def test_update_role_no_permission(self):
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        data = {"role": "admin"}

        response = self.client.put(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn(
            "Insufficient permissions for this operation", data["meta"]["error"]
        )

    def test_update_role_not_include_role(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_UPDATE,
        )
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )

        response = self.client.put(
            url, content_type="application/json", **self.headers_org
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("role is required", data["meta"]["error"])

    def test_update_role_invalid_role(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_UPDATE,
        )
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        data = {"role": "user"}

        response = self.client.put(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("Invalid role. Must be admin or member", data["meta"]["error"])

    def test_update_role_user_not_found(self):
        user = User.objects.create_user(
            "user", "user@localhost", first_name="user", last_name="user"
        )

        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_UPDATE,
        )
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": user.id},
        )
        data = {"role": "admin"}

        response = self.client.put(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("User is not in the organization", data["meta"]["error"])

    def test_update_role_not_admin(self):
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        data = {"role": "admin"}

        response = self.client.put(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_member,
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn(
            "User is not an admin of this organization", data["meta"]["error"]
        )

    def test_remove_user_no_api(self):
        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        data = {"user_email": "member@localhost"}

        response = self.client.delete(
            url, data=json.dumps(data), content_type="application/json"
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn("Invalid authentication", data["meta"]["error"])

    def test_remove_user_no_permission(self):
        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        data = {"user_email": "member@localhost"}

        response = self.client.delete(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn(
            "Insufficient permissions for this operation", data["meta"]["error"]
        )

    def test_remove_user_not_admin(self):
        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        data = {"user_email": "member@localhost"}
        response = self.client.delete(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_member,
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn(
            "User is not an admin of this organization", data["meta"]["error"]
        )

    def test_remove_user_not_found(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_DELETE,
        )
        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        data = {"user_email": "nonexistent@localhost"}

        response = self.client.delete(
            url,
            data=json.dumps(data),
            content_type="application/json",
            **self.headers_org,
        )

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("User is not in the organization", data["meta"]["error"])

    def test_remove_user_no_email(self):
        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_DELETE,
        )
        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        response = self.client.delete(
            url, content_type="application/json", **self.headers_org
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("user_email is required", data["meta"]["error"])

    def _readonly_admin_headers(self):
        _, key = UserAPIKey.objects.create_key(
            name="readonly admin key", user=self.admin_user, readonly=True
        )
        return {"HTTP_AUTHORIZATION": f"api-key {key}"}

    def test_readonly_admin_key_list_users(self):
        url = reverse("api:organization-users-list", kwargs={"org_id": self.org.id})
        response = self.client.get(url, **self._readonly_admin_headers())

        self.assertEqual(response.status_code, 200)

    def test_readonly_admin_key_cannot_add_admin(self):
        attacker = User.objects.create_user("attacker", "attacker@localhost")
        EmailAddress.objects.create(
            user=attacker, email="attacker@localhost", primary=True, verified=True
        )
        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        response = self.client.post(
            url,
            data=json.dumps({"user_email": "attacker@localhost", "role": "admin"}),
            content_type="application/json",
            **self._readonly_admin_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("API key is readonly", response.json()["meta"]["error"])
        self.assertFalse(attacker.is_org_admin(self.org))
        self.assertFalse(attacker.is_org_member(self.org))

    def test_readonly_admin_key_cannot_update_role(self):
        url = reverse(
            "api:organization-users-update-role",
            kwargs={"org_id": self.org.id, "user_id": self.member1.id},
        )
        response = self.client.put(
            url,
            data=json.dumps({"role": "admin"}),
            content_type="application/json",
            **self._readonly_admin_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.member1.is_org_admin(self.org))
        self.assertTrue(self.member1.is_org_member(self.org))

    def test_readonly_admin_key_cannot_remove_user(self):
        url = reverse("api:organization-users-remove", kwargs={"org_id": self.org.id})
        response = self.client.delete(
            url,
            data=json.dumps({"user_email": "admin@localhost"}),
            content_type="application/json",
            **self._readonly_admin_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.admin_user.is_org_admin(self.org))

    def _post_add(self, data, headers):
        url = reverse("api:organization-users-add", kwargs={"org_id": self.org.id})
        return self.client.post(
            url, data=json.dumps(data), content_type="application/json", **headers
        )

    def _verified_user(self, username, email):
        user = User.objects.create_user(
            username, email, first_name=username, last_name="user"
        )
        EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
        return user

    def test_add_user_failures_share_one_response(self):
        """
        Test that nothing about the account behind an email address can be
        told from a failed add: no account, no request, an unverified
        address, a closed account, a member or admin with a pending request,
        a denied request, a request to another org, two pending requesters
        sharing the address and an accent variant of a requester's address
        all get the same response
        """

        self._verified_user("norequest", "norequest@localhost")

        closed = self._verified_user("closed", "closed@localhost")
        self._request_affiliation(closed)
        closed.is_active = False
        closed.save()

        # joined after asking, so their requests are still pending
        member2 = self._verified_user("member2", "member2@localhost")
        admin2 = self._verified_user("admin2", "admin2@localhost")
        pending = [
            self._request_affiliation(member2),
            self._request_affiliation(admin2),
        ]
        self.org.usergroup.user_set.add(member2)
        self.org.admin_usergroup.user_set.add(admin2)

        unverified = User.objects.create_user("unverified", "unverified@localhost")
        EmailAddress.objects.create(
            user=unverified, email="unverified@localhost", verified=False
        )
        self._request_affiliation(unverified)

        # legacy data: the db does not enforce unique verified addresses
        for username in ("dup1", "dup2"):
            dup = self._verified_user(username, f"{username}@localhost")
            EmailAddress.objects.create(
                user=dup, email="shared@localhost", verified=True
            )
            pending.append(self._request_affiliation(dup))

        # the db collation would match these, the comparison must not
        jose = self._verified_user("jose", "jos\u00e9@localhost")
        pending.append(self._request_affiliation(jose))

        denied = self._verified_user("denied", "denied@localhost")
        self._request_affiliation(denied).deny()

        other_org = Organization.objects.create(name="Other", status="ok")
        elsewhere = self._verified_user("elsewhere", "elsewhere@localhost")
        self._request_affiliation(elsewhere, org=other_org)

        responses = []
        with patch.object(
            OrganizationUsersThrottle, "allow_request", return_value=True
        ):
            for email in (
                "nobody@localhost",
                "norequest@localhost",
                "unverified@localhost",
                "closed@localhost",
                "member@localhost",
                "member2@localhost",
                "admin2@localhost",
                "denied@localhost",
                "elsewhere@localhost",
                "shared@localhost",
                "jose@localhost",
            ):
                response = self._post_add({"user_email": email}, self.headers_admin)
                responses.append((email, response.status_code, response.content))

        self.assertEqual(responses[0][1], 400)
        self.assertIn(
            ADD_ORGANIZATION_USER_NO_REQUEST,
            json.loads(responses[0][2])["meta"]["error"],
        )
        for email, status_code, content in responses:
            self.assertEqual(status_code, 400, email)
            self.assertEqual(content, responses[0][2], email)

        self.assertEqual(
            set(self.org.usergroup.user_set.all()), {self.member1, member2}
        )
        self.assertEqual(
            set(self.org.admin_usergroup.user_set.all()), {self.admin_user, admin2}
        )
        for uoar in pending:
            uoar.refresh_from_db()
            self.assertEqual(uoar.status, "pending")

    @override_settings(MAIL_DEBUG=False)
    def test_add_user_approves_pending_request(self):
        """
        Test that adding a user with a pending request approves it the way
        the org admin view does, and the response shows only the user list
        fields
        """

        OrganizationAPIPermission.objects.create(
            org_api_key=self.org_key_instance,
            namespace=self.namespace,
            permission=PERM_CREATE,
        )
        member = self._verified_user("member2", "member2@localhost")
        self._request_affiliation(member)
        mail.outbox = []

        response = self._post_add({"user_email": "Member2@localhost"}, self.headers_org)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            set(response.json()["data"][0].keys()),
            {
                "id",
                "first_name",
                "last_name",
                "full_name",
                "is_active",
                "date_joined",
                "status",
                "role",
            },
        )
        self.assertTrue(member.is_org_member(self.org))
        self.assertFalse(member.is_org_admin(self.org))
        self.assertFalse(
            UserOrgAffiliationRequest.objects.filter(
                user=member, org=self.org, status="pending"
            ).exists()
        )

        # the org's admins learn about it as they do for a web approval
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.admin_user.email])
        self.assertIn(self.org_key_instance.prefix, mail.outbox[0].body)

        # an org key is not a user, the revision names the key instead
        revision = Revision.objects.latest("id")
        self.assertIsNone(revision.user)
        self.assertIn(self.org_key_instance.prefix, revision.comment)

    def test_add_user_role_admin(self):
        member = self._verified_user("member2", "member2@localhost")
        self._request_affiliation(member)

        response = self._post_add(
            {"user_email": "member2@localhost", "role": "admin"}, self.headers_admin
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"][0]["role"], "admin")
        self.assertTrue(member.is_org_admin(self.org))
        self.assertFalse(member.is_org_member(self.org))

        # the approval is attributed to the user the API key belongs to
        self.assertEqual(Revision.objects.latest("id").user, self.admin_user)

    def test_add_user_restricted_email_domain(self):
        """
        Test that the org's email domain restriction holds for a request
        filed before the restriction was turned on
        """

        member = self._verified_user("member2", "member2@localhost")
        uoar = self._request_affiliation(member)

        self.org.restrict_user_emails = True
        self.org.email_domains = "example.com"
        self.org.save()

        response = self._post_add(
            {"user_email": "member2@localhost"}, self.headers_admin
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["meta"]["error"], ADD_ORGANIZATION_USER_NO_REQUEST
        )
        self.assertFalse(member.is_org_member(self.org))
        uoar.refresh_from_db()
        self.assertEqual(uoar.status, "pending")
