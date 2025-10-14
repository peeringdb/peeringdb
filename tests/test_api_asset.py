import base64
import io

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from PIL import Image
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Campus,
    Carrier,
    Facility,
    InternetExchange,
    Network,
    Organization,
    UserOrgAffiliationRequest,
)

from .util import ClientCase, reset_group_ids

User = get_user_model()


def create_test_image(width=50, height=50, format="PNG"):
    """Create a test image and return base64 encoded data"""
    img = Image.new("RGB", (width, height), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format=format)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


class AssetAPITest(ClientCase):
    """Test cases for the unified /api/asset endpoint"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        reset_group_ids()

        cls.org = Organization.objects.create(name="Test Org", status="ok")

        cls.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
        )

        cls.user.set_verified()
        uoar = UserOrgAffiliationRequest.objects.create(
            user=cls.user, org=cls.org, status="approved"
        )
        uoar.approve()

        cls.facility = Facility.objects.create(
            name="Test Facility",
            org=cls.org,
            status="ok",
            city="Test City",
            country="US",
            zipcode="12345",
            latitude=40.7128,
            longitude=-74.0060,
        )

        cls.network = Network.objects.create(
            name="Test Network", org=cls.org, status="ok", asn=65001
        )

        cls.ix = InternetExchange.objects.create(
            name="Test IX",
            org=cls.org,
            status="ok",
            city="Test City",
            country="US",
        )

        cls.carrier = Carrier.objects.create(
            name="Test Carrier",
            org=cls.org,
            status="ok",
        )

        cls.campus = Campus.objects.create(
            name="Test Campus",
            org=cls.org,
            status="ok",
        )

        cls.facility.campus = cls.campus
        cls.facility.save()

        cls.facility2 = Facility.objects.create(
            name="Test Facility 2",
            org=cls.org,
            status="ok",
            city="Test City",
            country="US",
            zipcode="12345",
            latitude=40.7130,
            longitude=-74.0062,
            campus=cls.campus,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_upload_org_logo(self):
        """Test uploading a logo to an organization"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.org.refresh_from_db()
        self.assertTrue(self.org.logo)

    def test_upload_facility_logo(self):
        """Test uploading a logo to a facility"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/fac/{self.facility.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.facility.refresh_from_db()
        self.assertTrue(self.facility.logo)

    def test_upload_network_logo(self):
        """Test uploading a logo to a network"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/net/{self.network.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.network.refresh_from_db()
        self.assertTrue(self.network.logo)

    def test_upload_ix_logo(self):
        """Test uploading a logo to an internet exchange"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/ix/{self.ix.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.ix.refresh_from_db()
        self.assertTrue(self.ix.logo)

    def test_upload_carrier_logo(self):
        """Test uploading a logo to a carrier"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/carrier/{self.carrier.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.carrier.refresh_from_db()
        self.assertTrue(self.carrier.logo)

    def test_upload_campus_logo(self):
        """Test uploading a logo to a campus"""
        file_data = create_test_image(width=50, height=50)
        response = self.client.post(
            f"/api/asset/campus/{self.campus.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.campus.refresh_from_db()
        self.assertTrue(self.campus.logo)

    def test_get_logo(self):
        """Test retrieving a logo"""
        file_data = create_test_image(width=50, height=50)
        self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        response = self.client.get(f"/api/asset/org/{self.org.id}/logo")

        self.assertEqual(response.status_code, 200)
        self.assertIn("ref_tag", response.data)
        self.assertIn("ref_id", response.data)
        self.assertIn("asset_type", response.data)
        self.assertIn("file_type", response.data)
        self.assertIn("file_data", response.data)
        self.assertIn("created", response.data)
        self.assertIn("updated", response.data)
        self.assertEqual(response.data["ref_tag"], "org")
        self.assertEqual(response.data["ref_id"], self.org.id)
        self.assertEqual(response.data["asset_type"], "logo")
        self.assertEqual(response.data["file_type"], "image/png")

    def test_update_logo(self):
        """Test updating an existing logo"""

        file_data_1 = create_test_image(width=50, height=50)
        self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data_1,
            },
            format="json",
        )

        file_data_2 = create_test_image(width=40, height=40)
        response = self.client.put(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data_2,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_delete_logo(self):
        """Test deleting a logo"""
        file_data = create_test_image(width=50, height=50)
        self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        response = self.client.delete(f"/api/asset/org/{self.org.id}/logo")

        self.assertEqual(response.status_code, 204)
        self.org.refresh_from_db()
        self.assertFalse(self.org.logo)

    def test_invalid_ref_tag(self):
        """Test error when ref_tag is invalid"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/invalid_tag/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ref_tag", str(response.data))

    def test_invalid_entity_id(self):
        """Test error when entity doesn't exist"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            "/api/asset/org/99999/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not found", str(response.data))

    def test_file_size_too_large(self):
        """Test error when file size exceeds limit"""
        file_data = create_test_image(width=5000, height=5000)

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("File size too big", str(response.data))

    def test_image_height_too_large(self):
        """Test error when image height exceeds limit"""
        file_data = create_test_image(width=50, height=100)

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Image height too large", str(response.data))

    def test_invalid_base64(self):
        """Test error with invalid base64 data"""
        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": "not-valid-base64!!!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid base64 encoded data", str(response.data))

    def test_unsupported_file_type(self):
        """Test error with unsupported file type (e.g., GIF)"""
        img = Image.new("RGB", (50, 50), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="GIF")
        buffer.seek(0)
        file_data = base64.b64encode(buffer.read()).decode("utf-8")

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", str(response.data))

    def test_png_file_upload(self):
        """Test uploading PNG file"""
        file_data = create_test_image(width=50, height=50, format="PNG")

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_jpeg_file_upload(self):
        """Test uploading JPEG file"""
        file_data = create_test_image(width=50, height=50, format="JPEG")

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/jpeg",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_file_type_mismatch(self):
        """Test error when declared file_type doesn't match actual file type"""
        file_data = create_test_image(width=50, height=50, format="PNG")

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/jpeg",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("file_type", str(response.data))

    def test_missing_file_type(self):
        """Test error when file_type is not provided"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("file_type", str(response.data))

    def test_invalid_asset_type(self):
        """Test error when asset_type is invalid in URL"""
        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/invalid_type",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("asset_type", str(response.data))

    def test_unauthorized_access(self):
        """Test that unauthenticated users cannot upload logos"""
        self.client.logout()

        file_data = create_test_image(width=50, height=50)

        response = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_get_nonexistent_logo(self):
        """Test getting a logo that doesn't exist"""
        response = self.client.get(f"/api/asset/org/{self.org.id}/logo")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["file_data"])

    def test_delete_nonexistent_logo(self):
        """Test deleting a logo that doesn't exist"""
        response = self.client.delete(f"/api/asset/org/{self.org.id}/logo")

        self.assertEqual(response.status_code, 404)

    @override_settings(API_THROTTLE_RATE_WRITE="2/minute")
    def test_rate_limit_post(self):
        """Test that POST requests are rate limited"""
        file_data = create_test_image(width=50, height=50)

        response1 = self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )
        self.assertEqual(response1.status_code, 201)

        response2 = self.client.put(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )
        self.assertEqual(response2.status_code, 200)

        response3 = self.client.put(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )
        self.assertEqual(response3.status_code, 429)

    @override_settings(API_THROTTLE_RATE_WRITE="2/minute")
    def test_rate_limit_delete(self):
        """Test that DELETE requests are rate limited"""
        file_data = create_test_image(width=50, height=50)

        self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        response1 = self.client.delete(f"/api/asset/org/{self.org.id}/logo")
        self.assertEqual(response1.status_code, 204)

        self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        response2 = self.client.delete(f"/api/asset/org/{self.org.id}/logo")
        self.assertEqual(response2.status_code, 429)

    def test_rate_limit_get_not_throttled(self):
        """Test that GET requests are NOT rate limited"""
        file_data = create_test_image(width=50, height=50)

        self.client.post(
            f"/api/asset/org/{self.org.id}/logo",
            {
                "file_type": "image/png",
                "file_data": file_data,
            },
            format="json",
        )

        for _ in range(5):
            response = self.client.get(f"/api/asset/org/{self.org.id}/logo")
            self.assertEqual(response.status_code, 200)
