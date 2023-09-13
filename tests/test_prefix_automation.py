import base64

from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

import peeringdb_server.models as models


class PrefixAutomationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # create user and guest group
        user_group = Group.objects.create(name="user")

        cls.base_org = models.Organization.objects.create(
            name="Prefix Automation Tests", status="ok"
        )

        for username, email in [
            ("user_ok", "hostmaster@uen.org"),
            ("user_pending", "neteng@other.com"),
        ]:
            setattr(
                cls,
                username,
                models.User.objects.create_user(
                    username, email, username, is_superuser=True, is_staff=True
                ),
            )
            getattr(cls, username).set_password(username)
            EmailAddress.objects.create(
                user=getattr(cls, username), email=email, verified=True, primary=True
            )
            cls.base_org.usergroup.user_set.add(getattr(cls, username))
            user_group.user_set.add(getattr(cls, username))

    def setUp(self):
        self.client = APIClient()
        self.payload = {
            "org_id": self.base_org.id,
            "name": "testIX",
            "city": "New York",
            "country": "US",
            "region_continent": "North America",
            "media": "Ethernet",
            "website": "http://example.com",
            "social_media": [],
            "url_stats": "http://example.com",
            "tech_email": "user@example.com",
            "tech_phone": "",
            "policy_email": "user@example.com",
            "policy_phone": "",
            "sales_phone": "",
            "sales_email": "",
            "prefix": "205.127.237.0/24",
            "status_dashboard": "",
        }

    def test_ix_create_auto_approved(self):
        auth = base64.b64encode(b"user_ok:user_ok").decode("utf-8")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {auth}")
        request = self.client.post(
            "/api/ix",
            data=self.payload,
            format="json",
        )
        self.assertEqual(request.data["status"], "ok")
        self.assertEqual(request.status_code, 201)
        subject = f"[PREFIXAUTO] Approval granted to Internet Exchange '{self.payload['name']}' created by user 'user_ok'"
        deskpro = models.DeskProTicket.objects.filter(subject__icontains=subject)
        self.assertTrue(deskpro.exists())

    def test_ix_create_pending(self):
        auth = base64.b64encode(b"user_pending:user_pending").decode("utf-8")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {auth}")
        request = self.client.post(
            "/api/ix",
            data=self.payload,
            format="json",
        )
        self.assertEqual(request.data["status"], "pending")
        self.assertEqual(request.status_code, 201)
        subject = f"[PREFIXAUTO] Approval granted to Internet Exchange '{self.payload['name']}' created by user 'user_ok'"
        deskpro = models.DeskProTicket.objects.filter(subject__icontains=subject)
        self.assertFalse(deskpro.exists())
