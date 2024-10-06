import django_read_only
from django.conf import settings
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from peeringdb_server.models import REFTAG_MAP, User


class TestReadOnlyMode(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="adminpassword",
            is_superuser=True,
        )
        cls.org = REFTAG_MAP["org"].objects.create(
            name="Test Organization", status="ok"
        )

    def test_setting_changed(self):
        """
        Check that if the setting changes, read_only mode updates
        appropriately.
        """
        with override_settings(DJANGO_READ_ONLY=False):
            assert not django_read_only.read_only

            with override_settings(DJANGO_READ_ONLY=True):
                assert django_read_only.read_only

    @override_settings(
        DJANGO_READ_ONLY=True,
        INSTALLED_APPS=settings.INSTALLED_APPS + ["django_read_only"],
    )
    def test_login_in_read_only_mode(self):
        """Test that login is not blocked when read-only mode is enabled."""

        user = User.objects.get(username=self.superuser.username)
        last_login_before = user.last_login

        client = Client()
        response = client.post(
            "/account/login/",
            {"username": self.superuser.username, "password": "adminpassword"},
        )
        # Verify that login is not blocked
        self.assertEqual(response.status_code, 200)

        user.refresh_from_db()
        last_login_after = user.last_login

        # Last login should not be changed
        self.assertEqual(last_login_before, last_login_after)

    @override_settings(
        DJANGO_READ_ONLY=True,
        INSTALLED_APPS=settings.INSTALLED_APPS + ["django_read_only"],
    )
    def test_post_facility_in_read_only_mode(self):
        """Test that posting a new facility is blocked in read-only mode."""
        client = APIClient()
        client.force_authenticate(self.superuser)

        self.assertIn("django_read_only", settings.INSTALLED_APPS)

        # Attempt to post a new facility in read-only mode
        with self.assertRaises(django_read_only.DjangoReadOnlyError):
            client.post(
                "/api/fac",
                {
                    "org_id": self.org.id,
                    "name": "Test Facility",
                    "status": "ok",
                    "address1": "123 Test Street",
                    "city": "Test City",
                    "country": "US",
                    "website": "https://example.com",
                    "zipcode": "1-2345",
                },
                format="json",
            )

    @override_settings(DJANGO_READ_ONLY=False)  # Ensure read-only mode is off
    def test_post_facility_in_normal_mode(self):
        """Test that posting a new facility works when read-only mode is disabled."""
        client = APIClient()
        client.force_authenticate(self.superuser)

        self.assertNotIn("django_read_only", settings.INSTALLED_APPS)

        response = client.post(
            "/api/fac",
            {
                "org_id": self.org.id,
                "name": "Test Facility",
                "status": "ok",
                "address1": "123 Test Street",
                "city": "Test City",
                "country": "US",
                "website": "https://example.com",
                "zipcode": "1-2345",
            },
            format="json",
        )

        # Assert that the facility was created successfully
        self.assertEqual(response.status_code, 201)
