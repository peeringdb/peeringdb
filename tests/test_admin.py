import datetime
import json
import urllib

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from django_grainy.models import GroupPermission
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_security_keys.models import SecurityKey

import peeringdb_server.admin as admin
import peeringdb_server.models as models


class AdminTests(TestCase):
    """
    Test peeringdb django admin functionality
    """

    asn_count = 0

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
        for app_label in admin.PERMISSION_APP_LABELS:
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
        admin.merge_organizations(self.entities["org"][1:3], t_org, request)

        # check that all entities moved
        for tag in ["ix", "net", "fac"]:
            for ent in self.entities[tag][0:3]:
                ent.refresh_from_db()
                self.assertEqual(ent.org, t_org)

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
            f'Org {i} net</a></th><td class="field-asn">{i+1}</td>' for i in range(0, 9)
        ]
        for i, e in enumerate(expected):
            ## AS prefix
            content_as = self._run_regex_search("network", f"AS{i+1}")
            assert e in content_as

            for x in set(expected) - {expected[i]}:
                assert x not in content_as

            ## ASN prefix
            content_asn = self._run_regex_search("network", f"ASN{i+1}")
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
        _ = models.Facility.objects.create(
            name="Unverified facility", org=org, status="pending"
        )
        vqitem = models.VerificationQueueItem.objects.all().first()
        assert vqitem

        # create sponsorhship we can check
        sponsorship = models.Sponsorship.objects.create()
        models.SponsorshipOrganization.objects.create(sponsorship=sponsorship, org=org)

        # create partnership we can check
        _ = models.Partnership.objects.create(org=org)

        # create ixlan IX-F import log we can check
        ixfmemberdata = models.IXFMemberData.instantiate(
            ixlan=models.NetworkIXLan.objects.first().ixlan,
            ipaddr4=models.NetworkIXLan.objects.first().ipaddr4,
            ipaddr6=models.NetworkIXLan.objects.first().ipaddr6,
            asn=models.NetworkIXLan.objects.first().network.asn,
        )
        ixfmemberdata.save()

        # create ixlan IX-F import log we can check
        _ = models.IXLanIXFMemberImportLog.objects.create(
            ixlan=models.IXLan.objects.all().first()
        )

        # create user to organization affiliation request
        _ = models.UserOrgAffiliationRequest.objects.create(
            org=org, user=self.readonly_admin
        )

        # create command line tool instance
        _ = models.CommandLineTool.objects.create(
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

    def test_delete_user(self):
        """
        Test that deleting with pending UOAR works
        """

        client = Client()

        client.force_login(self.admin_user)

        user = models.User.objects.first()
        _ = models.UserOrgAffiliationRequest.objects.create(
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

    def test_get_user_change_form_with_inline_fields(self):
        """
        Test load page for TOTP devices and Webauthn Security Keys inline form fields
        """

        userchange = get_user_model().objects.create_user(
            username="user", email="user@localhost", password="user"
        )

        # create user TOTP devices
        totpdevice = TOTPDevice.objects.create(user=userchange, name="default")
        totpdevice.save()

        # create user to Webauthn Security Keys
        securitykey = SecurityKey.objects.create(
            name="test",
            type="security-key",
            user=userchange,
            credential_id="1234",
            credential_public_key="deadbeef",
        )
        securitykey.save()

        client = Client()
        client.force_login(self.admin_user)

        url = reverse("admin:peeringdb_server_user_change", args=[userchange.id])
        response = client.get(url, follow=True)

        assert response.status_code == 200
        page = response.content.decode()
        # check the topt device is listed
        assert (
            '<h2 class="grp-collapse-handler">User has these TOTP devices</h2>' in page
        )
        assert f'name="totpdevice_set-0-key" value="{totpdevice.key}"' in page
        # check the security key device is listed
        assert (
            '<h2 class="grp-collapse-handler">User has these Webauthn Security Keys</h2>'
            in page
        )
        assert 'name="webauthn_security_keys-0-credential_id" value="1234"' in page
