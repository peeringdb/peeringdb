import json
import os

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, TestCase

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


class AsnAutomationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # create user and guest group
        guest_group = Group.objects.create(name="guest")
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
            setattr(
                cls,
                username,
                models.User.objects.create_user(username, email, username),
            )
            getattr(cls, username).set_password(username)
            cls.base_org.usergroup.user_set.add(getattr(cls, username))
            user_group.user_set.add(getattr(cls, username))

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
        request = self.factory.post("/affiliate-to-org", data={"asn": asn_ok})
        request.user = self.user_a
        mock_csrf_session(request)
        resp = json.loads(pdbviews.view_affiliate_to_org(request).content)
        self.assertEqual(resp.get("status"), "ok")

        org = models.Organization.objects.get(name="ORG AS9000001")

        # check that support tickets were created
        ticket = models.DeskProTicket.objects.get(
            subject=f"[{settings.RELEASE_ENV}] [ASNAUTO] Organization 'ORG AS9000001', Network 'AS9000001' created"
        )
        self.assertEqual(
            ticket.body,
            self.ticket["asnauto-9000001-org-net-created.txt"].format(
                org_id=org.id, net_id=org.net_set.first().id
            ),
        )

        ticket = models.DeskProTicket.objects.get(
            subject=f"[{settings.RELEASE_ENV}] [ASNAUTO] Ownership claim granted to Org 'ORG AS9000001' for user 'user_a'"
        )
        self.assertEqual(
            ticket.body,
            self.ticket["asnauto-9000001-user-granted-ownership.txt"].format(
                org_id=org.id, net_id=org.net_set.first().id
            ),
        )

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

        ticket = models.DeskProTicket.objects.get(
            subject=f"[{settings.RELEASE_ENV}] [ASNAUTO] Ownership claim granted to Org 'ORG AS{asn_ok}' for user 'user_b'"
        )

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
        org = models.Organization.objects.create(
            status="ok", name="test_claim_ownership ORG"
        )
        net = models.Network.objects.create(
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
        net = models.Network.objects.create(
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
