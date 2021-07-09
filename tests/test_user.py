import json
import re

import pytest
from captcha.models import CaptchaStore
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, TestCase

import peeringdb_server.models as models
import peeringdb_server.views as views


class UserTests(TestCase):
    """
    Test peeringdb_server.models.User functions
    """

    @classmethod
    def setUpTestData(cls):
        cls.guest_group = Group.objects.create(name="guest", id=settings.GUEST_GROUP_ID)
        cls.user_group = Group.objects.create(name="user", id=settings.USER_GROUP_ID)

        settings.USER_GROUP_ID = cls.user_group.id
        settings.GUEST_GROUP_ID = cls.guest_group.id

        for name in ["user_a", "user_b", "user_c", "user_d"]:
            setattr(
                cls,
                name,
                models.User.objects.create_user(
                    name,
                    "%s@localhost" % name,
                    first_name=name,
                    last_name=name,
                    password=name,
                ),
            )

        cls.org_a = models.Organization.objects.create(name="org A", status="ok")
        cls.org_b = models.Organization.objects.create(name="org B", status="ok")

        cls.user_group.user_set.add(cls.user_a)
        cls.user_group.user_set.add(cls.user_d)
        cls.guest_group.user_set.add(cls.user_b)

        cls.org_a.usergroup.user_set.add(cls.user_a)
        cls.org_b.admin_usergroup.user_set.add(cls.user_b)

    def setUp(self):
        self.factory = RequestFactory()

    def test_full_name(self):
        """
        Test User.full_name
        """
        self.assertEqual(self.user_a.full_name, "user_a user_a")

    def test_organizations(self):
        """
        Test User.organizations
        """

        # test that organizations are returned where the user is member
        orgs = self.user_a.organizations
        self.assertEqual(len(orgs), 1)
        self.assertEqual(orgs[0].id, self.org_a.id)

        # test that organizations are returned where the user is admin
        orgs = self.user_b.organizations
        self.assertEqual(len(orgs), 1)
        self.assertEqual(orgs[0].id, self.org_b.id)

        orgs = self.user_c.organizations
        self.assertEqual(len(orgs), 0)

    def test_is_org_member(self):
        """
        Test User.is_org_member
        """
        self.assertEqual(self.user_a.is_org_member(self.org_a), True)
        self.assertEqual(self.user_a.is_org_member(self.org_b), False)
        self.assertEqual(self.user_c.is_org_member(self.org_a), False)
        self.assertEqual(self.user_c.is_org_member(self.org_b), False)

    def test_is_org_admin(self):
        """
        Test User.is_org_admin
        """
        self.assertEqual(self.user_b.is_org_member(self.org_b), False)
        self.assertEqual(self.user_b.is_org_admin(self.org_b), True)
        self.assertEqual(self.user_b.is_org_admin(self.org_a), False)
        self.assertEqual(self.user_b.is_org_member(self.org_a), False)

    def test_is_verified_user(self):
        """
        Test User.is_verified_user
        """

        self.assertEqual(self.user_a.is_verified_user, True)
        self.assertEqual(self.user_b.is_verified_user, False)
        self.assertEqual(self.user_c.is_verified_user, False)

    def test_set_verified(self):
        """
        Test user.set_verified
        """

        self.user_c.set_verified()
        self.user_c.refresh_from_db()

        self.assertEqual(self.user_c.status, "ok")
        self.assertEqual(self.user_c.is_verified_user, True)

        self.assertEqual(self.user_c.groups.filter(name="guest").exists(), False)
        self.assertEqual(self.user_c.groups.filter(name="user").exists(), True)

    def test_set_unverified(self):
        """
        Test user.set_unverified
        """

        self.user_c.set_unverified()
        self.user_c.refresh_from_db()

        self.assertEqual(self.user_c.status, "pending")
        self.assertEqual(self.user_c.is_verified_user, False)

        self.assertEqual(self.user_c.groups.filter(name="guest").exists(), True)
        self.assertEqual(self.user_c.groups.filter(name="user").exists(), False)

    def test_password_reset(self):
        """
        Test User.password_reset_initiate
        Test User.password_reset_complete
        Test views.view_password_reset POST
        """

        # initiate request
        request = self.factory.post(
            "/reset-password", data={"email": self.user_a.email}
        )
        request._dont_enforce_csrf_checks = True
        resp = views.view_password_reset(request)

        # check that password-reset instance was created
        pr = models.UserPasswordReset.objects.get(user=self.user_a)

        self.assertIsNotNone(pr.token)
        self.assertEqual(pr.is_valid(), True)

        # re-initiate internally so we can get the token
        token, hashed = self.user_a.password_reset_initiate()
        pr = self.user_a.password_reset

        # password reset request
        pwd = "abcdefghjikl"
        request = self.factory.post(
            "/reset-password",
            data={
                "target": self.user_a.id,
                "token": token,
                "password": pwd,
                "password_v": pwd,
            },
        )
        request._dont_enforce_csrf_checks = True
        resp = views.view_password_reset(request)

        self.assertEqual(json.loads(resp.content)["status"], "ok")

        with pytest.raises(models.UserPasswordReset.DoesNotExist):
            models.UserPasswordReset.objects.get(user=self.user_a)

        # initiate another request so we can test failures
        token, hashed = self.user_a.password_reset_initiate()

        # failure test: invalid token
        request = self.factory.post(
            "/reset-password",
            data={
                "target": self.user_a.id,
                "token": "wrong",
                "password": pwd,
                "password_v": pwd,
            },
        )
        request._dont_enforce_csrf_checks = True
        resp = views.view_password_reset(request)
        self.assertEqual(resp.status_code, 400)

        # failure test: invalid password(s): length
        request = self.factory.post(
            "/reset-password",
            data={
                "target": self.user_a.id,
                "token": token,
                "password": "a",
                "password_v": "a",
            },
        )
        request._dont_enforce_csrf_checks = True
        resp = views.view_password_reset(request)
        self.assertEqual(resp.status_code, 400)

        # failure test: invalid password(s): validation mismatch
        request = self.factory.post(
            "/reset-password",
            data={
                "target": self.user_a.id,
                "token": token,
                "password": pwd,
                "password_v": "a",
            },
        )
        request._dont_enforce_csrf_checks = True
        resp = views.view_password_reset(request)
        self.assertEqual(resp.status_code, 400)

        # failure test: invalid target
        request = self.factory.post(
            "/reset-password",
            data={
                "target": self.user_b.id,
                "token": token,
                "password": pwd,
                "password_v": pwd,
            },
        )
        request._dont_enforce_csrf_checks = True
        resp = views.view_password_reset(request)
        self.assertEqual(resp.status_code, 400)

    def test_login_redirect(self):
        data = {
            "next": f"/org/{self.org_a.id}",
            "auth-username": "user_d",
            "auth-password": "user_d",
            "login_view-current_step": "auth",
        }
        C = Client()
        resp = C.post("/account/login/", data, follow=True)
        self.assertEqual(resp.redirect_chain, [(f"/org/{self.org_a.id}", 302)])

        data = {
            "next": "/logout",
            "auth-username": "user_d",
            "auth-password": "user_d",
            "login_view-current_step": "auth",
        }

        C = Client()
        resp = C.post("/account/login/", data, follow=True)
        self.assertEqual(resp.redirect_chain, [("/", 302)])
        self.assertEqual(resp.context["user"].is_authenticated, True)

    def test_username_retrieve(self):
        """
        test the username retrieve process
        """

        c = Client()

        # initiate process
        response = c.post("/username-retrieve/initiate", {"email": self.user_a.email})

        secret = c.session["username_retrieve_secret"]
        email = c.session["username_retrieve_email"]
        self.assertNotEqual(secret, None)
        self.assertEqual(email, self.user_a.email)

        # invalid secret
        response = c.get("/username-retrieve/complete?secret=123")
        assert self.user_a.email not in response.content.decode()
        assert (
            f'<p class="username">{self.user_a.username}</p>'
            not in response.content.decode()
        )

        # complete process
        response = c.get(f"/username-retrieve/complete?secret={secret}")

        assert self.user_a.email in response.content.decode()
        assert (
            f'<p class="username">{self.user_a.username}</p>'
            in response.content.decode()
        )

        # process no longer valid
        response = c.get(f"/username-retrieve/complete?secret={secret}")

        assert self.user_a.email not in response.content.decode()
        assert (
            f'<p class="username">{self.user_a.username}</p>'
            not in response.content.decode()
        )

        with pytest.raises(KeyError):
            secret = c.session["username_retrieve_secret"]

        with pytest.raises(KeyError):
            email = c.session["username_retrieve_email"]

    def test_signup(self):
        """
        test user signup with captcha fallback
        """

        c = Client()
        response = c.get("/register")
        assert 'name="captcha_generator_0"' in response.content.decode()
        m = re.search(
            'name="captcha_generator_0" value="([^"]+)"', response.content.decode()
        )

        captcha_obj = CaptchaStore.objects.get(hashkey=m.group(1))

        response = c.post(
            "/register",
            {
                "username": "signuptest",
                "password1": "signuptest_123",
                "password2": "signuptest_123",
                "email": "signuptest@localhost",
                "captcha": f"{captcha_obj.hashkey}:{captcha_obj.response}",
            },
        )

        self.assertEqual(json.loads(response.content), {"status": "ok"})
