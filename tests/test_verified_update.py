import base64
import json

from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

import peeringdb_server.models as models
from peeringdb_server.validators import validate_verified_update_data


class VerifiedUpdateTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # create user and guest group

        call_command("pdb_generate_test_data", limit=2, commit=True)

        for username, email in [
            ("admin", "admin@admin.com"),
            ("user", "test@test.com"),
        ]:
            access = True if username == "admin" else False
            setattr(
                cls,
                username,
                models.User.objects.create_user(
                    username, email, username, is_superuser=access, is_staff=access
                ),
            )
            getattr(cls, username).set_password(username)
            EmailAddress.objects.create(
                user=getattr(cls, username), email=email, verified=True, primary=True
            )
            cls.net = models.Network.objects.first()
            cls.poc = cls.net.poc_set_active.first()
            cls.org = cls.net.org
            cls.org.usergroup.user_set.add(getattr(cls, username))

    def setUp(self):
        self.client = APIClient()
        self.payload = {
            "source": "pdb",
            "reason": "testing",
            "updates": [
                {
                    "ref_tag": "net",
                    "obj_id": self.net.id,
                    "data": {
                        "info_prefixes4": 4,
                        "info_prefixes6": 6,
                        "info_type": "Content",
                    },
                },
                {
                    "ref_tag": "poc",
                    "obj_id": self.poc.id,
                    "data": {"name": "20C", "role": "Sales", "email": "20c@cc.com"},
                },
            ],
        }
        self.payload_invalid_ref_tag = {
            "source": "pdb",
            "reason": "testing",
            "updates": [
                {
                    "ref_tag": "invalid",
                    "obj_id": self.net.id,
                    "data": {"info_prefixes4": 4, "info_prefixes6": 6},
                }
            ],
        }
        self.payload_invalid_obj_id = {
            "source": "pdb",
            "reason": "testing",
            "updates": [
                {
                    "ref_tag": "net",
                    "obj_id": 999,
                    "data": {"info_prefixes4": 4, "info_prefixes6": 6},
                }
            ],
        }
        self.payload_accept = {
            "data[]": ["net", f"{self.net.id}", "poc", f"{self.poc.id}"],
            "data[][info_prefixes4]": ["4"],
            "data[][info_prefixes6]": ["6"],
            "data[][name]": ["20C"],
            "data[][role]": ["Sales"],
            "data[][email]": ["20c@cc.com"],
            "reason": "testing",
            "source": "pdb",
            "referer": "http://testserver/verified-update",
        }
        self.payload_accept_empty_data = {
            "data[]": ["net", self.net.id, "poc", self.poc.id]
        }

    def _get_encoded_payload(self, payload):
        """
        Helper function to encode a payload into a base64 string
        """
        return base64.b64encode(json.dumps(payload).encode()).decode()

    def test_verified_update(self):
        self.client.login(username="admin", password="admin")
        encoded_payload = self._get_encoded_payload(self.payload)
        response = self.client.get(
            f"/verified-update?p={encoded_payload}",
            follow=True,
        )
        print(response.content.decode("utf-8"))
        self.assertIn(
            f"<b>{self.payload['source']}</b> proposes the following changes to:",
            response.content.decode("utf-8"),
        )
        self.assertIn(f"<h3>{self.net} -", response.content.decode("utf-8"))
        self.assertIn(f"<h3>{self.poc} -", response.content.decode("utf-8"))
        self.assertIn(
            '<button type="submit" class="btn btn-primary commit">Accept selected changes</button>',
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 200)

    def test_verified_update_invalid_ref_tag(self):
        self.client.login(username="admin", password="admin")
        encoded_payload = self._get_encoded_payload(self.payload_invalid_ref_tag)
        response = self.client.get(
            f"/verified-update?p={encoded_payload}",
            follow=True,
        )
        self.assertIn(
            "Proposed update contains invalid data: Unknown object type:",
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 400)

    def test_verified_update_invalid_obj_id(self):
        self.client.login(username="admin", password="admin")
        encoded_payload = self._get_encoded_payload(self.payload_invalid_obj_id)
        response = self.client.get(
            f"/verified-update?p={encoded_payload}",
            follow=True,
        )
        self.assertIn(
            "Proposed update contains invalid data: object net.999 not found",
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 400)

    def test_verified_update_invalid_permission(self):
        self.client.login(username="user", password="user")
        encoded_payload = self._get_encoded_payload(self.payload)
        response = self.client.get(
            f"/verified-update?p={encoded_payload}",
            follow=True,
        )
        self.assertIn(
            "You do not have permissions to make changes to:",
            response.content.decode("utf-8"),
        )
        self.assertIn(f"<p>{self.net} -", response.content.decode("utf-8"))
        self.assertIn(f"<p>{self.poc} -", response.content.decode("utf-8"))
        self.assertNotIn(f"<h3>{self.net} -", response.content.decode("utf-8"))
        self.assertNotIn(f"<h3>{self.poc} -", response.content.decode("utf-8"))
        self.assertNotIn(
            '<button type="submit" class="btn btn-primary commit">Accept selected changes</button>',
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 200)

    def test_verified_update_accept(self):
        self.assertNotEqual(self.net.info_prefixes4, 4)
        self.assertNotEqual(self.net.info_prefixes6, 6)
        self.assertNotEqual(self.poc.name, "20C")
        self.assertNotEqual(self.poc.role, "Sales")
        self.assertNotEqual(self.poc.email, "20c@cc.com")
        self.client.login(username="admin", password="admin")
        response = self.client.post(
            "/verified-update/accept/",
            data=self.payload_accept,
            follow=True,
        )
        print(response.content.decode("utf-8"))

        self.net.refresh_from_db()
        self.poc.refresh_from_db()
        self.assertIn("<h3>Successfully updated</h3>", response.content.decode("utf-8"))
        self.assertIn(
            f'<li><a href="{self.net.view_url}">{self.net.name}</a></li>',
            response.content.decode("utf-8"),
        )
        self.assertIn(
            f'<li><a href="{self.poc.view_url}">{self.poc.name}</a></li>',
            response.content.decode("utf-8"),
        )
        self.assertEqual(self.net.info_prefixes4, 4)
        self.assertEqual(self.net.info_prefixes6, 6)
        self.assertEqual(self.poc.name, "20C")
        self.assertEqual(self.poc.role, "Sales")
        self.assertEqual(self.poc.email, "20c@cc.com")
        self.assertEqual(response.status_code, 200)

    def test_verified_update_accept_empty_data(self):
        self.client.login(username="admin", password="admin")
        response = self.client.post(
            "/verified-update/accept/",
            data=self.payload_accept_empty_data,
            follow=True,
        )
        self.assertIn(
            "Please select one or more data", response.content.decode("utf-8")
        )
        self.assertEqual(response.status_code, 200)

    def test_verified_update_accept_no_permission(self):
        self.client.login(username="user", password="user")
        response = self.client.post(
            "/verified-update/accept/",
            data=self.payload_accept,
            follow=True,
        )
        self.assertIn(
            "You do not have permissions to make changes to",
            response.content.decode("utf-8"),
        )
        self.assertIn(
            f'<p><a href="{self.net.view_url}">{self.net.name}</a>',
            response.content.decode("utf-8"),
        )
        self.assertIn(
            f'<p><a href="{self.poc.view_url}">{self.poc.name}</a>',
            response.content.decode("utf-8"),
        )
        self.assertEqual(response.status_code, 200)

    def test_validate_verified_update_data(self):
        test_data = [
            # success validation
            (
                "net",
                self.net.id,
                {"info_prefixes4": 4, "info_prefixes6": 6},
                (True, {"info_prefixes4": 4, "info_prefixes6": 6}),
            ),
            # success validation with a data has same value as current data
            (
                "net",
                self.net.id,
                {"info_prefixes4": self.net.info_prefixes4, "info_prefixes6": 6},
                (True, {"info_prefixes6": 6}),
            ),
            # fail validation
            (
                "net",
                self.net.id,
                {},
                (False, "Data is empty"),
            ),
            (
                "invalid",
                self.net.id,
                {"info_prefixes4": 4, "info_prefixes6": 6},
                (False, "Unknown object type: invalid"),
            ),
            (
                "net",
                999,
                {"info_prefixes4": 4, "info_prefixes6": 6},
                (False, "object net.999 not found"),
            ),
        ]

        for ref_tag, obj_id, data, validated in test_data:
            with self.subTest(
                ref_tag=ref_tag, obj_id=obj_id, data=data, validated=validated
            ):
                if not validated[0]:
                    self.assertTrue(
                        isinstance(
                            str(
                                validate_verified_update_data(ref_tag, obj_id, data)[1]
                            ),
                            str,
                        )
                    )
                    self.assertTrue(
                        validate_verified_update_data(ref_tag, obj_id, data)[1],
                        validated[1],
                    )
                else:
                    self.assertTrue(
                        isinstance(
                            validate_verified_update_data(ref_tag, obj_id, data)[1],
                            dict,
                        )
                    )
                self.assertEqual(
                    validate_verified_update_data(ref_tag, obj_id, data), validated
                )
