import datetime
import json
import re
import urllib

import pytest
from django.conf import settings as dj_settings
from django.contrib.admin.sites import AdminSite
from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from django_grainy.models import GroupPermission
from django_otp.plugins.otp_email.models import EmailDevice
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_security_keys.models import SecurityKey
from grainy.const import PERM_CRUD

import peeringdb_server.admin as admin
import peeringdb_server.models as models


class AdminTests(TestCase):
    """
    Test peeringdb django admin functionality
    """

    asn_count = 0

    MFA_INLINE_HEADINGS = (
        "User has these TOTP devices",
        "User has these Webauthn Security Keys",
        "User has these Backup Token sets",
        "Email one-time password (auto-provisioned)",
    )

    MFA_INLINE_PREFIXES = (
        "totpdevice_set",
        "webauthn_security_keys",
        "staticdevice_set",
        "emaildevice_set",
    )

    # none of the four MFA device models is a peeringdb_server model, so
    # admin.PERMISSION_APP_LABELS does not cover them and a non-superuser is
    # shown none of these sections without their own grants (#2009)
    MFA_DEVICE_APP_LABELS = [
        "otp_totp",
        "django_security_keys",
        "otp_static",
        "otp_email",
    ]

    BACKUP_TOKENS = ("aaaa1111", "bbbb2222", "cccc3333")

    EMAIL_OTP_TOKEN = "998877"

    @classmethod
    def entity_data(cls, org, tag):
        kwargs = {
            "name": f"{org.name} {tag}",
            "status": "ok",
            "org": org,
            "website": "",
        }
        if tag == "net":
            cls.asn_count += 1
            kwargs.update(asn=cls.asn_count)
        return kwargs

    @classmethod
    def setUpTestData(cls):
        cls.entities = {}

        # set up organizations
        cls.entities["org"] = [
            org
            for org in [
                models.Organization.objects.create(name="Org %d" % i, status="ok")
                for i in range(0, 9)
            ]
        ]

        # set up a network,facility and ix under each org
        for tag in ["ix", "net", "fac", "carrier", "campus"]:
            cls.entities[tag] = [
                models.REFTAG_MAP[tag].objects.create(**cls.entity_data(org, tag))
                for org in cls.entities["org"]
            ]

        # create a user under each org
        cls.entities["user"] = [
            models.User.objects.create_user(
                username="user " + org.name,
                email="%s@localhost" % org.name,
                first_name="First",
                last_name="Last",
            )
            for org in cls.entities["org"]
        ]
        i = 0
        for user in cls.entities["user"]:
            cls.entities["org"][i].usergroup.user_set.add(user)
            i += 1

        cls.admin_user = models.User.objects.create_user(
            username="admin",
            email="admin@localhost",
            first_name="admin",
            last_name="admin",
        )
        cls.admin_user.is_superuser = True
        cls.admin_user.is_staff = True
        cls.admin_user.save()
        cls.admin_user.set_password("admin")
        cls.admin_user.save()

        # user and group for read-only access to /cp
        cls.readonly_admin = models.User.objects.create_user(
            username="ro_admin",
            email="ro_admin@localhost",
            password="admin",
            is_staff=True,
        )
        readonly_group = Group.objects.create(name="readonly")
        for app_label in admin.PERMISSION_APP_LABELS + cls.MFA_DEVICE_APP_LABELS:
            GroupPermission.objects.create(
                group=readonly_group, namespace=app_label, permission=0x01
            )
        readonly_group.user_set.add(cls.readonly_admin)

        # set up some ixlans
        cls.entities["ixlan"] = [ix.ixlan for ix in cls.entities["ix"]]

        # set up a prefix
        cls.entities["ixpfx"] = [
            models.IXLanPrefix.objects.create(
                ixlan=cls.entities["ixlan"][0],
                protocol="IPv4",
                prefix="207.41.110.0/24",
                status="ok",
            )
        ]

        # set up some netixlans
        cls.entities["netixlan"] = [
            models.NetworkIXLan.objects.create(
                network=cls.entities["net"][0],
                ixlan=cls.entities["ixlan"][0],
                ipaddr4=addr,
                status="ok",
                asn=cls.entities["net"][0].asn,
                speed=1000,
            )
            for addr in ["207.41.110.37", "207.41.110.38", "207.41.110.39"]
        ]

        # set up carrier facility presences
        cls.entities["carrierfac"] = [
            models.CarrierFacility.objects.create(
                carrier=cls.entities["carrier"][0],
                facility=cls.entities["fac"][0],
                status="ok",
            )
        ]

    def setUp(self):
        self.factory = RequestFactory()

    def _userpermission_payload(self, user, org, grainy_forms=1, initial_forms=0):
        """
        Payload for the UserPermission admin change form that puts `user` in
        `org`'s admin group -- override `groups` for any other role.
        `grainy_forms` is the number of permission inline forms submitted -- 0
        models a client that posts only the groups field. `initial_forms` is
        how many of those are existing rows rendered back by the change page.
        """

        payload = {
            "groups": org.admin_usergroup.id,
            "affiliation_requests-TOTAL_FORMS": 0,
            "affiliation_requests-INITIAL_FORMS": 0,
            "affiliation_requests-MIN_NUM_FORMS": 0,
            "affiliation_requests-MAX_NUM_FORMS": 1000,
            "affiliation_requests-__prefix__-org": "",
            "affiliation_requests-__prefix__-org_name": "",
            "affiliation_requests-__prefix__-asn": "",
            "affiliation_requests-__prefix__-status": "",
            "affiliation_requests-__prefix__-user": user.id,
            "affiliation_requests-__prefix__-id": "",
            "grainy_permissions-TOTAL_FORMS": grainy_forms,
            "grainy_permissions-INITIAL_FORMS": initial_forms,
            "grainy_permissions-MIN_NUM_FORMS": 0,
            "grainy_permissions-MAX_NUM_FORMS": 1000,
            "grainy_permissions-__prefix__-namespace": "",
            "grainy_permissions-__prefix__-user": user.id,
            "grainy_permissions-__prefix__-id": "",
            "_continue": "Save and continue editing",
        }

        return payload

    def test_views(self):
        """
        Test that all views are still functional

        Note: this only tests for HTTP status and is a quick and dirty
        way that none of the views got broken for GET requests. This will
        need to be replaced by something more extensive
        """

        m = [
            models.Facility,
            models.InternetExchange,
            models.Network,
            models.Organization,
            models.User,
        ]

        c = Client()
        c.login(username="admin", password="admin")
        for model in m:
            url = f"/cp/{model._meta.app_label}/{model._meta.model_name}/"
            response = c.get(url, follow=True)
            self.assertEqual(response.status_code, 200)

            url_add = "%sadd" % url
            response = c.get(url_add, follow=True)
            self.assertEqual(response.status_code, 200)

            url_id = f"{url}{model.objects.first().id}"
            response = c.get(url_id, follow=True)
            self.assertEqual(response.status_code, 200)

    def test_org_merge(self):
        """
        Test the org merge functionality, which should merge 1 or more
        organizations into a target organization, moving all entities
        to the target organization
        """
        request = self.factory.post("/cp")
        request.user = None
        # TEST 1

        # merge orgs 1 and 2 into org 0
        t_org = self.entities["org"][0]
        result = admin.merge_organizations(self.entities["org"][1:3], t_org, request)

        # check that all entities moved
        for tag in ["ix", "net", "fac", "campus", "carrier"]:
            for ent in self.entities[tag][0:3]:
                ent.refresh_from_db()
                self.assertEqual(ent.org, t_org)

        self.assertEqual(result["campus"], 2)
        self.assertEqual(result["carier"], 2)

        # check that all users moved
        i = 1
        for user in self.entities["user"][1:3]:
            org = self.entities["org"][i]
            self.assertEqual(user.is_org_member(t_org), True)
            self.assertEqual(user.is_org_admin(t_org), False)
            self.assertEqual(user.is_org_member(org), False)
            self.assertEqual(user.is_org_admin(org), False)
            i += 1

        # check that all merged orgs are deleted
        for org in self.entities["org"][1:3]:
            org.refresh_from_db()
            self.assertEqual(org.status, "deleted")

        # check that target org is still in tact
        t_org.refresh_from_db()
        self.assertEqual(t_org.status, "ok")

        # TEST 2 - Don't allow merging of target org into target org
        with pytest.raises(ValueError):
            admin.merge_organizations([t_org], t_org, request)

    def test_org_unmerge(self):
        """
        Test undoing an organization merge
        """

        request = self.factory.post("/cp")
        request.user = None

        # merge orgs 4 and 5 into org 3
        t_org = self.entities["org"][3]
        admin.merge_organizations(self.entities["org"][4:6], t_org, request)

        print(t_org)

        # check that merge log exists
        merges = models.OrganizationMerge.objects.filter(to_org=t_org)
        self.assertEqual(merges.count(), 2)

        # undo merges
        i = 4
        for merge in [m for m in merges]:
            self.assertEqual(merge.from_org, self.entities["org"][i])
            merge.undo()
            i += 1

        # check that all entities moved back
        for tag in ["ix", "net", "fac"]:
            i = 4
            for ent in self.entities[tag][4:6]:
                ent.refresh_from_db()
                self.assertEqual(ent.org, self.entities["org"][i])
                i += 1

        # check that all users moved back
        i = 4
        for user in self.entities["user"][4:6]:
            org = self.entities["org"][i]
            self.assertEqual(user.is_org_member(t_org), False)
            self.assertEqual(user.is_org_admin(t_org), False)
            self.assertEqual(user.is_org_member(org), True)
            self.assertEqual(user.is_org_admin(org), False)
            i += 1

        # check that all merged orgs are deleted
        for org in self.entities["org"][4:6]:
            org.refresh_from_db()
            self.assertEqual(org.status, "ok")

        # check that target org is still in tact
        t_org.refresh_from_db()
        self.assertEqual(t_org.status, "ok")

    def test_org_merge_sponsorships_ok(self):
        """
        Test the org merge functionality when one or more sponsorships
        are involved
        """

        request = self.factory.post("/cp")
        request.user = None
        now = timezone.now()
        end = now + datetime.timedelta(days=10)

        t_org = self.entities["org"][0]
        s_org = self.entities["org"][1]

        sponsor = models.Sponsorship.objects.create(start_date=now, end_date=end)
        sponsor.orgs.add(s_org)

        # merge orgs 1 into org 0
        admin.merge_organizations([s_org], t_org, request)

        # check that sponsorship has been transfered

        assert sponsor.orgs.filter(pk=t_org.pk).exists()
        assert not sponsor.orgs.filter(pk=s_org.pk).exists()

        # test undo
        merges = models.OrganizationMerge.objects.filter(to_org=t_org)
        for merge in merges:
            merge.undo()

        # check that sponsorship has been reverted

        assert not sponsor.orgs.filter(pk=t_org.pk).exists()
        assert sponsor.orgs.filter(pk=s_org.pk).exists()

    def test_org_merge_sponsorships_block(self):
        """
        Test the org merge functionality when one or more sponsorships
        are involved - block if both source and target org have different
        active sponsorships going
        """

        request = self.factory.post("/cp")
        request.user = None

        now = timezone.now()
        end = now + datetime.timedelta(days=10)
        t_org = self.entities["org"][0]
        s_org = self.entities["org"][1]

        sponsor_s = models.Sponsorship.objects.create(start_date=now, end_date=end)
        sponsor_s.orgs.add(s_org)

        sponsor_t = models.Sponsorship.objects.create(start_date=now, end_date=end)
        sponsor_t.orgs.add(t_org)

        # merge orgs 1 into org 0
        admin.merge_organizations([s_org], t_org, request)

        assert sponsor_s.orgs.filter(pk=s_org.pk).exists()
        assert not sponsor_s.orgs.filter(pk=t_org.pk).exists()
        assert sponsor_t.orgs.filter(pk=t_org.pk).exists()

    def test_org_merge_sponsorships_block_2(self):
        """
        Test the org merge functionality when one or more sponsorships
        are involved - block if source orgs have different active sponsorships
        going
        """

        request = self.factory.post("/cp")
        request.user = None

        now = timezone.now()
        end = now + datetime.timedelta(days=10)
        t_org = self.entities["org"][0]
        s_org_a = self.entities["org"][1]
        s_org_b = self.entities["org"][2]

        sponsor_a = models.Sponsorship.objects.create(start_date=now, end_date=end)
        sponsor_a.orgs.add(s_org_a)

        sponsor_b = models.Sponsorship.objects.create(start_date=now, end_date=end)
        sponsor_b.orgs.add(s_org_b)

        # merge orgs 1 into org 0
        admin.merge_organizations([s_org_a, s_org_b], t_org, request)

        assert sponsor_a.orgs.filter(pk=s_org_a.pk).exists()
        assert sponsor_b.orgs.filter(pk=s_org_b.pk).exists()

        assert not sponsor_a.orgs.filter(pk=t_org.pk).exists()
        assert not sponsor_b.orgs.filter(pk=t_org.pk).exists()

    def test_commandline_tool(self):
        c = Client()
        c.login(username="admin", password="admin")

        # test form that lets user select which command run
        url = "/cp/peeringdb_server/commandlinetool/prepare"
        response = c.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        for i, n in models.COMMANDLINE_TOOLS:
            assert f'<option value="{i}">{n}</option>' in response.content.decode()

    def test_commandline_tool_renumber_lans(self):
        # test the form that runs the renumer ip space tool
        c = Client()
        c.login(username="admin", password="admin")

        # test renumber lans command form
        data = {"tool": "pdb_renumber_lans"}
        url = "/cp/peeringdb_server/commandlinetool/prepare/"
        response = c.post(url, data, follow=True)
        cont = response.content.decode("utf-8")
        assert response.status_code == 200
        assert "Old prefix" in cont
        assert "Exchange" in cont

        # test post to renumber lans command form (preview)
        data = {
            "tool": "pdb_renumber_lans",
            "exchange": self.entities["ix"][0].id,
            "old_prefix": "207.41.110.0/24",
            "new_prefix": "207.41.111.0/24",
        }
        url = "/cp/peeringdb_server/commandlinetool/preview/"
        response = c.post(url, data, follow=True)
        cont = response.content.decode("utf-8")

        assert response.status_code == 200
        assert "[pretend]" in cont
        assert "207.41.110.0/24 -> 207.41.111.0/24" in cont
        assert "AS1 207.41.110.37 -> 207.41.111.37" in cont
        assert "AS1 207.41.110.38 -> 207.41.111.38" in cont
        assert "AS1 207.41.110.39 -> 207.41.111.39" in cont

        # test post to renumber lans command form
        data = {
            "tool": "pdb_renumber_lans",
            "exchange": self.entities["ix"][0].id,
            "old_prefix": "207.41.110.0/24",
            "new_prefix": "207.41.111.0/24",
        }
        url = "/cp/peeringdb_server/commandlinetool/run/"
        response = c.post(url, data, follow=True)

        cont = response.content.decode("utf-8")
        assert response.status_code == 200
        assert "[pretend]" not in cont
        assert "207.41.110.0/24 -> 207.41.111.0/24" in cont
        assert "AS1 207.41.110.37 -> 207.41.111.37" in cont
        assert "AS1 207.41.110.38 -> 207.41.111.38" in cont
        assert "AS1 207.41.110.39 -> 207.41.111.39" in cont

        for netixlan in self.entities["netixlan"]:
            netixlan.refresh_from_db()

        self.assertEqual(str(self.entities["netixlan"][0].ipaddr4), "207.41.111.37")
        self.assertEqual(str(self.entities["netixlan"][1].ipaddr4), "207.41.111.38")
        self.assertEqual(str(self.entities["netixlan"][2].ipaddr4), "207.41.111.39")

    def test_netixlan_inline(self):
        """
        test that inline netixlan admin forms can handle blank
        values in ipaddress fields (#644)

        also tests that duplicate ipaddr values are blocked
        """

        ixlan = self.entities["ixlan"][0]
        netixlan = ixlan.netixlan_set.all()[0]
        netixlan_b = ixlan.netixlan_set.all()[1]

        url = reverse(
            f"admin:{ixlan._meta.app_label}_{ixlan._meta.object_name}_change".lower(),
            args=(ixlan.id,),
        )

        client = Client()
        client.force_login(self.admin_user)

        def post_data(ipaddr4, ipaddr6):
            """
            helper function that builds data to send to
            the ixlan django admin form with inline
            netixlan data
            """

            return {
                # required ixlan form data
                "arp_sponge": "00:0a:95:9d:68:16",
                "ixf_ixp_member_list_url_visible": "Private",
                "ix": ixlan.ix.id,
                "status": ixlan.status,
                "mtu": 1500,
                # required management form data
                "ixpfx_set-TOTAL_FORMS": 0,
                "ixpfx_set-INITIAL_FORMS": 0,
                "ixpfx_set-MIN_NUM_FORMS": 0,
                "ixpfx_set-MAX_NUM_FORMS": 1000,
                "netixlan_set-TOTAL_FORMS": 1,
                "netixlan_set-INITIAL_FORMS": 1,
                "netixlan_set-MIN_NUM_FORMS": 0,
                "netixlan_set-MAX_NUM_FORMS": 1000,
                # inline netixlan data
                "netixlan_set-0-ipaddr4": ipaddr4 or "",
                "netixlan_set-0-ipaddr6": ipaddr6 or "",
                "netixlan_set-0-speed": netixlan.speed,
                "netixlan_set-0-network": netixlan.network.id,
                "netixlan_set-0-ixlan": ixlan.id,
                "netixlan_set-0-id": netixlan.id,
                "netixlan_set-0-status": netixlan.status,
                "netixlan_set-0-asn": netixlan.network.asn,
            }

        # test #1: post request to ixlan change operation passing
        # blank values to ipaddress fields

        response = client.post(url, post_data("", ""))
        netixlan.refresh_from_db()
        assert netixlan.ipaddr6 is None
        assert netixlan.ipaddr4 is None

        # test #2: block dupe ipv4

        response = client.post(url, post_data(netixlan_b.ipaddr4, netixlan_b.ipaddr6))
        assert netixlan.ipaddr6 is None
        assert netixlan.ipaddr4 is None
        assert "IP already exists" in response.content.decode("utf-8")

    def test_netixlan_change_side(self):
        """
        test that saving a netixlan from the admin resolves the `*_side`
        choice fields to facilities (#2043)

        they are plain choice fields, so their cleaned value is a facility id
        string - handing that to the fk raises ValueError, which is not a
        ValidationError and so leaves the change view as a 500
        """

        netixlan = self.entities["netixlan"][0]
        fac = self.entities["fac"][0]

        models.InternetExchangeFacility.objects.get_or_create(
            ix=netixlan.ixlan.ix, facility=fac, defaults={"status": "ok"}
        )

        url = reverse(
            f"admin:{netixlan._meta.app_label}_{netixlan._meta.object_name}_change".lower(),
            args=(netixlan.id,),
        )

        client = Client()
        client.force_login(self.admin_user)

        response = client.get(url)
        self.assertEqual(response.status_code, 200)

        # post the form back unchanged apart from ix_side, so the test does
        # not have to track the model's full field list
        data = {
            name: "" if value is None else value
            for name, value in response.context["adminform"].form.initial.items()
        }
        data.update(status=netixlan.status, net_side="", ix_side=fac.id)

        response = client.post(url, data)
        self.assertEqual(response.status_code, 302)

        netixlan.refresh_from_db()
        self.assertEqual(netixlan.ix_side, fac)

    def _run_regex_search(self, model, search_term):
        c = Client()
        c.login(username="admin", password="admin")
        url = reverse(f"admin:peeringdb_server_{model}_changelist")
        search = url + "?q=" + urllib.parse.quote_plus(search_term)
        response = c.get(search)
        content = response.content.decode("utf-8")
        return content

    def test_search_deskprotickets(self):
        # Set up data
        ixf_importer, _ = models.User.objects.get_or_create(username="ixf_importer")
        for i in range(10):
            models.DeskProTicket.objects.create(
                subject=f"test number {i}", body="test", user=ixf_importer
            )

        search_term = "^.*[0-5]$"
        content = self._run_regex_search("deskproticket", search_term)
        print(content)
        expected = [f"test number {i}" for i in range(5)]
        expected_not = [f"test number {i}" for i in range(6, 10)]

        for e in expected:
            assert e in content

        for e in expected_not:
            assert e not in content

    def test_search_ixfimportemails(self):
        for i in range(10):
            models.IXFImportEmail.objects.create(
                subject=f"test number {i}", message="test", recipients="test"
            )
        search_term = "^.*[2-4]$"
        content = self._run_regex_search("ixfimportemail", search_term)
        print(content)
        expected = [f"test number {i}" for i in range(2, 5)]
        expected_not = ["test number 1"] + [f"test number {i}" for i in range(6, 10)]

        for e in expected:
            assert e in content

        for e in expected_not:
            assert e not in content

    def test_search_network_prefixed(self):
        expected = [
            f'Org {i} net</a></th><td class="field-asn">{i + 1}</td>'
            for i in range(0, 9)
        ]
        for i, e in enumerate(expected):
            ## AS prefix
            content_as = self._run_regex_search("network", f"AS{i + 1}")
            assert e in content_as

            for x in set(expected) - {expected[i]}:
                assert x not in content_as

            ## ASN prefix
            content_asn = self._run_regex_search("network", f"ASN{i + 1}")
            assert e in content_asn

            for x in set(expected) - {expected[i]}:
                assert x not in content_asn

    def test_all_views_readonly(self):
        self._test_all_views(
            self.readonly_admin,
            status_add=403,
            status_get_orgmerge=403,
            status_get_orgmerge_undo=403,
            status_get_vq_approve=403,
            status_get_vq_deny=403,
        )

    def test_all_views_superuser(self):
        self._test_all_views(self.admin_user)

    def test_superuser_search(self):
        urls = [
            "/cp/django_security_keys/securitykey/?q=example",
            "/cp/peeringdb_server/commandlinetool/?q=example",
            "/cp/peeringdb_server/datachangeemail/?q=example",
            "/cp/peeringdb_server/datachangenotificationqueue/?q=example",
            "/cp/peeringdb_server/datachangewatchedobject/?q=example",
            "/cp/peeringdb_server/geocoordinatecache/?q=example",
            # "/cp/peeringdb_server/oauthapplication/?q=example",  # This route doesn't exist with the default OAuth provider application under the test environment. Needs to be peeringdb_server.OAuthApplication
            "/cp/peeringdb_server/partnership/?q=example",
            "/cp/peeringdb_server/sponsorship/?q=example",
        ]

        client = Client()
        client.force_login(self.admin_user)
        assert self.admin_user.is_staff

        for url in urls:
            fn = getattr(client, "get")
            response = fn(url, follow=True)
            assert response.status_code == 200

    def _test_all_views(self, user, **kwargs):
        call_command("pdb_generate_test_data", limit=2, commit=True)

        # create a verification queue item we can check
        org = models.Organization.objects.all().first()
        models.Facility.objects.create(
            name="Unverified facility", org=org, status="pending"
        )
        vqitem = models.VerificationQueueItem.objects.all().first()
        assert vqitem

        # create sponsorhship we can check
        sponsorship = models.Sponsorship.objects.create()
        models.SponsorshipOrganization.objects.create(sponsorship=sponsorship, org=org)

        # create partnership we can check
        models.Partnership.objects.create(org=org)

        # create ixlan IX-F import log we can check
        ixfmemberdata = models.IXFMemberData.instantiate(
            ixlan=models.NetworkIXLan.objects.first().ixlan,
            ipaddr4=models.NetworkIXLan.objects.first().ipaddr4,
            ipaddr6=models.NetworkIXLan.objects.first().ipaddr6,
            asn=models.NetworkIXLan.objects.first().network.asn,
        )
        ixfmemberdata.save()

        # create ixlan IX-F import log we can check
        models.IXLanIXFMemberImportLog.objects.create(
            ixlan=models.IXLan.objects.all().first()
        )

        # create user to organization affiliation request
        models.UserOrgAffiliationRequest.objects.create(
            org=org, user=self.readonly_admin
        )

        # create command line tool instance
        models.CommandLineTool.objects.create(
            user=self.readonly_admin, arguments="{}", tool="pdb_renumber_lans"
        )

        # create organization merge
        orgmerge = models.OrganizationMerge.objects.create(
            from_org=org, to_org=models.Organization.objects.all()[1]
        )

        # set up testing for all pdb models that have
        # admin views registered
        ops = ["changelist", "change", "add"]
        classes = [
            models.Organization,
            models.Facility,
            models.InternetExchange,
            models.InternetExchangeFacility,
            models.Network,
            models.NetworkFacility,
            models.NetworkIXLan,
            models.NetworkContact,
            models.IXLan,
            models.IXLanPrefix,
            models.Carrier,
            models.CarrierFacility,
            models.User,
            models.UserOrgAffiliationRequest,
            models.Sponsorship,
            models.Partnership,
            models.IXLanIXFMemberImportLog,
            models.VerificationQueueItem,
            models.CommandLineTool,
            admin.UserPermission,
            models.OrganizationMerge,
            models.IXFMemberData,
        ]

        ignore_add = [
            admin.UserPermission,
            models.OrganizationMerge,
            models.IXFMemberData,
        ]

        ignore_change = []

        # any other urls we want to test
        extra_urls = [
            (
                "/cp/peeringdb_server/organization/org-merge-tool/",
                "get",
                kwargs.get("status_get_orgmerge", 200),
            ),
            (
                reverse(
                    "admin:peeringdb_server_commandlinetool_prepare",
                ),
                "get",
                kwargs.get("status_add", 200),
            ),
            (
                reverse(
                    "admin:peeringdb_server_organizationmerge_actions",
                    args=(orgmerge.id, "undo"),
                ),
                "get",
                kwargs.get("status_get_orgmerge_undo", 200),
            ),
            (
                reverse(
                    "admin:peeringdb_server_verificationqueueitem_actions",
                    args=(vqitem.id, "vq_approve"),
                ),
                "get",
                kwargs.get("status_get_vq_approve", 200),
            ),
            (
                reverse(
                    "admin:peeringdb_server_verificationqueueitem_actions",
                    args=(vqitem.id, "vq_deny"),
                ),
                "get",
                kwargs.get("status_get_vq_deny", 200),
            ),
        ]

        client = Client()
        client.force_login(user)

        assert user.is_staff

        search_str = 'action="/cp/logout/"'

        for op in ops:
            for cls in classes:
                args = None

                if op == "change":
                    # change op required object id

                    args = (cls.objects.all().first().id,)

                    if cls in ignore_change:
                        continue

                elif op == "add":
                    if cls in ignore_add:
                        continue

                url = reverse(
                    f"admin:{cls._meta.app_label}_{cls._meta.object_name}_{op}".lower(),
                    args=args,
                )
                response = client.get(url)
                cont = response.content.decode("utf-8")
                assert response.status_code == kwargs.get(f"status_{op}", 200)
                if response.status_code == 200:
                    print(cont)
                    print(url)
                    assert search_str in cont

        for url, method, status in extra_urls:
            fn = getattr(client, method)
            response = fn(url, follow=True)
            assert response.status_code == status
            if response.status_code == 200:
                assert search_str in cont

        response = client.post(
            reverse("admin:peeringdb_server_commandlinetool_preview"),
            data={"tool": "pdb_fac_merge"},
        )
        assert response.status_code == kwargs.get("status_add", 200)
        if response.status_code == 200:
            assert search_str in cont

    def _test_custom_result_length(self, sz):
        user = self.admin_user
        client = Client()
        client.force_login(user)

        assert user.is_staff

        cls = models.Organization
        url = reverse(
            f"admin:{cls._meta.app_label}_{cls._meta.object_name}_changelist".lower(),
        )
        response = client.get(f"{url}?sz={sz}")
        cont = response.content.decode("utf-8")
        assert response.status_code == 200
        assert cont.count('class="action-checkbox"') == sz

    def test_custom_result_length(self):
        self._test_custom_result_length(1)
        self._test_custom_result_length(3)

    def test_grappelli_autocomplete(self):
        """
        test that grappelli autocomplete works correctly
        as we are overriding it with our own handler that
        respects soft-deleted objects (#664)
        """

        client = Client()
        client.force_login(self.admin_user)

        # these are the handle models we currently have auto-complete
        # fields setup for in admin

        tags = [
            "fac",
            "org",
            "ix",
            "net",
            "ixlan",
            "carrier",
            "campus",
        ]

        # we also do auto complete on user relationships

        check_models = [models.User]

        for reftag in tags:
            check_models.append(models.REFTAG_MAP[reftag])

        for model in check_models:
            instance = model.objects.first()

            # make sure we have at least once instance
            # available

            assert instance

            # determine partial search term (min. 3 chars)

            if model == models.User:
                term = instance.username
            elif hasattr(instance, "name"):
                term = instance.name
            elif model == models.IXLan:
                term = instance.ix.name
            else:
                raise ValueError(f"could not get search term for {model}")

            term = term[:3]
            app_label = model._meta.app_label
            model_name = model._meta.object_name

            # grappelli autocomplete request

            response = client.get(
                "/grappelli/lookup/autocomplete/?"
                f"term={term}&app_label={app_label}&"
                f"model_name={model_name}&query_string="
                "_to_field=id&to_field=id"
            )

            assert response.status_code == 200

            data = json.loads(response.content.decode("utf8"))
            assert len(data)

    def test_protected_entity_errors(self):
        """
        Test that attempting to delete a protected
        entity shows an error message and doesnt raise a 500
        """

        client = Client()
        client.force_login(self.admin_user)

        org = models.Organization.objects.first()

        url = reverse(
            "admin:peeringdb_server_organization_changelist",
        )

        response = client.post(
            url, {"_selected_action": org.id, "action": "soft_delete"}, follow=True
        )

        assert response.status_code == 200

        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "Please confirm deletion of selected objects." in str(messages[0])

    def test_ixpfx_last_prefix_warning(self):
        """
        Test that /cp warns that deleting an exchange's last prefix takes
        the exchange with it (#1717)

        Django's own confirmation pages only list the prefix rows, so
        without this the exchange would disappear unannounced.
        """

        org = models.Organization.objects.create(
            name="Org Last Prefix Admin", status="ok"
        )
        ix = models.InternetExchange.objects.create(
            name="IX Last Prefix Admin", org=org, status="ok"
        )
        ixpfx = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.123.0/24", status="ok"
        )

        client = Client()
        client.force_login(self.admin_user)

        # bulk SOFT DELETE action confirmation page
        response = client.post(
            reverse("admin:peeringdb_server_ixlanprefix_changelist"),
            {"_selected_action": ixpfx.id, "action": "soft_delete"},
            follow=True,
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert any("remove the exchange from PeeringDB" in msg for msg in messages)

        # single object delete confirmation page
        response = client.get(
            reverse("admin:peeringdb_server_ixlanprefix_delete", args=(ixpfx.id,))
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert any("remove the exchange from PeeringDB" in msg for msg in messages)

        # merely opening the ixlan change form deletes nothing, so it says
        # nothing -- the inline warns on the save that carries the flags
        response = client.get(
            reverse("admin:peeringdb_server_ixlan_change", args=(ix.ixlan.id,))
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert not any("remove the exchange from PeeringDB" in msg for msg in messages)

        # none of the confirmation pages changed anything
        ixpfx.refresh_from_db()
        ix.refresh_from_db()

        assert ixpfx.status == "ok"
        assert ix.status == "ok"

        # the inline warns on the save that carries the delete flag, which is
        # also the save that takes the exchange
        response = client.post(
            reverse("admin:peeringdb_server_ixlan_change", args=(ix.ixlan.id,)),
            self.ixlan_form_data(ix.ixlan, [ixpfx], delete=[ixpfx]),
            follow=True,
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert any("remove the exchange from PeeringDB" in msg for msg in messages)

        ix.refresh_from_db()
        assert ix.status == "deleted"

    def test_ixpfx_last_prefix_no_warning_when_another_prefix_remains(self):
        """
        Test that the last-prefix warning is not raised while the exchange
        keeps another prefix (#1717)
        """

        org = models.Organization.objects.create(
            name="Org Two Prefixes Admin", status="ok"
        )
        ix = models.InternetExchange.objects.create(
            name="IX Two Prefixes Admin", org=org, status="ok"
        )
        ixpfx = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.124.0/24", status="ok"
        )
        models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv6", prefix="2001:db8:124::/64", status="ok"
        )

        client = Client()
        client.force_login(self.admin_user)

        response = client.get(
            reverse("admin:peeringdb_server_ixlanprefix_delete", args=(ixpfx.id,))
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert not any("remove the exchange from PeeringDB" in msg for msg in messages)

    def ixlan_form_data(self, ixlan, prefixes, delete=()):
        """
        Build a post body for the ixlan change form, flagging the prefixes
        in `delete` for removal on the prefix inline (#1717)
        """

        data = {
            "arp_sponge": "",
            "ixf_ixp_member_list_url_visible": "Private",
            "ix": ixlan.ix.id,
            "status": ixlan.status,
            "mtu": 1500,
            "ixpfx_set-TOTAL_FORMS": len(prefixes),
            "ixpfx_set-INITIAL_FORMS": len(prefixes),
            "ixpfx_set-MIN_NUM_FORMS": 0,
            "ixpfx_set-MAX_NUM_FORMS": 1000,
            "netixlan_set-TOTAL_FORMS": 0,
            "netixlan_set-INITIAL_FORMS": 0,
            "netixlan_set-MIN_NUM_FORMS": 0,
            "netixlan_set-MAX_NUM_FORMS": 1000,
        }

        for idx, prefix in enumerate(prefixes):
            data.update(
                {
                    f"ixpfx_set-{idx}-id": prefix.id,
                    f"ixpfx_set-{idx}-ixlan": ixlan.id,
                    f"ixpfx_set-{idx}-status": prefix.status,
                    f"ixpfx_set-{idx}-protocol": prefix.protocol,
                    f"ixpfx_set-{idx}-prefix": str(prefix.prefix),
                }
            )
            if prefix in delete:
                data[f"ixpfx_set-{idx}-DELETE"] = "on"

        return data

    def test_ixpfx_last_prefix_warning_for_whole_selection(self):
        """
        Test that /cp warns when one operation removes every prefix an
        exchange has, not just when a row is the last one left (#1717)

        Asked per row, both prefixes report that a sibling remains.
        """

        org = models.Organization.objects.create(name="Org Both Prefixes", status="ok")
        ix = models.InternetExchange.objects.create(
            name="IX Both Prefixes", org=org, status="ok"
        )
        ixpfx4 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.125.0/24", status="ok"
        )
        ixpfx6 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv6", prefix="2001:db8:125::/64", status="ok"
        )

        # neither row is the last one on its own
        assert ixpfx4.is_last_prefix is False
        assert ixpfx6.is_last_prefix is False

        client = Client()
        client.force_login(self.admin_user)

        response = client.post(
            reverse("admin:peeringdb_server_ixlanprefix_changelist"),
            {
                "_selected_action": [ixpfx4.id, ixpfx6.id],
                "action": "soft_delete",
            },
            follow=True,
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        warning = [
            msg for msg in messages if "remove the exchange from PeeringDB" in msg
        ]

        # one warning for the exchange, not one per prefix
        assert len(warning) == 1
        assert "last 2 prefixes" in warning[0]

        # the confirmation page changed nothing
        ix.refresh_from_db()
        assert ix.status == "ok"

    def test_ixpfx_last_prefix_no_warning_for_partial_selection(self):
        """
        Test that selecting only some of an exchange's prefixes raises no
        warning, since the exchange keeps the rest (#1717)
        """

        org = models.Organization.objects.create(
            name="Org Partial Selection", status="ok"
        )
        ix = models.InternetExchange.objects.create(
            name="IX Partial Selection", org=org, status="ok"
        )
        ixpfx4 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.126.0/24", status="ok"
        )
        models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv6", prefix="2001:db8:126::/64", status="ok"
        )

        client = Client()
        client.force_login(self.admin_user)

        response = client.post(
            reverse("admin:peeringdb_server_ixlanprefix_changelist"),
            {"_selected_action": [ixpfx4.id], "action": "soft_delete"},
            follow=True,
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert not any("remove the exchange from PeeringDB" in msg for msg in messages)

    def test_ixpfx_last_prefix_no_warning_when_a_selected_prefix_is_protected(self):
        """
        Test that a protected prefix in the selection suppresses the warning,
        since the delete skips it and the exchange stays listed (#1717)
        """

        org = models.Organization.objects.create(
            name="Org Protected Selection", status="ok"
        )
        ix = models.InternetExchange.objects.create(
            name="IX Protected Selection", org=org, status="ok"
        )
        net = models.Network.objects.create(
            name="Net Protected Selection", org=org, asn=64599, status="ok"
        )
        ixpfx4 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.127.0/24", status="ok"
        )
        ixpfx6 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv6", prefix="2001:db8:127::/64", status="ok"
        )
        models.NetworkIXLan.objects.create(
            network=net,
            ixlan=ix.ixlan,
            asn=net.asn,
            speed=1000,
            status="ok",
            ipaddr4="198.51.127.1",
        )

        assert ixpfx4.deletable is False
        assert ixpfx6.deletable is True

        client = Client()
        client.force_login(self.admin_user)

        response = client.post(
            reverse("admin:peeringdb_server_ixlanprefix_changelist"),
            {
                "_selected_action": [ixpfx4.id, ixpfx6.id],
                "action": "soft_delete",
            },
            follow=True,
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert not any("remove the exchange from PeeringDB" in msg for msg in messages)

    def test_ixpfx_last_prefix_warning_on_ixlan_inline_save(self):
        """
        Test that the ixlan change form warns when the prefixes flagged for
        deletion on the save are all the exchange has (#1717)

        The exchange really does go, which is what made the silence a bug
        rather than a cosmetic gap.
        """

        org = models.Organization.objects.create(name="Org Inline Delete", status="ok")
        ix = models.InternetExchange.objects.create(
            name="IX Inline Delete", org=org, status="ok"
        )
        ixpfx4 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.128.0/24", status="ok"
        )
        ixpfx6 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv6", prefix="2001:504:16:128::/64", status="ok"
        )

        client = Client()
        client.force_login(self.admin_user)

        response = client.post(
            reverse("admin:peeringdb_server_ixlan_change", args=(ix.ixlan.id,)),
            self.ixlan_form_data(ix.ixlan, [ixpfx4, ixpfx6], delete=[ixpfx4, ixpfx6]),
            follow=True,
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        warning = [
            msg for msg in messages if "remove the exchange from PeeringDB" in msg
        ]

        assert len(warning) == 1
        assert "last 2 prefixes" in warning[0]

        ix.refresh_from_db()
        assert ix.status == "deleted"

    def test_ixpfx_last_prefix_no_warning_on_ixlan_inline_partial_save(self):
        """
        Test that the ixlan change form stays silent when the save leaves the
        exchange a prefix (#1717)
        """

        org = models.Organization.objects.create(name="Org Inline Keep", status="ok")
        ix = models.InternetExchange.objects.create(
            name="IX Inline Keep", org=org, status="ok"
        )
        ixpfx4 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.129.0/24", status="ok"
        )
        ixpfx6 = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv6", prefix="2001:504:16:129::/64", status="ok"
        )

        client = Client()
        client.force_login(self.admin_user)

        response = client.post(
            reverse("admin:peeringdb_server_ixlan_change", args=(ix.ixlan.id,)),
            self.ixlan_form_data(ix.ixlan, [ixpfx4, ixpfx6], delete=[ixpfx4]),
            follow=True,
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert not any("remove the exchange from PeeringDB" in msg for msg in messages)

        ix.refresh_from_db()
        ixpfx4.refresh_from_db()

        assert ix.status == "ok"
        assert ixpfx4.status == "deleted"

    def test_ixpfx_last_prefix_no_warning_on_ixlan_inline_protected_save(self):
        """
        Test that flagging a protected prefix for deletion on the ixlan
        inline neither deletes it nor warns about the exchange (#1717)

        The inline has no refusal of its own at the call site: it works
        because `StatusForm.clean` clears `DELETE` before raising, which is
        what keeps the form invalid and `save_formset` unreached. If that
        ordering ever changed, the prefix would be deleted with the warning
        suppressed -- the silent exchange removal this is meant to close.
        """

        org = models.Organization.objects.create(
            name="Org Inline Protected", status="ok"
        )
        ix = models.InternetExchange.objects.create(
            name="IX Inline Protected", org=org, status="ok"
        )
        net = models.Network.objects.create(
            name="Net Inline Protected", org=org, asn=64598, status="ok"
        )
        ixpfx = models.IXLanPrefix.objects.create(
            ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.130.0/24", status="ok"
        )
        models.NetworkIXLan.objects.create(
            network=net,
            ixlan=ix.ixlan,
            asn=net.asn,
            speed=1000,
            status="ok",
            ipaddr4="198.51.130.1",
        )

        assert ixpfx.deletable is False

        client = Client()
        client.force_login(self.admin_user)

        response = client.post(
            reverse("admin:peeringdb_server_ixlan_change", args=(ix.ixlan.id,)),
            self.ixlan_form_data(ix.ixlan, [ixpfx], delete=[ixpfx]),
            follow=True,
        )

        assert response.status_code == 200
        messages = [str(msg) for msg in get_messages(response.wsgi_request)]
        assert not any("remove the exchange from PeeringDB" in msg for msg in messages)

        ixpfx.refresh_from_db()
        ix.refresh_from_db()

        assert ixpfx.status == "ok"
        assert ix.status == "ok"

    def test_delete_user(self):
        """
        Test that deleting with pending UOAR works
        """

        client = Client()

        client.force_login(self.admin_user)

        user = models.User.objects.first()
        models.UserOrgAffiliationRequest.objects.create(
            user=user, asn=1, status="pending"
        )

        # Initiate a delete and check if the object has DoTF protection

        url = f"/cp/peeringdb_server/user/{user.id}/delete/"
        response = client.post(url)

        assert response.status_code == 200
        assert (
            "WARNING! This object currently has DoTF protection:"
            in response.content.decode("utf-8")
        )
        # Delete and check if the object is deleted
        response = client.post(url, {"post": "yes"})

        messages = list(get_messages(response.wsgi_request))

        assert "The user “user Org 0” was deleted successfully." in str(messages[0])

    def test_envvar_choices(self):
        """
        Test that EnvironmentSetting configuration is sane
        """

        field_choices = dict(
            models.EnvironmentSetting._meta.get_field("setting").choices
        )

        for k, v in models.EnvironmentSetting.setting_to_field.items():
            assert v in ["value_str", "value_bool", "value_int"]
            assert k in field_choices

        for k, v in models.EnvironmentSetting.setting_validators.items():
            assert k in field_choices

    def test_org_merge_usergroup_migration(self):
        """
        Test usergroup migration for orgamization merge
        """
        request = self.factory.post("/cp")
        request.user = None
        # TEST 1

        # merge orgs b into org a
        org_a = self.entities["org"][0]
        org_b = self.entities["org"][1]

        # Add users to both orgs usergroups
        user_a = models.User.objects.create(
            username="user_a",
        )

        org_a.admin_usergroup.user_set.add(user_a)
        org_b.admin_usergroup.user_set.add(user_a)

        admin.merge_organizations([org_a], org_b, request)

        assert user_a in org_b.admin_usergroup.user_set.all()
        assert user_a not in org_b.usergroup.user_set.all()

    def test_userpermission(self):
        """
        Test that userpermission is sane
        """

        user_permission = get_user_model().objects.create_user(
            username="user", email="user@localhost", password="user"
        )

        org = models.Organization.objects.create(name="test-org", status="ok")
        org.admin_usergroup.user_set.add(user_permission)
        org.save()

        # assert that user is in org admin usergroup
        assert user_permission in org.admin_usergroup.user_set.all()

        client = Client()
        client.force_login(self.admin_user)

        # Submit post request to save userpermission
        url = reverse(
            "admin:peeringdb_server_userpermission_change", args=[user_permission.id]
        )

        payload = {
            "groups": org.admin_usergroup.id,
            "affiliation_requests-TOTAL_FORMS": 0,
            "affiliation_requests-INITIAL_FORMS": 0,
            "affiliation_requests-MIN_NUM_FORMS": 0,
            "affiliation_requests-MAX_NUM_FORMS": 1000,
            "affiliation_requests-__prefix__-org": "",
            "affiliation_requests-__prefix__-org_name": "",
            "affiliation_requests-__prefix__-asn": "",
            "affiliation_requests-__prefix__-status": "",
            "affiliation_requests-__prefix__-user": user_permission.id,
            "affiliation_requests-__prefix__-id": "",
            "grainy_permissions-TOTAL_FORMS": 1,
            "grainy_permissions-INITIAL_FORMS": 0,
            "grainy_permissions-MIN_NUM_FORMS": 0,
            "grainy_permissions-MAX_NUM_FORMS": 1000,
            "grainy_permissions-0-namespace": f"peeringdb.organization.{org.id}.test",
            "grainy_permissions-0-permission": 1,
            "grainy_permissions-0-user": user_permission.id,
            "grainy_permissions-0-id": "",
            "grainy_permissions-__prefix__-namespace": "",
            "grainy_permissions-__prefix__-user": user_permission.id,
            "grainy_permissions-__prefix__-id": "",
            "_continue": "Save and continue editing",
        }

        response = client.post(url, payload, follow=True)

        assert response.status_code == 200

        # assert that the there are 0 grainy permissions
        assert len(user_permission.grainy_permissions.all()) == 0

        # test that other namespaces can still be added
        payload["grainy_permissions-0-namespace"] = "random.namespace"
        response = client.post(url, payload, follow=True)

        assert response.status_code == 200

        # assert that the there are 1 grainy permissions
        assert len(user_permission.grainy_permissions.all()) == 1

    def create_mfa_devices(self, user):
        """
        Give `user` one device of every type the change form renders.
        """

        devices = {
            "totp": TOTPDevice.objects.create(user=user, name="default"),
            "securitykey": SecurityKey.objects.create(
                name="test",
                type="security-key",
                user=user,
                credential_id="1234",
                credential_public_key="deadbeef",
            ),
            "static": StaticDevice.objects.create(user=user, name="backup tokens"),
            "email": EmailDevice.objects.create(
                user=user,
                confirmed=True,
                token=self.EMAIL_OTP_TOKEN,
                last_used_at=timezone.now(),
            ),
        }

        for token in self.BACKUP_TOKENS:
            StaticToken.objects.create(device=devices["static"], token=token)

        return devices

    def get_user_change_page(self, user):
        client = Client()
        client.force_login(self.admin_user)

        url = reverse("admin:peeringdb_server_user_change", args=[user.id])
        response = client.get(url, follow=True)

        assert response.status_code == 200
        return response.content.decode()

    def read_inline_cell(self, page, prefix, field):
        """
        Return the rendered value of a read-only inline column.

        Scoped to the inline group named by prefix, because a column name like
        last_used_at is rendered by more than one MFA section. The single-match
        assertion is what keeps this honest if a fixture ever gives a user two
        devices of the same type -- an unscoped read would silently return the
        first row.
        """

        group = re.search(
            rf'id="{prefix}-group".*?(?=id="[\w-]+-group"|</form>)', page, re.S
        )
        assert group, f"no inline group rendered for {prefix}"

        cells = re.findall(
            rf'grp-td {field} .*?<div class="grp-readonly">(.*?)</div>',
            group.group(0),
            re.S,
        )
        assert cells, f"no read-only cell rendered for {prefix}.{field}"
        assert len(cells) == 1, (
            f"{len(cells)} read-only cells rendered for {prefix}.{field}, expected 1"
        )
        return cells[0].strip()

    def test_userpermission_org_root_namespace(self):
        """
        Test that the #1157 cleanup also removes a permission at exactly the
        org root namespace (#2038)

        `test_userpermission` above only covers a dotted sub-namespace. The old
        dotted-prefix filter never matched the org root row -- the one that
        shadows the admin group's own CRUD grant at the same namespace.
        """

        user_permission = get_user_model().objects.create_user(
            username="user", email="user@localhost", password="user"
        )

        org = models.Organization.objects.create(name="test-org", status="ok")
        org.admin_usergroup.user_set.add(user_permission)

        client = Client()
        client.force_login(self.admin_user)

        url = reverse(
            "admin:peeringdb_server_userpermission_change", args=[user_permission.id]
        )

        payload = self._userpermission_payload(user_permission, org)
        payload.update(
            {
                "grainy_permissions-0-namespace": org.grainy_namespace,
                "grainy_permissions-0-permission": 1,
                "grainy_permissions-0-user": user_permission.id,
                "grainy_permissions-0-id": "",
            }
        )

        response = client.post(url, payload, follow=True)

        assert response.status_code == 200
        assert len(user_permission.grainy_permissions.all()) == 0

    def test_userpermission_groups_only_change(self):
        """
        Test that promoting a user to org admin in django-admin cleans up their
        granular permissions even when no permission inline form is submitted
        (#2038)

        `save_formset` took the user from a bound inline form, so a POST that
        changes only `groups` reached it with no user and did nothing.
        """

        user_permission = get_user_model().objects.create_user(
            username="user", email="user@localhost", password="user"
        )

        org = models.Organization.objects.create(name="test-org", status="ok")
        org.usergroup.user_set.add(user_permission)
        user_permission.grainy_permissions.create(
            namespace=org.grainy_namespace, permission=PERM_CRUD
        )

        client = Client()
        client.force_login(self.admin_user)

        url = reverse(
            "admin:peeringdb_server_userpermission_change", args=[user_permission.id]
        )

        response = client.post(
            url,
            self._userpermission_payload(user_permission, org, grainy_forms=0),
            follow=True,
        )

        assert response.status_code == 200
        assert user_permission.is_org_admin(org)
        assert len(user_permission.grainy_permissions.all()) == 0

    def test_userpermission_demotion_clears_user_permissions(self):
        """
        Test that demoting an org admin in django-admin drops the granular
        permissions they held while admin, without touching a permission the
        same POST added (#2038)

        `admin_organizations` reflects the groups as they are *after* the save,
        so cleaning up from that alone would cover the promote direction only,
        while the org UI and the REST API both scrub a demotion.
        """

        user_permission = get_user_model().objects.create_user(
            username="user", email="user@localhost", password="user"
        )

        org = models.Organization.objects.create(name="test-org", status="ok")
        org.admin_usergroup.user_set.add(user_permission)

        # what the admin role left behind -- the population
        # `pdb_fix_org_admin_perms` is shipped to clean

        leftover = user_permission.grainy_permissions.create(
            namespace=org.grainy_namespace, permission=PERM_CRUD
        )

        # a legitimate permission in an unrelated org the demotion must not
        # reach -- the wipe is a new delete path, so its scope is asserted

        other_org = models.Organization.objects.create(name="other-org", status="ok")
        other_org.usergroup.user_set.add(user_permission)
        user_permission.grainy_permissions.create(
            namespace=f"{other_org.grainy_namespace}.network", permission=PERM_CRUD
        )

        client = Client()
        client.force_login(self.admin_user)

        url = reverse(
            "admin:peeringdb_server_userpermission_change", args=[user_permission.id]
        )

        payload = self._userpermission_payload(
            user_permission, org, grainy_forms=2, initial_forms=1
        )

        # `groups` replaces the whole set, so the unrelated membership has to be
        # posted back alongside the demotion

        payload["groups"] = [org.usergroup.id, other_org.usergroup.id]

        payload.update(
            {
                # the leftover row as the change page renders it back -- the
                # inline always echoes existing rows, and the permission field
                # reports itself as changed either way, so the wipe cannot lean
                # on the formset to tell it what the POST really touched
                "grainy_permissions-0-namespace": org.grainy_namespace,
                "grainy_permissions-0-permission": PERM_CRUD,
                "grainy_permissions-0-user": user_permission.id,
                "grainy_permissions-0-id": leftover.id,
                # and one permission the same POST grants the demoted member,
                # which is legitimate for a member to hold
                "grainy_permissions-1-namespace": f"{org.grainy_namespace}.network",
                "grainy_permissions-1-permission": PERM_CRUD,
                "grainy_permissions-1-user": user_permission.id,
                "grainy_permissions-1-id": "",
            }
        )

        response = client.post(url, payload, follow=True)

        assert response.status_code == 200

        user_permission = get_user_model().objects.get(id=user_permission.id)

        assert not user_permission.is_org_admin(org)
        assert {p.namespace for p in user_permission.grainy_permissions.all()} == {
            f"{org.grainy_namespace}.network",
            f"{other_org.grainy_namespace}.network",
        }

    def test_userpermission_removal_clears_user_permissions(self):
        """
        Test that removing a plain member from an org in django-admin drops the
        granular permissions they held there (#2038)

        Both capture points around the group write key on the *admin* role, so
        a user who was never an admin of the org fell through every branch --
        leaving django-admin the only removal path that did not scrub, while
        `manage_user_delete` and `remove_organization_user` both wipe on
        removal without consulting the role.
        """

        user_permission = get_user_model().objects.create_user(
            username="user", email="user@localhost", password="user"
        )

        org = models.Organization.objects.create(name="test-org", status="ok")
        org.usergroup.user_set.add(user_permission)

        # legitimately granted while the user was a member -- it stops being
        # legitimate the moment they are out of the org

        granted = user_permission.grainy_permissions.create(
            namespace=f"{org.grainy_namespace}.network.123", permission=PERM_CRUD
        )

        # an unrelated org the removal must not reach

        other_org = models.Organization.objects.create(name="other-org", status="ok")
        other_org.usergroup.user_set.add(user_permission)
        user_permission.grainy_permissions.create(
            namespace=f"{other_org.grainy_namespace}.network", permission=PERM_CRUD
        )

        client = Client()
        client.force_login(self.admin_user)

        url = reverse(
            "admin:peeringdb_server_userpermission_change", args=[user_permission.id]
        )

        payload = self._userpermission_payload(
            user_permission, org, grainy_forms=1, initial_forms=1
        )

        # `groups` replaces the whole set, so dropping `org` from it is the
        # removal -- the unrelated membership has to be posted back alongside

        payload["groups"] = [other_org.usergroup.id]

        payload.update(
            {
                # the row as the change page renders it back, so the wipe has
                # to take an echoed row and not just an untouched one
                "grainy_permissions-0-namespace": granted.namespace,
                "grainy_permissions-0-permission": PERM_CRUD,
                "grainy_permissions-0-user": user_permission.id,
                "grainy_permissions-0-id": granted.id,
            }
        )

        response = client.post(url, payload, follow=True)

        assert response.status_code == 200

        user_permission = get_user_model().objects.get(id=user_permission.id)

        assert org not in user_permission.organizations
        assert {p.namespace for p in user_permission.grainy_permissions.all()} == {
            f"{other_org.grainy_namespace}.network",
        }

    def test_get_user_change_form_with_inline_fields(self):
        """
        Test that all configured MFA device types are listed on the user change
        form (#2009)
        """

        userchange = get_user_model().objects.create_user(
            username="user", email="user@localhost", password="user"
        )

        devices = self.create_mfa_devices(userchange)

        page = self.get_user_change_page(userchange)

        for heading in self.MFA_INLINE_HEADINGS:
            assert f'<h2 class="grp-collapse-handler">{heading}</h2>' in page

        # the TOTP and security key sections are read-only like the rest
        assert 'name="totpdevice_set-0-name"' not in page
        assert 'name="webauthn_security_keys-0-name"' not in page
        assert self.read_inline_cell(page, "totpdevice_set", "name") == "default"
        assert (
            self.read_inline_cell(page, "webauthn_security_keys", "type")
            == "security-key"
        )
        # SecurityKey.updated is auto_now and this key never authenticated, so
        # the column must not be presented as a last-use time
        assert '<div class="grp-th last-updated">' in page
        assert '<div class="grp-th last-used">' not in page
        assert (
            self.read_inline_cell(page, "webauthn_security_keys", "last_updated") != "-"
        )

        # every throttled device type shows its lockout state
        for prefix in ("totpdevice_set", "staticdevice_set", "emaildevice_set"):
            assert (
                self.read_inline_cell(page, prefix, "throttling_failure_count") == "0"
            )

        # only the TOTP device page can clear a lockout, so only TOTP links to
        # it. the static and email device pages have no throttling fields, the
        # static one lists every backup code, and the security key one is
        # editable
        assert (
            reverse("admin:otp_totp_totpdevice_change", args=[devices["totp"].pk])
            in page
        )
        for key, url_name in (
            ("static", "admin:otp_static_staticdevice_change"),
            ("email", "admin:otp_email_emaildevice_change"),
            ("securitykey", "admin:django_security_keys_securitykey_change"),
        ):
            assert reverse(url_name, args=[devices[key].pk]) not in page

        # backup tokens are reported as a count of what is left
        assert self.read_inline_cell(
            page, "staticdevice_set", "unused_token_count"
        ) == str(len(self.BACKUP_TOKENS))

        # email otp falls back to the account address when the device carries
        # no alternative one
        assert (
            self.read_inline_cell(page, "emaildevice_set", "token_destination")
            == "user@localhost"
        )

        # last_used_at is what distinguishes an auto-provisioned email device
        # from one that has actually authenticated someone
        assert self.read_inline_cell(page, "emaildevice_set", "last_used_at") != "-"
        assert self.read_inline_cell(page, "staticdevice_set", "last_used_at") == "-"

    def test_get_user_change_form_hides_mfa_secrets(self):
        """
        Test that no MFA section renders a secret: the TOTP shared key, backup
        token values or the live email one-time password (#2009)
        """

        userchange = get_user_model().objects.create_user(
            username="user_secrets", email="user_secrets@localhost", password="user"
        )

        devices = self.create_mfa_devices(userchange)

        page = self.get_user_change_page(userchange)

        assert devices["totp"].key not in page

        for token in self.BACKUP_TOKENS:
            assert token not in page

        assert self.EMAIL_OTP_TOKEN not in page

    def test_get_user_change_form_without_mfa_devices(self):
        """
        Test that the user change form renders for a user with no MFA devices
        at all (#2009)
        """

        userchange = get_user_model().objects.create_user(
            username="user_nodevices", email="user_nodevices@localhost", password="user"
        )

        page = self.get_user_change_page(userchange)

        for heading in self.MFA_INLINE_HEADINGS:
            assert f'<h2 class="grp-collapse-handler">{heading}</h2>' in page

    def user_change_post_data(self, user, devices):
        """
        Build a POST payload for the user change form that leaves every MFA
        device exactly as it is, mirroring what the browser submits.
        """

        return {
            "username": user.username,
            "email": user.email,
            "first_name": "Changed",
            "last_name": "",
            "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
            "affiliation_requests-TOTAL_FORMS": "0",
            "affiliation_requests-INITIAL_FORMS": "0",
            "affiliation_requests-MIN_NUM_FORMS": "0",
            "affiliation_requests-MAX_NUM_FORMS": "1000",
            # the MFA sections contribute no editable fields, so the browser
            # submits their management form and the row ids only
            "totpdevice_set-TOTAL_FORMS": "1",
            "totpdevice_set-INITIAL_FORMS": "1",
            "totpdevice_set-MIN_NUM_FORMS": "0",
            "totpdevice_set-MAX_NUM_FORMS": "0",
            "totpdevice_set-0-id": str(devices["totp"].id),
            "totpdevice_set-0-user": str(user.id),
            "webauthn_security_keys-TOTAL_FORMS": "1",
            "webauthn_security_keys-INITIAL_FORMS": "1",
            "webauthn_security_keys-MIN_NUM_FORMS": "0",
            "webauthn_security_keys-MAX_NUM_FORMS": "0",
            "webauthn_security_keys-0-id": str(devices["securitykey"].id),
            "webauthn_security_keys-0-user": str(user.id),
            "staticdevice_set-TOTAL_FORMS": "1",
            "staticdevice_set-INITIAL_FORMS": "1",
            "staticdevice_set-MIN_NUM_FORMS": "0",
            "staticdevice_set-MAX_NUM_FORMS": "0",
            "staticdevice_set-0-id": str(devices["static"].id),
            "staticdevice_set-0-user": str(user.id),
            "emaildevice_set-TOTAL_FORMS": "1",
            "emaildevice_set-INITIAL_FORMS": "1",
            "emaildevice_set-MIN_NUM_FORMS": "0",
            "emaildevice_set-MAX_NUM_FORMS": "0",
            "emaildevice_set-0-id": str(devices["email"].id),
            "emaildevice_set-0-user": str(user.id),
        }

    def test_user_change_form_saves_with_mfa_devices(self):
        """
        Test that the user change form still saves for a user carrying every
        MFA device type, and leaves the devices alone (#2009)

        The MFA sections render with MAX_NUM_FORMS of 0 because they take no
        additions, so the browser posts that back on an ordinary save.
        """

        userchange = get_user_model().objects.create_user(
            username="user_save", email="user_save@localhost", password="user"
        )

        devices = self.create_mfa_devices(userchange)

        client = Client()
        client.force_login(self.admin_user)

        url = reverse("admin:peeringdb_server_user_change", args=[userchange.id])
        response = client.post(url, self.user_change_post_data(userchange, devices))

        assert response.status_code == 302

        userchange.refresh_from_db()
        assert userchange.first_name == "Changed"

        assert TOTPDevice.objects.filter(pk=devices["totp"].pk).exists()
        assert SecurityKey.objects.filter(pk=devices["securitykey"].pk).exists()
        assert StaticDevice.objects.filter(pk=devices["static"].pk).exists()
        assert EmailDevice.objects.filter(pk=devices["email"].pk).exists()
        assert StaticToken.objects.filter(
            device_id=devices["static"].pk
        ).count() == len(self.BACKUP_TOKENS)

    def test_user_change_form_ignores_mfa_device_edits(self):
        """
        Test that values posted for the read-only TOTP and security key columns
        are ignored, so the user change form cannot replace a TOTP shared key
        """

        userchange = get_user_model().objects.create_user(
            username="user_forge", email="user_forge@localhost", password="user"
        )

        devices = self.create_mfa_devices(userchange)
        totp_key = devices["totp"].key

        data = self.user_change_post_data(userchange, devices)
        data["totpdevice_set-0-key"] = "00" * 20
        data["totpdevice_set-0-name"] = "forged"
        data["webauthn_security_keys-0-name"] = "forged"

        client = Client()
        client.force_login(self.admin_user)

        url = reverse("admin:peeringdb_server_user_change", args=[userchange.id])
        response = client.post(url, data)

        assert response.status_code == 302

        devices["totp"].refresh_from_db()
        devices["securitykey"].refresh_from_db()
        assert devices["totp"].key == totp_key
        assert devices["totp"].name == "default"
        assert devices["securitykey"].name == "test"

    def test_get_user_change_form_readonly_admin(self):
        """
        Test that a read-only staff admin sees every MFA device section on the
        user change form, and no secret in any of them (#2009)

        The positive assertion is load bearing. Django drops an inline whose
        model the request has no permission on, and the four device models sit
        outside peeringdb_server, so a staff account is shown none of these
        sections unless its grants include MFA_DEVICE_APP_LABELS. Asserting
        only the absence of secrets would therefore pass against a page with
        no MFA sections on it at all.
        """

        userchange = get_user_model().objects.create_user(
            username="user_ro", email="user_ro@localhost", password="user"
        )

        devices = self.create_mfa_devices(userchange)

        client = Client()
        client.force_login(self.readonly_admin)

        url = reverse("admin:peeringdb_server_user_change", args=[userchange.id])
        # no follow: a redirect to the login form also lands on 200 and would
        # not be the change form
        response = client.get(url)

        assert response.status_code == 200

        page = response.content.decode()

        for heading in self.MFA_INLINE_HEADINGS:
            assert f'<h2 class="grp-collapse-handler">{heading}</h2>' in page

        # the computed columns render for a non-superuser too
        assert self.read_inline_cell(
            page, "staticdevice_set", "unused_token_count"
        ) == str(len(self.BACKUP_TOKENS))
        assert (
            self.read_inline_cell(page, "emaildevice_set", "token_destination")
            == "user_ro@localhost"
        )

        assert devices["totp"].key not in page

        for token in self.BACKUP_TOKENS:
            assert token not in page

        assert self.EMAIL_OTP_TOKEN not in page

    def test_user_change_form_mfa_device_delete(self):
        """
        Test that every MFA device section on the user change form offers
        deletion, including the ones added by #2009
        """

        userchange = get_user_model().objects.create_user(
            username="user_revoke", email="user_revoke@localhost", password="user"
        )

        devices = self.create_mfa_devices(userchange)

        page = self.get_user_change_page(userchange)

        for prefix in self.MFA_INLINE_PREFIXES:
            assert f'name="{prefix}-0-DELETE"' in page

        request = self.factory.post("/cp")
        request.user = self.admin_user

        inline = admin.UserStaticDeviceInline(models.User, admin_site)
        formset_cls = inline.get_formset(request, userchange)
        prefix = formset_cls.get_default_prefix()

        formset = formset_cls(
            {
                f"{prefix}-TOTAL_FORMS": "1",
                f"{prefix}-INITIAL_FORMS": "1",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "0",
                f"{prefix}-0-id": str(devices["static"].id),
                f"{prefix}-0-user": str(userchange.id),
                f"{prefix}-0-DELETE": "on",
            },
            instance=userchange,
        )

        assert formset.is_valid(), formset.errors
        formset.save()

        assert not StaticDevice.objects.filter(pk=devices["static"].pk).exists()

    def test_protected_ixlanprefix_deletion(self):
        ixlan = self.entities["ixlan"][0]
        prefix = models.IXLanPrefix.objects.create(
            ixlan=ixlan, protocol="IPv4", prefix="198.51.100.0/24", status="ok"
        )

        netixlan = models.NetworkIXLan.objects.create(
            network=self.entities["net"][0],
            ixlan=ixlan,
            ipaddr4="198.51.100.10",
            status="ok",
            asn=self.entities["net"][0].asn,
            speed=1000,
        )

        self.assertFalse(prefix.deletable)
        self.assertIn("198.51.100.10", prefix.not_deletable_reason)

        client = Client()
        client.force_login(self.admin_user)

        url = reverse("admin:peeringdb_server_ixlanprefix_changelist")
        response = client.post(
            url, {"_selected_action": prefix.id, "action": "soft_delete"}, follow=True
        )
        self.assertEqual(response.status_code, 200)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("Please confirm deletion of selected objects", str(messages[0]))

        response = client.post(
            url,
            {"_selected_action": prefix.id, "action": "soft_delete", "delete": "true"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        # Verify prefix still exists
        self.assertTrue(models.IXLanPrefix.objects.filter(id=prefix.id).exists())

        # Check for error message
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("Protected object", str(messages[0]))
        self.assertIn("IP address 198.51.100.10", str(messages[0]))

        url = reverse("admin:peeringdb_server_ixlanprefix_delete", args=[prefix.id])
        response = client.get(url, follow=True)

        # Redirect back to the change list with error
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 2)
        self.assertIn("IP address 198.51.100.10", str(messages[0]))

        self.assertTrue(models.IXLanPrefix.objects.filter(id=prefix.id).exists())

        # Clean up the netixlan to make prefix deletable
        netixlan.delete()

        prefix = models.IXLanPrefix.objects.get(id=prefix.id)
        self.assertTrue(prefix.deletable)

        response = client.post(url, {"post": "yes"}, follow=True)
        self.assertEqual(response.status_code, 200)
        # True because it just soft delete, so the data is still exist
        self.assertTrue(
            models.IXLanPrefix.objects.filter(id=prefix.id).filter(status="deleted")
        )

    def test_deleted_org_child_activation(self):
        """
        Test that objects under a deleted organization cannot be activated.

        Verifies that when an organization is deleted, child objects
        (network, ix, facility) cannot be changed from 'deleted' to 'ok' status.
        Addresses issue #1845.
        """
        client = Client()
        client.force_login(self.admin_user)

        org = self.entities["org"][0]
        network = self.entities["net"][0]

        # Delete both org and network
        network.status = "deleted"
        network.save()
        org.status = "deleted"
        org.save()

        url = reverse("admin:peeringdb_server_network_change", args=[network.id])
        response = client.post(
            url,
            {
                "name": network.name,
                "asn": network.asn,
                "status": "ok",
                "org": org.id,
                "website": "",
            },
            follow=True,
        )

        # Verify the status change was rejected
        self.assertEqual(response.status_code, 200)

        # Check that error message is displayed
        content = response.content.decode("utf-8")
        self.assertIn("cannot be saved because its parent entity", content.lower())
        self.assertIn("has been marked as deleted", content.lower())

        # Verify status remains 'deleted'
        network.refresh_from_db()
        self.assertEqual(network.status, "deleted")

        # Clean up netixlan entries to avoid foreign key issues
        for netixlan in self.entities["netixlan"]:
            netixlan.delete()

        # Test the same for other entity types
        entity_mappings = [
            ("internetexchange", "ix"),
            ("facility", "fac"),
        ]

        for admin_name, entity_tag in entity_mappings:
            entity = self.entities[entity_tag][0]
            entity.status = "deleted"
            entity.save()

            url = reverse(
                f"admin:peeringdb_server_{admin_name}_change", args=[entity.id]
            )
            response = client.post(
                url,
                {
                    "name": entity.name,
                    "status": "ok",
                    "org": org.id,
                    "website": "",
                },
                follow=True,
            )

            # Verify it failed
            entity.refresh_from_db()
            self.assertEqual(
                entity.status,
                "deleted",
                f"{entity_tag} status should remain 'deleted' when org is deleted",
            )

    def test_ixf_cascade_delete_internetexchange(self):
        """
        A superuser must be able to delete an InternetExchange that has
        associated IX-F Import Log and IX-F Member Data via the admin
        (soft-delete sets status to 'deleted'). The IX-F records themselves
        are not actually deleted — the cascade simulation in the confirmation
        page is bypassed via InternetExchangeAdmin.get_deleted_objects().
        Addresses issue #1875.
        """
        ix = self.entities["ix"][1]
        ixlan = ix.ixlan

        models.IXLanPrefix.objects.create(
            ixlan=ixlan,
            protocol="IPv4",
            prefix="198.51.100.0/24",
            status="ok",
        )
        netixlan = models.NetworkIXLan.objects.create(
            network=self.entities["net"][1],
            ixlan=ixlan,
            ipaddr4="198.51.100.10",
            status="ok",
            asn=self.entities["net"][1].asn,
            speed=1000,
        )
        ixfmemberdata = models.IXFMemberData.instantiate(
            ixlan=ixlan,
            ipaddr4=netixlan.ipaddr4,
            ipaddr6=netixlan.ipaddr6,
            asn=netixlan.network.asn,
        )
        ixfmemberdata.save()
        models.IXLanIXFMemberImportLog.objects.create(ixlan=ixlan)

        client = Client()
        client.force_login(self.admin_user)

        url = reverse("admin:peeringdb_server_internetexchange_delete", args=[ix.id])

        confirm = client.get(url)
        self.assertEqual(confirm.status_code, 200)
        body = confirm.content.decode("utf-8")
        self.assertNotIn("doesn&#x27;t have permission to delete", body)
        self.assertNotIn("doesn't have permission to delete", body)

        response = client.post(url, {"post": "yes"}, follow=True)
        self.assertEqual(response.status_code, 200)

        ix.refresh_from_db()
        self.assertEqual(ix.status, "deleted")

    def test_ixf_delete_direct_blocked_for_all(self):
        """
        No user — including superusers — must be able to directly delete
        IXLanIXFMemberImportLog or IXFMemberData via the admin. The bypass
        in InternetExchangeAdmin.get_deleted_objects() only skips the cascade
        permission check, it does not open up direct deletion.
        Addresses issue #1875.
        """
        ix = self.entities["ix"][2]
        ixlan = ix.ixlan
        netixlan = models.NetworkIXLan.objects.create(
            network=self.entities["net"][2],
            ixlan=ixlan,
            ipaddr4="192.0.2.1",
            status="ok",
            asn=self.entities["net"][2].asn,
            speed=1000,
        )

        ixfmemberdata = models.IXFMemberData.instantiate(
            ixlan=ixlan,
            ipaddr4=netixlan.ipaddr4,
            ipaddr6=netixlan.ipaddr6,
            asn=netixlan.network.asn,
        )
        ixfmemberdata.save()
        log = models.IXLanIXFMemberImportLog.objects.create(ixlan=ixlan)

        log_url = reverse(
            "admin:peeringdb_server_ixlanixfmemberimportlog_delete", args=[log.id]
        )
        data_url = reverse(
            "admin:peeringdb_server_ixfmemberdata_delete", args=[ixfmemberdata.id]
        )

        for user in [self.admin_user, self.readonly_admin]:
            client = Client()
            client.force_login(user)

            response = client.post(log_url, {"post": "yes"}, follow=True)
            self.assertIn(response.status_code, [403, 302])
            self.assertTrue(
                models.IXLanIXFMemberImportLog.objects.filter(id=log.id).exists()
            )

            response = client.post(data_url, {"post": "yes"}, follow=True)
            self.assertIn(response.status_code, [403, 302])
            self.assertTrue(
                models.IXFMemberData.objects.filter(id=ixfmemberdata.id).exists()
            )

    # --- Passkey policy flag tests (org admin form) ---

    def _post_org_admin(self, org, extra_data):
        """Post to the Django admin change page for an Organization."""
        url = reverse("admin:peeringdb_server_organization_change", args=[org.id])
        data = {
            "status": "ok",
            "name": org.name,
            "aka": "",
            "name_long": "",
            "address1": "",
            "address2": "",
            "city": "",
            "state": "",
            "zipcode": "",
            "country": "",
            "floor": "",
            "suite": "",
            "latitude": "",
            "longitude": "",
            "geocode_status": "",
            "geocode_date": "",
            "website": "",
            "notes": "",
            "restrict_user_emails": False,
            "email_domains": "",
            "passkey_disable_password_auth": False,
            "disable_totp": False,
            "passkey_require_mfa": False,
        }
        data.update(extra_data)
        self.client.force_login(self.admin_user)
        return self.client.post(url, data, follow=True)

    def test_admin_sets_passkey_disable_password_auth(self):
        """Saving the org admin form with passkey_disable_password_auth sets the flag."""
        org = self.entities["org"][0]
        response = self._post_org_admin(org, {"passkey_disable_password_auth": True})
        self.assertEqual(response.status_code, 200)

        org.refresh_from_db()
        self.assertTrue(org.passkey_disable_password_auth)
        self.assertFalse(org.disable_totp)
        self.assertFalse(org.passkey_require_mfa)

    def test_admin_sets_disable_totp(self):
        """Saving the org admin form with disable_totp sets the flag."""
        org = self.entities["org"][1]
        response = self._post_org_admin(org, {"disable_totp": True})
        self.assertEqual(response.status_code, 200)

        org.refresh_from_db()
        self.assertFalse(org.passkey_disable_password_auth)
        self.assertTrue(org.disable_totp)
        self.assertFalse(org.passkey_require_mfa)

    def test_admin_sets_passkey_require_mfa(self):
        """Saving the org admin form with passkey_require_mfa sets the flag."""
        org = self.entities["org"][2]
        response = self._post_org_admin(org, {"passkey_require_mfa": True})
        self.assertEqual(response.status_code, 200)

        org.refresh_from_db()
        self.assertFalse(org.passkey_disable_password_auth)
        self.assertFalse(org.disable_totp)
        self.assertTrue(org.passkey_require_mfa)

    def test_admin_allows_disable_totp_and_require_mfa(self):
        """
        disable_totp + passkey_require_mfa is a valid combination: the user can
        satisfy MFA via a second security key (or be redirected to enroll one).
        """
        org = self.entities["org"][3]
        response = self._post_org_admin(
            org, {"disable_totp": True, "passkey_require_mfa": True}
        )
        self.assertEqual(response.status_code, 200)

        org.refresh_from_db()
        self.assertTrue(org.disable_totp)
        self.assertTrue(org.passkey_require_mfa)

    def test_admin_clears_passkey_flag(self):
        """Unchecking a flag in admin clears it."""
        org = self.entities["org"][4]
        org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
        org.save()
        self.assertTrue(org.passkey_disable_password_auth)

        self._post_org_admin(org, {"passkey_disable_password_auth": False})

        org.refresh_from_db()
        self.assertFalse(org.passkey_disable_password_auth)


class NetixlanStatusAdminTests(TestCase):
    """
    #1742: netixlan carries operational-ness in `status`, so the admin's
    status vocabulary has to include "not-operational".

    StatusForm backs both netixlan admin write paths -- NetworkIXLanAdmin
    via NetworkIXLanAdminForm, and the netixlan inline on the Network admin
    page via NetworkIXLanForm. A select whose options do not contain the
    row's current value renders preselected on "ok" and posts that back, so
    saving a Network for an entirely unrelated reason would silently discard
    the network's non-operational declaration.
    """

    @classmethod
    def setUpTestData(cls):
        cls.org = models.Organization.objects.create(name="NotOp Org", status="ok")
        cls.net = models.Network.objects.create(
            name="NotOp Net", asn=64599, org=cls.org, status="ok"
        )
        cls.ix = models.InternetExchange.objects.create(
            name="NotOp IX", org=cls.org, status="ok"
        )
        models.IXLanPrefix.objects.create(
            ixlan=cls.ix.ixlan,
            protocol="IPv4",
            prefix="195.69.164.0/22",
            status="ok",
        )
        cls.netixlan = models.NetworkIXLan.objects.create(
            network=cls.net,
            ixlan=cls.ix.ixlan,
            asn=cls.net.asn,
            speed=1000,
            status="not-operational",
            ipaddr4="195.69.164.10",
        )

    def request(self):
        # the concrete form class only exists once the ModelAdmin has run it
        # through modelform_factory -- StatusForm itself declares no
        # Meta.model, so the vocabulary has to be resolved at that point
        request = RequestFactory().get("/")
        request.user = get_user_model().objects.create_user(
            "notop_admin", "notop_admin@localhost", "admin", is_superuser=True
        )
        return request

    def status_field(self, model_admin, obj):
        return model_admin.get_form(self.request(), obj=obj)(instance=obj).fields[
            "status"
        ]

    def test_status_choices_include_not_operational_on_the_netixlan_admin(self):
        field = self.status_field(
            admin.NetworkIXLanAdmin(models.NetworkIXLan, AdminSite()), self.netixlan
        )
        assert "not-operational" in dict(field.choices)
        # ... and the row's own value is selectable, so a save keeps it
        assert field.valid_value("not-operational")

    def test_status_choices_include_not_operational_on_the_network_inline(self):
        inline = admin.NetworkInternetExchangeInline(models.Network, AdminSite())
        formset = inline.get_formset(self.request(), obj=self.net)
        field = formset.form(instance=self.netixlan).fields["status"]
        assert "not-operational" in dict(field.choices)
        assert field.valid_value("not-operational")

    def test_other_models_keep_the_plain_status_vocabulary(self):
        # the extra value is netixlan's alone -- it must not leak into every
        # admin status select
        field = self.status_field(
            admin.NetworkAdmin(models.Network, AdminSite()), self.net
        )
        assert "not-operational" not in dict(field.choices)

    def test_pending_netixlan_can_be_resolved_into_either_live_status(self):
        models.NetworkIXLan.objects.filter(id=self.netixlan.id).update(status="pending")
        self.netixlan.refresh_from_db()
        field = self.status_field(
            admin.NetworkIXLanAdmin(models.NetworkIXLan, AdminSite()), self.netixlan
        )
        assert set(dict(field.choices)) == {"ok", "not-operational", "pending"}

    def test_status_filter_can_list_not_operational(self):
        class _ModelAdmin:
            model = models.NetworkIXLan

        lookups = dict(
            admin.StatusFilter(None, {}, models.NetworkIXLan, _ModelAdmin).lookups(
                None, _ModelAdmin
            )
        )
        assert "not-operational" in lookups
        assert set(lookups) == {"ok", "not-operational", "pending", "deleted", "all"}

    @staticmethod
    def _post_data(form_cls, instance, **overrides):
        # rebuild what the change form would post: every field at its
        # current value, with the caller's overrides on top
        unbound = form_cls(instance=instance)
        data = {
            name: unbound[name].value()
            for name in unbound.fields
            if unbound[name].value() is not None
        }
        data.update(overrides)
        return data

    def test_restoring_a_deleted_netixlan_under_a_deleted_parent_is_a_form_error(self):
        """
        StatusForm.clean()'s parent-status guard has to cover every live
        status, not a literal list. A status missing from that list skips
        validate_parent_status(), which NetworkIXLan.save() then raises as
        ParentStatusException -- an IOError, not a ValidationError, so it
        escapes the admin as a 500 on exactly the path that gives the AC a
        readable error for "ok".
        """
        models.Network.objects.filter(id=self.net.id).update(status="deleted")
        models.NetworkIXLan.objects.filter(id=self.netixlan.id).update(status="deleted")
        self.netixlan.refresh_from_db()

        # driven through the inline's form, the path the AC reaches from the
        # Network page -- NetworkIXLanAdminForm shares StatusForm.clean()
        inline = admin.NetworkInternetExchangeInline(models.Network, AdminSite())
        form_cls = inline.get_formset(self.request(), obj=self.net).form

        for status in ("ok", "not-operational"):
            # a fresh instance per iteration -- validating a bound form
            # mutates the one it is given
            instance = models.NetworkIXLan.objects.get(id=self.netixlan.id)
            form = form_cls(
                instance=instance,
                data=self._post_data(form_cls, instance, status=status),
            )
            assert not form.is_valid(), status
            assert "has been marked as deleted" in str(form.errors), status

    def test_operational_is_read_only_on_both_netixlan_admin_paths(self):
        # NetworkIXLan.save() recomputes `operational` from `status` on
        # every save, so an editable widget would silently discard whatever
        # the AC set
        request = self.request()
        model_admin = admin.NetworkIXLanAdmin(models.NetworkIXLan, AdminSite())
        assert "operational" in model_admin.get_readonly_fields(
            request, obj=self.netixlan
        )
        assert (
            "operational"
            not in model_admin.get_form(request, obj=self.netixlan).base_fields
        )

        inline = admin.NetworkInternetExchangeInline(models.Network, AdminSite())
        assert "operational" in inline.get_readonly_fields(request, obj=self.net)
        assert (
            "operational"
            not in inline.get_formset(request, obj=self.net).form.base_fields
        )
