import json
import os

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings

import peeringdb_server.inet as pdbinet
import peeringdb_server.models as models
import peeringdb_server.views as pdbviews

from .util import SettingsCase, mock_csrf_session, reset_group_ids

ERR_COULD_NOT_GET_RIR_ENTRY = "This ASN is not assigned by any RIR"
ERR_BOGON_ASN = "ASNs in this range are private or reserved"

RdapLookup_get_asn = pdbinet.RdapLookup.get_asn


def setup_module(module):
    # RDAP LOOKUP OVERRIDE
    # Since we are working with fake ASNs throughout the api tests
    # we need to make sure the RdapLookup client can fake results
    # for us

    # These ASNs will be seen as valid and a prepared json object
    # will be returned for them (data/api/rdap_override.json)
    #
    # ALL ASNs outside of this range will raise a RdapNotFoundError
    ASN_RANGE_OVERRIDE = list(range(9000000, 9000999))

    with open(
        os.path.join(os.path.dirname(__file__), "data", "api", "rdap_override.json"),
    ) as fh:
        pdbinet.RdapLookup.override_result = json.load(fh)

    def get_asn(self, asn):
        if asn in ASN_RANGE_OVERRIDE:
            r = pdbinet.RdapAsn(self.override_result)
            r._parse()
            r._parsed["name"] = "AS%d" % asn
            r._parsed["org_name"] = "ORG AS%d" % asn
            return r
        elif pdbinet.asn_is_bogon(asn):
            return RdapLookup_get_asn(self, asn)
        else:
            raise pdbinet.RdapNotFoundError("Test Not Found")

    pdbinet.RdapLookup.get_asn = get_asn


def teardown_module(module):
    pdbinet.RdapLookup.get_asn = RdapLookup_get_asn


@pytest.mark.xdist_group(name="asn_automation_tests")
class AsnAutomationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # create user and guest group
        Group.objects.create(name="guest")
        user_group = Group.objects.create(name="user")

        with open(
            os.path.join(
                os.path.dirname(__file__), "data", "api", "rdap_override.json"
            ),
        ) as fh:
            data = json.load(fh)
            cls.rdap_63311 = pdbinet.RdapAsn(data)
            cls.rdap_63311_no_name = pdbinet.RdapAsn(data)
            cls.rdap_63311_no_name._parse()
            cls.rdap_63311_no_name._parsed["org_name"] = None
            cls.rdap_63311_no_name._parsed["name"] = None

        cls.ticket = {}

        for ticket_name in [
            "asnauto-9000001-org-net-created.txt",
            "asnauto-9000001-user-granted-ownership.txt",
            "asnauto-9000002-user-requested-ownership.txt",
            "asnauto-9000002-affiliated-user-requested-ownership.txt",
        ]:
            with open(
                os.path.join(os.path.dirname(__file__), "data", "deskpro", ticket_name),
            ) as fh:
                cls.ticket[ticket_name] = fh.read()

        cls.base_org = models.Organization.objects.create(name="ASN Automation Tests")

        for username, email in [
            ("user_a", "Neteng@20c.com"),
            ("user_b", "neteng@other.com"),
            ("user_c", "other@20c.com"),
        ]:
            user = models.User.objects.create_user(username, email, username)
            user.set_password(username)
            setattr(cls, username, user)
            cls.base_org.usergroup.user_set.add(user)
            user_group.user_set.add(user)

            models.EmailAddress.objects.create(
                user=user, email=email, verified=True, primary=True
            )

    def setUp(self):
        self.factory = RequestFactory()

    def test_org_create_from_rdap(self):
        org, created = models.Organization.create_from_rdap(self.rdap_63311, 63311)
        self.assertEqual(org.name, "20C, LLC")
        org_2, created = models.Organization.create_from_rdap(self.rdap_63311, 63311)
        self.assertEqual(org_2.id, org.id)
        org, created = models.Organization.create_from_rdap(
            self.rdap_63311_no_name, 63311
        )
        self.assertEqual(org.name, "AS63311")

    def test_net_create_from_rdap(self):
        net, created = models.Network.create_from_rdap(
            self.rdap_63311, 63311, self.base_org
        )
        self.assertEqual(net.name, "AS-20C")

        net, created = models.Network.create_from_rdap(
            self.rdap_63311, 63312, self.base_org
        )
        self.assertEqual(net.name, "AS-20C !")

        net, created = models.Network.create_from_rdap(
            self.rdap_63311_no_name, 63313, self.base_org
        )
        self.assertEqual(net.name, "AS63313")

    def test_validate_rdap_relationship(self):
        b = self.user_a.validate_rdap_relationship(self.rdap_63311)
        self.assertEqual(b, True)
        b = self.user_b.validate_rdap_relationship(self.rdap_63311)
        self.assertEqual(b, False)
        b = self.user_c.validate_rdap_relationship(self.rdap_63311)
        self.assertEqual(b, False)

    def test_validate_rdap_relationship_secondary_email(self):
        """
        Test that validation works with verified secondary email addresses.

        Fix for issue #1852 where users should be able to use any verified email
        address for RDAP validation, not just their primary email.
        """

        # user_b has primary email "neteng@other.com" which doesn't match RDAP
        b = self.user_b.validate_rdap_relationship(self.rdap_63311)
        self.assertEqual(b, False, "Should not validate with primary email alone")

        # Add a verified secondary email that matches RDAP data
        models.EmailAddress.objects.create(
            user=self.user_b,
            email="neteng@20c.com",
            verified=True,
        )

        # Now validation should succeed with the verified secondary email
        b = self.user_b.validate_rdap_relationship(self.rdap_63311)
        self.assertEqual(b, True, "Should validate with verified secondary email")

        # Test that unverified secondary emails are not checked
        user_d = models.User.objects.create_user("user_d", "user_d@localhost", "user_d")

        # Add an unverified secondary email that matches RDAP
        models.EmailAddress.objects.create(
            user=user_d,
            email="neteng@20c.com",
            verified=False,
        )

        b = user_d.validate_rdap_relationship(self.rdap_63311)
        self.assertEqual(b, False, "Should not validate with unverified email")

    @override_settings(TICKET_CREATION_ASNAUTO=True)
    def test_affiliate(self):
        """
        tests affiliation with non-existant asn
        """
        asn_ok = 9000001
        asn_ok_b = 9000002
        asn_fail = 890000

        reset_group_ids()

        # test 1: test affiliation to asn that has no RiR entry
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_fail})
        request.user = self.user_a
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("asn"), ERR_COULD_NOT_GET_RIR_ENTRY)

        # test 2: test affiliation to asn that has RiR entry and user relationship
        # can be validated (ASN 9000001)
        # Even with TICKET_CREATION_ASNAUTO=True, no tickets created when RDAP validates
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_ok})
        request.user = self.user_a
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        org = models.Organization.objects.get(name="ORG AS9000001")

        net = models.Network.objects.get(asn=asn_ok)
        self.assertEqual(net.name, "AS%d" % asn_ok)
        self.assertEqual(net.org.name, "ORG AS%d" % asn_ok)
        self.assertEqual(
            self.user_a.groups.filter(name=net.org.admin_usergroup.name).exists(), True
        )
        self.assertEqual(net.status, "ok")
        self.assertEqual(net.org.status, "ok")

        # test 3: test affiliation to asn that hsa RiR entry and user relationship
        # cannot be verified (ASN 9000002)
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_ok_b})
        request.user = self.user_b
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        # check that support tickets were created
        ticket = models.DeskProTicket.objects.get(
            subject=f"[{settings.RELEASE_ENV}] User user_b wishes to request ownership of ORG AS9000002"
        )
        self.assertEqual(
            ticket.body,
            self.ticket["asnauto-9000002-user-requested-ownership.txt"].format(
                user_id=self.user_b.id,
                affil_id=self.user_b.affiliation_requests.last().id,
            ),
        )

        net = models.Network.objects.get(asn=asn_ok_b)
        self.assertEqual(net.name, "AS%d" % asn_ok_b)
        self.assertEqual(net.org.name, "ORG AS%d" % asn_ok_b)
        self.assertEqual(
            self.user_b.groups.filter(name=net.org.admin_usergroup.name).exists(), False
        )
        self.assertEqual(net.status, "ok")
        self.assertEqual(net.org.status, "ok")

    @override_settings(TICKET_CREATION_ASNAUTO=True)
    def test_reevaluate(self):
        """
        tests re-check of affiliation requests
        """
        asn_ok = 9000001

        reset_group_ids()

        # test 1: test affiliation to asn that has RiR entry and user relationship
        # cannot be verified (ASN 9000002)
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_ok})
        request.user = self.user_b
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        net = models.Network.objects.get(asn=asn_ok)

        assert not net.org.admin_usergroup.user_set.filter(id=self.user_b.id).exists()

        # simulate email change
        # change to user_a's email, since that email will allow the ownership of
        # the org to be granted
        new_email = self.user_a.email

        self.user_a.email = "user_a_updated@localhost"
        self.user_a.save()

        self.user_b.email = new_email
        self.user_b.save()

        self.user_b.recheck_affiliation_requests()

        # Ownership should be granted automatically after email change
        # Even with TICKET_CREATION_ASNAUTO=True, no tickets when RDAP validates
        assert net.org.admin_usergroup.user_set.filter(id=self.user_b.id).exists()

    def test_affiliate_limit(self):
        """
        test affiliation request limit (fail when there is n pending
        affiliations for a user)
        """

        for i in range(0, settings.MAX_USER_AFFILIATION_REQUESTS + 1):
            # For this test we need the orgs to actually exist

            models.Organization.objects.create(name=f"AFFILORG{i}", status="ok")
            request = self.factory.post(
                "/affiliate-to-org", data={"org": f"AFFILORG{i}"}
            )
            request.user = self.user_b
            mock_csrf_session(request)
            print("\n")
            print(i)
            response = pdbviews.view_affiliate_to_org(request)

            print(response.content)
            if i < settings.MAX_USER_AFFILIATION_REQUESTS:
                assert response.status_code == 200
            else:
                assert response.status_code == 400

    def test_cancel_affiliation_request(self):
        """
        tests user canceling a pending affiliation request
        """

        request = self.factory.post("/affiliate-to-org", data={"org": "AFFILORG"})
        request.user = self.user_b
        mock_csrf_session(request)
        response = pdbviews.view_affiliate_to_org(request)

        assert response.status_code == 200

        affiliation_request = self.user_b.pending_affiliation_requests.first()

        assert affiliation_request

        request = self.factory.post(
            f"/cancel-affiliation-request/{affiliation_request.id}/"
        )
        request.user = self.user_b
        mock_csrf_session(request)
        response = pdbviews.cancel_affiliation_request(request, affiliation_request.id)

        assert response.status_code == 302
        assert self.user_b.pending_affiliation_requests.count() == 0

    def test_deny_cancel_other_affiliation_request(self):
        """
        users should never be allowed to cancel other user's affiliation requests
        """

        request = self.factory.post("/affiliate-to-org", data={"org": "AFFILORG"})
        request.user = self.user_b
        mock_csrf_session(request)
        response = pdbviews.view_affiliate_to_org(request)

        assert response.status_code == 200

        affiliation_request = self.user_b.pending_affiliation_requests.first()

        assert affiliation_request

        request = self.factory.post(
            f"/cancel-affiliation-request/{affiliation_request.id}/"
        )
        request.user = self.user_a
        mock_csrf_session(request)
        response = pdbviews.cancel_affiliation_request(request, affiliation_request.id)

        assert response.status_code == 404
        assert self.user_b.pending_affiliation_requests.count() == 1

    def test_affil_already_affiliated(self):
        """
        When a user needs pdb admin approval of an affiliation an deskpro
        ticket is created.

        When the user is already affiliated to another organization, there is
        extra information appended to that ticket, such as what organizations
        the user is already affiliated to.
        """

        org_1 = models.Organization.objects.create(
            name="Org with admin user", status="ok"
        )
        org_2 = models.Organization.objects.create(
            name="Org with normal user", status="ok"
        )
        org_1.admin_usergroup.user_set.add(self.user_b)
        org_2.usergroup.user_set.add(self.user_b)

        request = self.factory.post("/affiliate-to-org", data={"asn": 9000002})
        request.user = self.user_b
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        ticket = models.DeskProTicket.objects.get(
            subject=f"[{settings.RELEASE_ENV}] User user_b wishes to request ownership of ORG AS9000002"
        )

        self.assertEqual(
            ticket.body,
            self.ticket[
                "asnauto-9000002-affiliated-user-requested-ownership.txt"
            ].format(
                admin_org_id=org_1.id,
                user_org_id=org_2.id,
                user_id=self.user_b.id,
                affil_id=self.user_b.affiliation_requests.first().id,
            ),
        )

    def test_affiliate_to_bogon_asn(self):
        """
        tests affiliation with non-existant asn
        """
        asns = []
        for a, b in pdbinet.BOGON_ASN_RANGES:
            asns.extend([a, b])

        for asn in asns:
            request = self.factory.post("/affiliate-to-org", data={"asn": asn})

            request.user = self.user_a
            mock_csrf_session(request)
            resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
            self.assertEqual(resp.get("asn"), ERR_BOGON_ASN)

    def test_claim_ownership(self):
        """
        tests ownership to org via asn RiR validation
        """
        reset_group_ids()
        org = models.Organization.objects.create(
            status="ok", name="test_claim_ownership ORG"
        )
        models.Network.objects.create(
            status="ok", name="test_claim_ownership NET", asn=9000100, org=org
        )

        request = self.factory.post("/request-ownership", data={"id": org.id})
        request.user = self.user_a
        mock_csrf_session(request)

        resp = json.loads(pdbviews.view_request_ownership(request).content)
        self.assertEqual(resp.get("status"), "ok")
        self.assertEqual(resp.get("ownership_status"), "approved")
        self.assertEqual(
            self.user_a.groups.filter(name=org.admin_usergroup.name).exists(), True
        )

    def test_claim_ownership_validation_failure(self):
        """
        test failure to claim ownership to org via asn RiR validation
        """
        org = models.Organization.objects.create(
            status="ok", name="test_claim_ownership ORG"
        )
        models.Network.objects.create(
            status="ok", name="test_claim_ownership NET", asn=9000100, org=org
        )

        request = self.factory.post("/request-ownership", data={"id": org.id})
        request.user = self.user_b
        mock_csrf_session(request)

        resp = json.loads(pdbviews.view_request_ownership(request).content)
        self.assertEqual(resp.get("status"), "ok")
        self.assertEqual(resp.get("ownership_status"), "pending")
        self.assertEqual(
            self.user_b.groups.filter(name=org.admin_usergroup.name).exists(), False
        )

    @override_settings(TICKET_CREATION_ASNAUTO=True)
    def test_affiliate_with_tickets_enabled(self):
        """
        Test affiliation flow with TICKET_CREATION_ASNAUTO=True
        Verifies that tickets ARE created when setting is enabled
        """
        asn_ok = 9000600
        reset_group_ids()

        # Clear any existing tickets
        models.DeskProTicket.objects.all().delete()

        # Affiliate with valid RDAP that matches user email
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_ok})
        request.user = self.user_a
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        org = models.Organization.objects.get(name=f"ORG AS{asn_ok}")
        net = models.Network.objects.get(asn=asn_ok)

        # Verify org/net created and user granted ownership
        self.assertEqual(net.status, "ok")
        self.assertEqual(net.org.status, "ok")
        self.assertTrue(
            self.user_a.groups.filter(name=net.org.admin_usergroup.name).exists()
        )

        # With TICKET_CREATION_ASNAUTO=True, tickets should NOT be created
        # when RDAP validates (automation succeeds) - this is by design in signals.py
        # Tickets are only created when automation FAILS and needs manual review
        self.assertEqual(
            models.DeskProTicket.objects.filter(subject__contains="[ASNAUTO]").count(),
            0,
        )

    @override_settings(TICKET_CREATION_ASNAUTO=False)
    def test_ticket_creation_disabled_by_default(self):
        """
        Test that tickets are NOT created when automation succeeds
        and TICKET_CREATION_ASNAUTO is False (default)
        """
        asn_ok = 9000500
        reset_group_ids()

        # Affiliate with valid RDAP that matches user email
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_ok})
        request.user = self.user_a
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        # Verify org/net were created and user was granted ownership
        net = models.Network.objects.get(asn=asn_ok)
        self.assertEqual(net.status, "ok")
        self.assertEqual(net.org.status, "ok")
        self.assertTrue(
            self.user_a.groups.filter(name=net.org.admin_usergroup.name).exists()
        )

        # Verify NO tickets were created
        self.assertEqual(
            models.DeskProTicket.objects.filter(subject__contains="[ASNAUTO]").count(),
            0,
        )

    def test_ticket_creation_when_automation_fails(self):
        """
        Test that tickets ARE created when automation fails
        (user email doesn't match RDAP)
        """
        asn_fail = 9000501
        reset_group_ids()

        # Clear any existing tickets
        models.DeskProTicket.objects.all().delete()

        # Affiliate with valid RDAP but user email doesn't match
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_fail})
        request.user = self.user_b
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        # Verify org/net were created
        net = models.Network.objects.get(asn=asn_fail)
        self.assertEqual(net.status, "ok")
        self.assertEqual(net.org.status, "ok")

        # User should NOT be granted ownership (needs manual review)
        self.assertFalse(
            self.user_b.groups.filter(name=net.org.admin_usergroup.name).exists()
        )

        # Verify ticket WAS created for manual review
        self.assertTrue(
            models.DeskProTicket.objects.filter(
                subject__contains=f"User {self.user_b.username} wishes to request ownership"
            ).exists()
        )

    @override_settings(TICKET_CREATION_ASNAUTO=True)
    def test_ticket_creation_enabled_via_setting(self):
        """
        Test that tickets ARE created when TICKET_CREATION_ASNAUTO is True,
        even when automation succeeds
        """
        asn_ok = 9000502
        reset_group_ids()

        # Clear any existing tickets
        models.DeskProTicket.objects.all().delete()

        # Affiliate with valid RDAP that matches user email
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_ok})
        request.user = self.user_a
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        # Verify org/net were created and user was granted ownership
        net = models.Network.objects.get(asn=asn_ok)
        self.assertEqual(net.status, "ok")
        self.assertEqual(net.org.status, "ok")
        self.assertTrue(
            self.user_a.groups.filter(name=net.org.admin_usergroup.name).exists()
        )

        # No tickets created when automation succeeds (RDAP validates)
        # Tickets are only created when automation fails and needs manual review
        self.assertEqual(
            models.DeskProTicket.objects.filter(subject__contains="[ASNAUTO]").count(),
            0,
        )

    # Issue #1877: Auto-undelete network tests

    def test_undelete_network_rdap_validated(self):
        """
        Test that a user with RDAP-validated email can claim a deleted network.
        The network should be undeleted and assigned to a new organization.
        """
        asn = 9000010

        reset_group_ids()

        # Create a network and then delete it
        old_org = models.Organization.objects.create(name="Old Org for Undelete Test")
        network = models.Network.objects.create(
            asn=asn, name="Old Network", org=old_org, status="ok"
        )
        old_network_id = network.id

        # Delete the network
        network.delete()
        network.refresh_from_db()
        self.assertEqual(network.status, "deleted")

        # User with RDAP-validated email requests affiliation
        request = self.factory.post("/affiliate-to-org", data={"asn": asn})
        # user_a has Neteng@20c.com which matches RDAP
        request.user = self.user_a
        mock_csrf_session(request)

        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        # Network should be undeleted
        network.refresh_from_db()
        self.assertEqual(network.status, "ok")
        # Same record, not new
        self.assertEqual(network.id, old_network_id)

        # Network should be assigned to NEW organization (from RDAP)
        self.assertNotEqual(network.org.id, old_org.id)
        self.assertEqual(network.org.name, f"ORG AS{asn}")

        # User should be admin of the new org (RDAP validated = auto-approved)
        self.assertTrue(
            self.user_a.groups.filter(name=network.org.admin_usergroup.name).exists()
        )

    def test_undelete_network_rdap_not_validated(self):
        """
        Test that a user without RDAP validation cannot auto-claim a deleted network.
        The request is denied and the network stays deleted.
        """
        asn = 9000011

        reset_group_ids()

        # Create and delete a network
        old_org = models.Organization.objects.create(
            name="Old Org for Non-Validated Test"
        )
        network = models.Network.objects.create(
            asn=asn, name="Old Network NV", org=old_org, status="ok"
        )

        network.delete()
        network.refresh_from_db()
        self.assertEqual(network.status, "deleted")

        # User without RDAP-validated email requests affiliation
        request = self.factory.post("/affiliate-to-org", data={"asn": asn})

        # user_b has neteng@other.com which does NOT match RDAP
        request.user = self.user_b
        mock_csrf_session(request)

        pdbviews.view_affiliate_to_org(request)

        # Network should remain deleted - RDAP validation failed
        network.refresh_from_db()
        self.assertEqual(network.status, "deleted")

    def test_undelete_preserves_network_id(self):
        """
        Test that undelete preserves the original network ID (history preserved).
        """
        asn = 9000013

        reset_group_ids()

        old_org = models.Organization.objects.create(name="Old Org for ID Test")
        network = models.Network.objects.create(
            asn=asn, name="ID Test Network", org=old_org, status="ok"
        )
        original_id = network.id

        network.delete()

        # Request affiliation
        request = self.factory.post("/affiliate-to-org", data={"asn": asn})
        request.user = self.user_a
        mock_csrf_session(request)

        pdbviews.view_affiliate_to_org(request)

        # Verify same network ID
        network.refresh_from_db()
        self.assertEqual(network.id, original_id)
        self.assertEqual(network.status, "ok")

    def test_undelete_child_objects_remain_deleted(self):
        """
        Test that child objects (poc_set) remain soft-deleted after network undelete.
        The new owner rebuilds from scratch.
        """
        asn = 9000014

        reset_group_ids()

        old_org = models.Organization.objects.create(name="Old Org for Child Test")
        network = models.Network.objects.create(
            asn=asn, name="Child Test Network", org=old_org, status="ok"
        )

        # Create a contact for the network
        contact = models.NetworkContact.objects.create(
            network=network,
            role="Abuse",
            name="Old Contact",
            email="old@example.com",
            status="ok",
        )

        # Delete the network (which deletes the contact too)
        network.delete()
        contact.refresh_from_db()
        self.assertEqual(contact.status, "deleted")

        # Request affiliation to undelete
        request = self.factory.post("/affiliate-to-org", data={"asn": asn})
        request.user = self.user_a
        mock_csrf_session(request)

        pdbviews.view_affiliate_to_org(request)

        # Network should be undeleted
        network.refresh_from_db()
        self.assertEqual(network.status, "ok")

        # But contact should still be deleted
        contact.refresh_from_db()
        self.assertEqual(contact.status, "deleted")

    @override_settings(AUTO_UNDELETE_NETWORK=False)
    def test_undelete_disabled_returns_error(self):
        """
        Test that when AUTO_UNDELETE_NETWORK is disabled, the original
        error message is returned for deleted networks.
        """
        asn = 9000012

        reset_group_ids()

        # Create and delete a network
        old_org = models.Organization.objects.create(name="Old Org for Disabled Test")
        network = models.Network.objects.create(
            asn=asn, name="Old Network Disabled", org=old_org, status="ok"
        )

        network.delete()
        network.refresh_from_db()
        self.assertEqual(network.status, "deleted")

        # Request affiliation - should be rejected
        request = self.factory.post("/affiliate-to-org", data={"asn": asn})
        request.user = self.user_a
        mock_csrf_session(request)

        resp = pdbviews.view_affiliate_to_org(request)
        self.assertEqual(resp.status_code, 400)

        data = json.loads(resp.content)
        self.assertIn("non_field_errors", data)
        self.assertIn("deleted", data["non_field_errors"][0].lower())

        # Network should still be deleted
        network.refresh_from_db()
        self.assertEqual(network.status, "deleted")


class TestTutorialMode(SettingsCase):
    settings = {"TUTORIAL_MODE": True}

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_affiliate_to_bogon_asn(self):
        """
        tests affiliation with non-existant bogon asn
        with tutorial mode enabled those should be allowed
        """
        user = get_user_model().objects.create_user(
            username="user_a", email="user_a@localhost", password="user_a"
        )
        asns = []
        for a, b in pdbinet.TUTORIAL_ASN_RANGES:
            asns.extend([a, b])

        for asn in asns:
            request = self.factory.post("/affiliate-to-org", data={"asn": asn})

            request.user = user
            mock_csrf_session(request)
            resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
            self.assertEqual(resp.get("status"), "ok")
