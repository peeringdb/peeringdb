import json

from allauth.account.models import EmailAddress
from django.test import TestCase
from django.urls import reverse
from grainy.const import PERM_CREATE, PERM_DELETE, PERM_READ, PERM_UPDATE
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Organization,
    OrganizationAPIKey,
    OrganizationAPIPermission,
    User,
    UserAPIKey,
)


class OrganizationUsersViewSetTests(TestCase):
    def setUp(self):
        """Set up test client and common headers"""
        self.client = APIClient()
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
        self.assertIn("User is already in the organization", data["meta"]["error"])

    def test_add_user_unverified_email(self):
        """
        Tests that member2 cannot be added to the organization since"
        their email is not verified
        """
        User.objects.create_user(
            "member2", "member2@localhost", first_name="member2", last_name="member"
        )

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
        self.assertIn("User email is not verified", data["meta"]["error"])

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
