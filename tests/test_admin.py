import os
import pytest

from django.test import Client, TestCase, RequestFactory
from django.contrib.auth.models import Group
from django.urls import reverse
from django.core.management import call_command

import django_namespace_perms as nsp

import peeringdb_server.models as models
import peeringdb_server.admin as admin




class AdminTests(TestCase):
    """
    Test peeringdb django admin functionality
    """

    asn_count = 0

    @classmethod
    def entity_data(cls, org, tag):
        kwargs = {"name": "%s %s" % (org.name, tag), "status": "ok", "org": org}
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
        for tag in ["ix", "net", "fac"]:
            cls.entities[tag] = [
                models.REFTAG_MAP[tag].objects.create(**cls.entity_data(org, tag))
                for org in cls.entities["org"]
            ]

        # create a user under each org
        cls.entities["user"] = [
            models.User.objects.create_user(
                "user " + org.name,
                "%s@localhost" % org.name,
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
            "admin", "admin@localhost", first_name="admin", last_name="admin"
        )
        cls.admin_user.is_superuser = True
        cls.admin_user.is_staff = True
        cls.admin_user.save()
        cls.admin_user.set_password("admin")
        cls.admin_user.save()

        # user and group for read-only access to /cp
        cls.readonly_admin = models.User.objects.create_user(
            "ro_admin", "ro_admin@localhost", password="admin", is_staff=True
        )
        readonly_group = Group.objects.create(name="readonly")
        for app_label in admin.PERMISSION_APP_LABELS:
            nsp.models.GroupPermission.objects.create(
                group=readonly_group, namespace=app_label, permissions=0x01
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
            url = "/cp/%s/%s/" % (model._meta.app_label, model._meta.model_name)
            response = c.get(url, follow=True)
            self.assertEqual(response.status_code, 200)

            url_add = "%sadd" % url
            response = c.get(url_add, follow=True)
            self.assertEqual(response.status_code, 200)

            url_id = "%s%s" % (url, model.objects.first().id)
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

        # TEST 2 - Dont allow merging of target org into target org
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

    def test_commandline_tool(self):
        c = Client()
        c.login(username="admin", password="admin")

        # test form that lets user select which command run
        url = "/cp/peeringdb_server/commandlinetool/prepare"
        response = c.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        for i, n in models.COMMANDLINE_TOOLS:
            assert (
                '<option value="{}">{}</option>'.format(i, n)
                in response.content.decode()
            )

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
        assert 'Old prefix' in cont
        assert 'Exchange' in cont

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
        assert "[pretend] Renumbering ixpfx1 207.41.110.0/24 -> 207.41.111.0/24" in cont
        assert (
            "[pretend] Renumbering netixlan1 AS1 207.41.110.37 -> 207.41.111.37" in cont
        )
        assert (
            "[pretend] Renumbering netixlan2 AS1 207.41.110.38 -> 207.41.111.38" in cont
        )
        assert (
            "[pretend] Renumbering netixlan3 AS1 207.41.110.39 -> 207.41.111.39" in cont
        )

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

        assert "Renumbering ixpfx1 207.41.110.0/24 -> 207.41.111.0/24" in cont
        assert "Renumbering netixlan1 AS1 207.41.110.37 -> 207.41.111.37" in cont
        assert "Renumbering netixlan2 AS1 207.41.110.38 -> 207.41.111.38" in cont
        assert "Renumbering netixlan3 AS1 207.41.110.39 -> 207.41.111.39" in cont

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
            'admin:{}_{}_change'.format(
               ixlan._meta.app_label, ixlan._meta.object_name,
            ).lower(), args=(ixlan.id,)
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
                "ix": ixlan.ix.id,
                "status": ixlan.status,

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

        response = client.post(url, post_data(
            netixlan_b.ipaddr4, netixlan_b.ipaddr6
        ))
        assert netixlan.ipaddr6 is None
        assert netixlan.ipaddr4 is None
        assert "Ip address already exists elsewhere" in response.content.decode("utf-8")




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


    def _test_all_views(self, user, **kwargs):
        call_command("pdb_generate_test_data", limit=2, commit=True)

        # create a verification queue item we can check
        org = models.Organization.objects.all().first()
        net = models.Network.objects.create(name="Unverified network", org=org, asn=33333, status="pending")
        vqitem = models.VerificationQueueItem.objects.all().first()
        assert vqitem



        # create sponsorhship we can check
        sponsorship = models.Sponsorship.objects.create()
        models.SponsorshipOrganization.objects.create(
            sponsorship=sponsorship, org=org
        )

        # create partnership we can check
        partnership = models.Partnership.objects.create(
            org=org
        )

        # create ixlan ix-f import log we can check
        importlog = models.IXLanIXFMemberImportLog.objects.create(
            ixlan = models.IXLan.objects.all().first()
        )

        # create user to organization affiliation request
        affil = models.UserOrgAffiliationRequest.objects.create(
            org = org,
            user = self.readonly_admin
        )

        # create command line tool instance
        cmdtool = models.CommandLineTool.objects.create(
            user = self.readonly_admin,
            arguments = "{}",
            tool = "pdb_renumber_lans"
        )

        # create organization merge
        orgmerge = models.OrganizationMerge.objects.create(
            from_org=org,
            to_org=models.Organization.objects.all()[1]
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
            models.User,
            models.UserOrgAffiliationRequest,
            models.Sponsorship,
            models.Partnership,
            models.IXLanIXFMemberImportLog,
            models.VerificationQueueItem,
            models.CommandLineTool,
            admin.UserPermission,
            admin.DuplicateIPNetworkIXLan,
            models.OrganizationMerge,
        ]

        ignore_add = [
            admin.UserPermission,
            admin.DuplicateIPNetworkIXLan,
            models.OrganizationMerge
        ]

        ignore_change = [
            admin.DuplicateIPNetworkIXLan,
        ]

        # any other urls we want to test
        extra_urls = [
            (
                "/cp/peeringdb_server/organization/org-merge-tool/",
                "get",
                kwargs.get("status_get_orgmerge", 200)
            ),
            (
                reverse(
                    "admin:peeringdb_server_commandlinetool_prepare",
                ),
                "get",
                kwargs.get("status_add", 200)
            ),
            (
                reverse(
                    "admin:peeringdb_server_organizationmerge_actions",
                    args=(orgmerge.id, "undo")
                ),
                "get",
                kwargs.get("status_get_orgmerge_undo", 200)
            ),
            (
                reverse(
                    "admin:peeringdb_server_verificationqueueitem_actions",
                    args=(vqitem.id, "vq_approve")
                ),
                "get",
                kwargs.get("status_get_vq_approve", 200)
            ),
            (
                reverse(
                    "admin:peeringdb_server_verificationqueueitem_actions",
                    args=(vqitem.id, "vq_deny")
                ),
                "get",
                kwargs.get("status_get_vq_deny", 200)
            )

        ]

        client = Client()
        client.force_login(user)

        assert user.is_staff

        search_str = '<a href="/cp/logout/"';

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
                    'admin:{}_{}_{}'.format(
                        cls._meta.app_label, cls._meta.object_name, op
                    ).lower(), args=args
                )
                response = client.get(url)
                cont = response.content.decode("utf-8")
                assert response.status_code == kwargs.get("status_{}".format(op), 200)
                if response.status_code == 200:
                    assert search_str in cont

        for url, method, status in extra_urls:
            fn = getattr(client, method)
            response = fn(url, follow=True)
            assert response.status_code == status
            if response.status_code == 200:
                assert search_str in cont


        response = client.post(
            reverse("admin:peeringdb_server_commandlinetool_preview"),
            data={"tool":"pdb_fac_merge"}
        )
        assert response.status_code == kwargs.get("status_add", 200)
        if response.status_code == 200:
            assert search_str in cont




