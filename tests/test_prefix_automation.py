import base64
import datetime
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

import peeringdb_server.models as models
from tests.util import setup_test_data


@override_settings(
    MFA_FORCE_SOFT_START=datetime.datetime.now() + datetime.timedelta(days=1),
    MFA_FORCE_HARD_START=datetime.datetime.now() + datetime.timedelta(days=1),
)
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
            "ixf_ixp_member_list_url": "http://example.com/ixf.json",
        }

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ix_create_auto_approved(self):
        """
        Test that when IX is auto-approved via prefix automation (RDAP + valid IX-F feed),
        NO ticket is created with default setting (False)
        """
        auth = base64.b64encode(b"user_ok:user_ok").decode("utf-8")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {auth}")
        ixf_data = setup_test_data("ixf.prefixauto.valid")
        with patch(
            "peeringdb_server.auto_approval.Importer.fetch", return_value=ixf_data
        ):
            request = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(request.data["status"], "ok")
        self.assertEqual(request.status_code, 201)

        # No ticket should be created when automation succeeds
        subject = f"[PREFIXAUTO] Approval granted to Internet Exchange '{self.payload['name']}' created by user 'user_ok'"
        deskpro = models.DeskProTicket.objects.filter(subject__icontains=subject)
        self.assertFalse(deskpro.exists())

    @override_settings(TICKET_CREATION_PREFIXAUTO=True)
    def test_ix_create_auto_approved_with_ticket_enabled(self):
        """
        Test that when IX is auto-approved (RDAP + valid IX-F feed) and
        TICKET_CREATION_PREFIXAUTO=True, a ticket IS created
        """
        auth = base64.b64encode(b"user_ok:user_ok").decode("utf-8")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {auth}")
        ixf_data = setup_test_data("ixf.prefixauto.valid")
        with patch(
            "peeringdb_server.auto_approval.Importer.fetch", return_value=ixf_data
        ):
            request = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(request.data["status"], "ok")
        self.assertEqual(request.status_code, 201)

        # Ticket should be created when setting is enabled
        subject = f"[PREFIXAUTO] Approval granted to Internet Exchange '{self.payload['name']}' created by user 'user_ok'"
        deskpro = models.DeskProTicket.objects.filter(subject__icontains=subject)
        self.assertTrue(deskpro.exists())

    def test_ix_create_pending(self):
        """
        Test that when IX creation is pending (automation doesn't apply),
        no PREFIXAUTO ticket is created
        """
        auth = base64.b64encode(b"user_pending:user_pending").decode("utf-8")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {auth}")
        request = self.client.post(
            "/api/ix",
            data=self.payload,
            format="json",
        )
        self.assertEqual(request.data["status"], "pending")
        self.assertEqual(request.status_code, 201)

        # No PREFIXAUTO ticket for pending items (automation didn't run)
        subject = "[PREFIXAUTO]"
        deskpro = models.DeskProTicket.objects.filter(subject__icontains=subject)
        self.assertFalse(deskpro.exists())


# ---------------------------------------------------------------------------
# IX-F feed validation tests (issue #1832)
# ---------------------------------------------------------------------------


@override_settings(
    MFA_FORCE_SOFT_START=datetime.datetime.now() + datetime.timedelta(days=1),
    MFA_FORCE_HARD_START=datetime.datetime.now() + datetime.timedelta(days=1),
)
class IXFPrefixAutomationTestCase(TestCase):
    """
    Tests for the IX-F feed validation gate added in issue #1832.

    RDAP is mocked to always pass so these tests focus exclusively on the
    IX-F validation logic.  IX-F feed data is loaded from:
      tests/data/json_members_list/ixf.prefixauto.*.json

    Importer.fetch is always mocked — the ixf_ixp_member_list_url in the
    payload is never fetched; it only needs to be non-empty to pass the
    "URL present" gate in _validate_ixf_feed.
    """

    @classmethod
    def setUpTestData(cls):
        user_group = Group.objects.create(name="user")

        cls.base_org = models.Organization.objects.create(
            name="IXF Prefix Automation Tests", status="ok"
        )

        cls.user_ok = models.User.objects.create_user(
            "ixf_user_ok",
            "hostmaster@uen.org",
            "ixf_user_ok",
            is_superuser=True,
            is_staff=True,
        )
        cls.user_ok.set_password("ixf_user_ok")
        EmailAddress.objects.create(
            user=cls.user_ok,
            email="hostmaster@uen.org",
            verified=True,
            primary=True,
        )
        cls.base_org.usergroup.user_set.add(cls.user_ok)
        user_group.user_set.add(cls.user_ok)

    def setUp(self):
        self.client = APIClient()
        auth = base64.b64encode(b"ixf_user_ok:ixf_user_ok").decode("utf-8")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {auth}")
        self.payload = {
            "org_id": self.base_org.id,
            "name": "testIXF",
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
            "ixf_ixp_member_list_url": "http://example.com/ixf.json",
        }

    def _rdap_mock(self, mock_cls):
        """Configure a RdapLookup mock whose email matches the test user."""
        mock_cls.return_value.get_ip.return_value.emails = ["hostmaster@uen.org"]

    # ------------------------------------------------------------------
    # Failure paths
    # ------------------------------------------------------------------

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_no_ixf_url_goes_pending(self):
        """RDAP passes but no IX-F URL is supplied → IX stays pending."""
        payload = {**self.payload, "ixf_ixp_member_list_url": None}

        with patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap:
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn(
            "no IX-F member list URL provided", response.data["ixf_pending_reason"]
        )

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ixf_url_fetch_error_goes_pending(self):
        """
        RDAP passes, IX-F URL supplied but fetch fails → pending.

        Importer.fetch() never raises — it catches all exceptions internally
        and returns {"pdb_error": <exc>}.  We mirror that here.
        """
        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch(
                "peeringdb_server.auto_approval.Importer.fetch",
                return_value={"pdb_error": "connection refused"},
            ),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("IX-F feed error", response.data["ixf_pending_reason"])

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ixf_url_too_few_asns_goes_pending(self):
        """
        RDAP passes, feed (ixf.prefixauto.too_few_asns) has only 2 unique ASNs
        — below the IXF_PREFIXAUTO_MIN_ASN_COUNT threshold → IX stays pending.
        """
        ixf_data = setup_test_data("ixf.prefixauto.too_few_asns")

        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch(
                "peeringdb_server.auto_approval.Importer.fetch", return_value=ixf_data
            ),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("unique ASN(s)", response.data["ixf_pending_reason"])

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ixf_url_asn_belongs_to_submitting_org_goes_pending(self):
        """
        RDAP passes, feed (ixf.prefixauto.org_conflict) has 3 ASNs but ASN 64500
        belongs to the submitting org → IX stays pending.
        """
        models.Network.objects.create(
            org=self.base_org,
            name="Conflicting Net",
            asn=64500,
            status="ok",
        )
        ixf_data = setup_test_data("ixf.prefixauto.org_conflict")

        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch(
                "peeringdb_server.auto_approval.Importer.fetch", return_value=ixf_data
            ),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("submitting organization", response.data["ixf_pending_reason"])

    # ------------------------------------------------------------------
    # Success paths
    # ------------------------------------------------------------------

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ixf_url_valid_feed_auto_approved(self):
        """
        RDAP passes, feed (ixf.prefixauto.valid) has 3 ASNs none belonging to
        the submitting org → IX is auto-approved and URL is stored on IXLan.
        """
        ixf_data = setup_test_data("ixf.prefixauto.valid")

        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch(
                "peeringdb_server.auto_approval.Importer.fetch", return_value=ixf_data
            ),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "ok")
        self.assertNotIn("ixf_pending_reason", response.data)

        # IX-F URL must be persisted on the IXLan
        ix = models.InternetExchange.objects.get(id=response.data["id"])
        self.assertEqual(
            ix.ixlan.ixf_ixp_member_list_url,
            self.payload["ixf_ixp_member_list_url"],
        )

    @override_settings(TICKET_CREATION_PREFIXAUTO=True)
    def test_ixf_url_valid_feed_creates_prefixauto_ticket(self):
        """
        Full auto-approval with a valid IX-F feed also creates the PREFIXAUTO
        DeskPro ticket when TICKET_CREATION_PREFIXAUTO=True.
        """
        ixf_data = setup_test_data("ixf.prefixauto.valid")

        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch(
                "peeringdb_server.auto_approval.Importer.fetch", return_value=ixf_data
            ),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.data["status"], "ok")
        subject = "[PREFIXAUTO] Approval granted to Internet Exchange 'testIXF' created by user 'ixf_user_ok'"
        self.assertTrue(
            models.DeskProTicket.objects.filter(subject__icontains=subject).exists()
        )

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_rdap_error_goes_pending(self):
        """RDAP lookup raises an exception → IX stays pending regardless of IX-F URL."""
        with patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap:
            mock_rdap.return_value.get_ip.side_effect = Exception("RDAP timeout")
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertNotIn("ixf_pending_reason", response.data)

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ixf_feed_http_error_goes_pending(self):
        """
        RDAP passes, fetch returns a pdb_error (e.g. HTTP 404) → IX stays pending.
        """
        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch(
                "peeringdb_server.auto_approval.Importer.fetch",
                return_value={"pdb_error": "Got HTTP status 404"},
            ),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("IX-F feed error", response.data["ixf_pending_reason"])

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ixf_feed_missing_member_list_goes_pending(self):
        """
        RDAP passes, feed JSON has no member_list key → 0 unique ASNs → pending.
        """
        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch("peeringdb_server.auto_approval.Importer.fetch", return_value={}),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("unique ASN(s)", response.data["ixf_pending_reason"])

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ixf_feed_empty_member_list_goes_pending(self):
        """
        RDAP passes, member_list is empty → 0 unique ASNs → pending.
        """
        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch(
                "peeringdb_server.auto_approval.Importer.fetch",
                return_value={"member_list": []},
            ),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("unique ASN(s)", response.data["ixf_pending_reason"])

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_ixf_feed_null_asnum_goes_pending(self):
        """
        RDAP passes, feed (ixf.prefixauto.null_asnum) has 3 members but all have
        asnum=null → 0 valid unique ASNs → pending.
        """
        ixf_data = setup_test_data("ixf.prefixauto.null_asnum")

        with (
            patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap,
            patch(
                "peeringdb_server.auto_approval.Importer.fetch", return_value=ixf_data
            ),
        ):
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("unique ASN(s)", response.data["ixf_pending_reason"])

    @override_settings(TICKET_CREATION_PREFIXAUTO=False)
    def test_empty_string_ixf_url_goes_pending(self):
        """
        ixf_ixp_member_list_url is an empty string → coerced to None by the
        serializer → treated as missing URL → pending.
        """
        payload = {**self.payload, "ixf_ixp_member_list_url": ""}

        with patch("peeringdb_server.auto_approval.RdapLookup") as mock_rdap:
            self._rdap_mock(mock_rdap)
            response = self.client.post("/api/ix", data=payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertIn(
            "no IX-F member list URL provided", response.data["ixf_pending_reason"]
        )
