import os
import pytest

from django.test import Client, TestCase, RequestFactory

import peeringdb_server.models as models
import peeringdb_server.admin as admin


class AdminTests(TestCase):
    """
    Test peeringdb django admin functionality
    """

    asn_count = 0

    @classmethod
    def entity_data(cls, org, tag):
        kwargs = {
            "name": "%s %s" % (org.name, tag),
            "status": "ok",
            "org": org
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
                models.Organization.objects.create(
                    name="Org %d" % i, status="ok") for i in range(0, 9)
            ]
        ]

        # set up a network,facility and ix under each org
        for tag in ["ix", "net", "fac"]:
            cls.entities[tag] = [
                models.REFTAG_MAP[tag].objects.create(**cls.entity_data(
                    org, tag)) for org in cls.entities["org"]
            ]

        # create a user under each org
        cls.entities["user"] = [
            models.User.objects.create_user(
                "user " + org.name, "%s@localhost" % org.name,
                first_name="First", last_name="Last")
            for org in cls.entities["org"]
        ]
        i = 0
        for user in cls.entities["user"]:
            cls.entities["org"][i].usergroup.user_set.add(user)
            i += 1

        cls.admin_user = models.User.objects.create_user(
            "admin", "admin@localhost", first_name="admin", last_name="admin")
        cls.admin_user.is_superuser = True
        cls.admin_user.is_staff = True
        cls.admin_user.save()
        cls.admin_user.set_password("admin")
        cls.admin_user.save()

        #set up some ixlans
        cls.entities["ixlan"] = [
            models.IXLan.objects.create(ix=ix, status="ok")
            for ix in cls.entities["ix"]
        ]

        #set up a prefix
        cls.entities["ixpfx"] = [
            models.IXLanPrefix.objects.create(
                ixlan=cls.entities["ixlan"][0],
                protocol="IPv4",
                prefix="207.41.110.0/24",
                status="ok")
        ]

        #set up some netixlans
        cls.entities["netixlan"] = [
            models.NetworkIXLan.objects.create(
                network=cls.entities["net"][0], ixlan=cls.entities["ixlan"][0],
                ipaddr4=addr, status="ok", asn=cls.entities["net"][0].asn,
                speed=1000)
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
            models.Facility, models.InternetExchange, models.Network,
            models.Organization, models.User
        ]

        c = Client()
        c.login(username="admin", password="admin")
        for model in m:
            url = "/cp/%s/%s/" % (model._meta.app_label,
                                  model._meta.model_name)
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
        with self.assertRaises(ValueError) as inst:
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

        print t_org

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
            self.assertGreater(
                response.content.find('<option value="{}">{}</option>'.format(
                    i, n)), -1)

    def test_commandline_tool_renumber_lans(self):
        # test the form that runs the renumer ip space tool
        c = Client()
        c.login(username="admin", password="admin")

        # test renumber lans command form
        data = {"tool": "pdb_renumber_lans"}
        url = "/cp/peeringdb_server/commandlinetool/prepare/"
        response = c.post(url, data, follow=True)
        cont = response.content
        self.assertEqual(response.status_code, 200)
        self.assertGreater(
            cont.find(
                '<label class="required" for="id_old_prefix">Old prefix:</label>'
            ), -1)
        self.assertGreater(
            cont.find(
                '<label class="required" for="id_new_prefix">New prefix:</label>'
            ), -1)
        self.assertGreater(
            cont.find(
                '<label class="required" for="id_exchange">Exchange:</label>'),
            -1)

        # test post to renumber lans command form (preview)
        data = {
            "tool": "pdb_renumber_lans",
            "exchange": self.entities["ix"][0].id,
            "old_prefix": "207.41.110.0/24",
            "new_prefix": "207.41.111.0/24"
        }
        url = "/cp/peeringdb_server/commandlinetool/preview/"
        response = c.post(url, data, follow=True)
        cont = response.content
        self.assertEqual(response.status_code, 200)
        self.assertGreater(
            cont.find(
                '[pretend] Renumbering ixpfx1 207.41.110.0/24 -> 207.41.111.0/24'
            ), -1)
        self.assertGreater(
            cont.find(
                '[pretend] Renumbering netixlan1 AS1 207.41.110.37 -> 207.41.111.37'
            ), -1)
        self.assertGreater(
            cont.find(
                '[pretend] Renumbering netixlan2 AS1 207.41.110.38 -> 207.41.111.38'
            ), -1)
        self.assertGreater(
            cont.find(
                '[pretend] Renumbering netixlan3 AS1 207.41.110.39 -> 207.41.111.39'
            ), -1)

        # test post to renumber lans command form
        data = {
            "tool": "pdb_renumber_lans",
            "exchange": self.entities["ix"][0].id,
            "old_prefix": "207.41.110.0/24",
            "new_prefix": "207.41.111.0/24"
        }
        url = "/cp/peeringdb_server/commandlinetool/run/"
        response = c.post(url, data, follow=True)
        cont = response.content
        self.assertEqual(response.status_code, 200)

        self.assertGreater(
            cont.find(
                '>Renumbering ixpfx1 207.41.110.0/24 -> 207.41.111.0/24'
            ), -1)
        self.assertGreater(
            cont.find(
                '>Renumbering netixlan1 AS1 207.41.110.37 -> 207.41.111.37'
            ), -1)
        self.assertGreater(
            cont.find(
                '>Renumbering netixlan2 AS1 207.41.110.38 -> 207.41.111.38'
            ), -1)
        self.assertGreater(
            cont.find(
                '>Renumbering netixlan3 AS1 207.41.110.39 -> 207.41.111.39'
            ), -1)


        for netixlan in self.entities["netixlan"]:
            netixlan.refresh_from_db()

        self.assertEqual(
            str(self.entities["netixlan"][0].ipaddr4), "207.41.111.37")
        self.assertEqual(
            str(self.entities["netixlan"][1].ipaddr4), "207.41.111.38")
        self.assertEqual(
            str(self.entities["netixlan"][2].ipaddr4), "207.41.111.39")
