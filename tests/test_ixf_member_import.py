import os
import json
import reversion
import requests
import jsonschema
import time
import StringIO

from django.db import transaction
from django.core.cache import cache
from django.test import TestCase, Client, RequestFactory
from django.core.management import call_command

from peeringdb_server.models import (
    Organization, Network, NetworkIXLan, IXLan, IXLanPrefix, InternetExchange,
    IXLanIXFMemberImportAttempt, IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry, User)
from peeringdb_server.import_views import (
    view_import_ixlan_ixf_preview,
    view_import_net_ixf_preview,
    view_import_net_ixf_postmortem,
    )
from peeringdb_server import ixf

from util import ClientCase


class JsonMembersListTestCase(ClientCase):
    # test this version of the json schema; requires the file
    # to exist at data/json_members_list/members.<VERSION>.json
    version = "0.6"

    schema_url = "https://raw.githubusercontent.com/euro-ix/json-schemas/v0.6/ixp-member-list.schema.json"

    # will be loaded with the json data to be tested against during
    # setUpTestData
    json_data = {}

    entities = {}

    @classmethod
    def setUpTestData(cls):

        super(JsonMembersListTestCase, cls).setUpTestData()

        # load json members list data to test against
        with open(
                os.path.join(
                    os.path.dirname(__file__), "data", "json_members_list",
                    "members.{}.json".format(cls.version)), "r") as fh:
            cls.json_data = json.load(fh)

        with reversion.create_revision():
            # create organization(s)
            cls.entities["org"] = [
                Organization.objects.create(name="Netflix", status="ok")
            ]

            # create exchange(s)
            cls.entities["ix"] = [
                InternetExchange.objects.create(name="Test Exchange",
                                                org=cls.entities["org"][0],
                                                status="ok")
            ]

            # create ixlan(s)
            cls.entities["ixlan"] = [
                IXLan.objects.create(ix=cls.entities["ix"][0], status="ok"),
                IXLan.objects.create(ix=cls.entities["ix"][0], status="ok"),
                IXLan.objects.create(ix=cls.entities["ix"][0], status="ok")
            ]

            # create ixlan prefix(s)
            cls.entities["ixpfx"] = [
                IXLanPrefix.objects.create(
                    ixlan=cls.entities["ixlan"][0], status="ok",
                    prefix="195.69.144.0/22", protocol="IPv4"),
                IXLanPrefix.objects.create(
                    ixlan=cls.entities["ixlan"][0], status="ok",
                    prefix="2001:7f8:1::/64", protocol="IPv6"),
                IXLanPrefix.objects.create(
                    ixlan=cls.entities["ixlan"][1], status="ok",
                    prefix="195.66.224.0/22", protocol="IPv4"),
                IXLanPrefix.objects.create(
                    ixlan=cls.entities["ixlan"][1], status="ok",
                    prefix="2001:7f8:4::/64", protocol="IPv6")
            ]

            # create network(s)
            cls.entities["net"] = [
                Network.objects.create(
                    name="Netflix", org=cls.entities["org"][0], asn=2906,
                    info_prefixes4=42, info_prefixes6=42,
                    website="http://netflix.com/", policy_general="Open",
                    policy_url="https://www.netflix.com/openconnect/",
                    allow_ixp_update=True, status="ok", irr_as_set="AS-NFLX"),
                Network.objects.create(name="Network with deleted netixlans",
                                       org=cls.entities["org"][0], asn=1001,
                                       allow_ixp_update=True, status="ok"),
                Network.objects.create(
                    name="Network with allow ixp update off",
                    org=cls.entities["org"][0], asn=1002, status="ok")
            ]

            # create netixlans
            cls.entities["netixlan"] = [
                NetworkIXLan.objects.create(
                    network=cls.entities["net"][1],
                    ixlan=cls.entities["ixlan"][1], asn=1001, speed=10000,
                    ipaddr4="195.69.146.250", ipaddr6=None, status="deleted"),
                NetworkIXLan.objects.create(
                    network=cls.entities["net"][1],
                    ixlan=cls.entities["ixlan"][1], asn=1001, speed=10000,
                    ipaddr4=None, ipaddr6="2001:7f8:1::a500:2906:1",
                    status="deleted"),
                NetworkIXLan.objects.create(
                    network=cls.entities["net"][0],
                    ixlan=cls.entities["ixlan"][0], asn=2906, speed=10000,
                    ipaddr4="195.69.146.249", ipaddr6=None, status="ok"),
                NetworkIXLan.objects.create(
                    network=cls.entities["net"][0],
                    ixlan=cls.entities["ixlan"][0], asn=2906, speed=10000,
                    ipaddr4="195.69.146.251", ipaddr6=None, status="ok"),
                NetworkIXLan.objects.create(
                    network=cls.entities["net"][0],
                    ixlan=cls.entities["ixlan"][0], asn=2906, speed=20000, is_rs_peer=False,
                    ipaddr4="195.69.147.251", ipaddr6=None, status="ok"),
                NetworkIXLan.objects.create(
                    network=cls.entities["net"][0],
                    ixlan=cls.entities["ixlan"][0], asn=1002, speed=10000,
                    ipaddr4="195.69.147.252", ipaddr6=None, status="ok"),
            ]

        cls.admin_user = User.objects.create_user("admin","admin@localhost","admin")
        cls.entities["org"][0].admin_usergroup.user_set.add(cls.admin_user)



    def setUp(self):
        self.ixf_importer = ixf.Importer()

    def assertLog(self, log, expected):
        path = os.path.join(os.path.dirname(__file__), "data", "ixf", "logs", "{}.json".format(expected))
        with open(path, "r") as fh:
            self.assertEqual(log, json.load(fh))

    def test_update_from_ixf_ixp_member_list(self):
        ixlan = self.entities["ixlan"][0]
        n_deleted = self.entities["netixlan"][0]
        n_deleted2 = self.entities["netixlan"][1]
        self.assertEqual(unicode(n_deleted.ipaddr4), u'195.69.146.250')
        self.assertEqual(
            unicode(n_deleted2.ipaddr6), u'2001:7f8:1::a500:2906:1')
        self.assertEqual(ixlan.netixlan_set_active.count(), 4)
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        self.assertLog(log, "update_01")
        self.assertEqual(len(netixlans), 5)
        self.assertEqual(len(netixlans_deleted), 2)

        n = netixlans[0]
        self.assertEqual(unicode(n.ipaddr4), u"195.69.146.250")
        self.assertEqual(unicode(n.ipaddr6), u"2001:7f8:1::a500:2906:2")
        self.assertEqual(n.speed, 10000)
        self.assertEqual(n.status, "ok")
        self.assertEqual(n.ixlan, ixlan)
        self.assertEqual(n.asn, 2906)

        n2 = netixlans[1]
        self.assertEqual(unicode(n2.ipaddr4), u"195.69.147.250")
        self.assertEqual(unicode(n2.ipaddr6), u"2001:7f8:1::a500:2906:1")
        self.assertEqual(n2.speed, 10000)
        self.assertEqual(n2.status, "ok")
        self.assertEqual(n2.ixlan, ixlan)
        self.assertEqual(n.asn, 2906)

        # test that inactive connections had no effect
        self.assertEqual(NetworkIXLan.objects.filter(ipaddr4="195.69.146.251", speed=10000, status="ok").count(), 1)
        self.assertEqual(NetworkIXLan.objects.filter(ipaddr4="195.69.146.252").count(), 0)


        #self.assertEqual(IXLan.objects.get(id=ixlan.id).netixlan_set_active.count(), 2)

        #FIXME: this is not practical until
        #https://github.com/peeringdb/peeringdb/issues/90 is resolved
        #so skipping those tests right now
        #n_deleted.refresh_from_db()
        #n_deleted2.refresh_from_db()
        #self.assertEqual(n_deleted.ipaddr4, None)
        #self.assertEqual(n_deleted2.ipaddr6, None)

    def test_preview_from_ixf_ixp_member_list(self):
        ixlan = self.entities["ixlan"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data, save=False)
        self.assertLog(log, "preview_01")


    def test_update_from_ixf_ixp_member_list_skip_prefix_mismatch(self):
        """
        Here we test that entries with ipaddresses that cannot be validated
        against any of the prefixes that exist on the ixlan get skipped
        """
        ixlan = self.entities["ixlan"][1]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        self.assertLog(log, "skip_prefix_mismatch")
        self.assertEqual(len(netixlans), 0)

    def test_update_from_ixf_ixp_member_list_skip_missing_prefixes(self):
        """
        Here we test that nothing is done at all if the importer is run on an
        ixlan that does not have any prefixes
        """
        ixlan = self.entities["ixlan"][2]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        self.assertEqual(len(netixlans), 0)
        self.assertEqual(len(netixlans_deleted), 0)
        self.assertEqual(log["errors"], [u'No prefixes defined on ixlan'])

    def test_update_from_ixf_ixp_member_list_skip_disabled_networks(self):
        """
        Here we test that networks with allow_ixp_update set to False
        will not be processed
        """
        ixlan = self.entities["ixlan"][0]
        network = self.entities["net"][0]
        network.allow_ixp_update = False
        network.save()
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        self.assertLog(log, "skip_disabled_networks")
        self.assertEqual(len(netixlans), 0)

        for netixlan in network.netixlan_set_active.all():
            netixlan.refresh_from_db()
            self.assertEqual(netixlan.status, "ok")

    def test_update_from_ixf_ixp_member_list_logs(self):
        ixlan = self.entities["ixlan"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        attempt_dt_1 = ixlan.ixf_import_attempt.updated

        for netixlan in netixlans:
            log_entry = ixlan.ixf_import_log_set.last().entries.get(
                netixlan=netixlan)

            if netixlan.id in (self.entities["netixlan"][4].id, self.entities["netixlan"][5].id):
                # netixlan was modified
                self.assertEqual(
                    log_entry.version_before,
                    reversion.models.Version.objects.get_for_object(netixlan)[1])
            else:
                # netixlan was added
                self.assertEqual(
                    log_entry.version_before, None)

            self.assertEqual(
                log_entry.version_after,
                reversion.models.Version.objects.get_for_object(netixlan)[0])

        for netixlan in netixlans_deleted:
            log_entry = ixlan.ixf_import_log_set.last().entries.get(
                netixlan=netixlan)
            self.assertEqual(
                log_entry.version_before,
                reversion.models.Version.objects.get_for_object(netixlan)[1])
            self.assertEqual(
                log_entry.version_after,
                reversion.models.Version.objects.get_for_object(netixlan)[0])

        with reversion.create_revision():
            netixlans[0].speed = 10
            netixlans[0].save()

        time.sleep(0.1)

        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        ixlan.ixf_import_attempt.refresh_from_db()
        attempt_dt_2 = ixlan.ixf_import_attempt.updated

        self.assertNotEqual(attempt_dt_1, attempt_dt_2)
        self.assertEqual(ixlan.ixf_import_log_set.count(), 2)
        self.assertEqual(len(netixlans), 1)

        for netixlan in netixlans:
            log_entry = ixlan.ixf_import_log_set.last().entries.get(
                netixlan=netixlan)
            self.assertEqual(
                log_entry.version_before,
                reversion.models.Version.objects.get_for_object(netixlan)[1])
            self.assertEqual(
                log_entry.version_after,
                reversion.models.Version.objects.get_for_object(netixlan)[0])

    def test_rollback(self):
        ixlan = self.entities["ixlan"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        for entry in ixlan.ixf_import_log_set.last().entries.all():
            self.assertEqual(entry.rollback_status(), 0)

        ixlan.ixf_import_log_set.last().rollback()
        netixlans[0].refresh_from_db()
        netixlans[1].refresh_from_db()
        self.assertEqual(netixlans[0].status, "deleted")
        self.assertEqual(netixlans[1].status, "deleted")

        ixlan.ixf_import_log_set.last().refresh_from_db()

        for entry in ixlan.ixf_import_log_set.last().entries.all():
            self.assertEqual(entry.rollback_status(), 1)

    def test_rollback_avoid_ipaddress_conflict(self):
        ixlan = self.entities["ixlan"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        self.assertEqual(len(netixlans_deleted), 2)

        netixlan = netixlans_deleted[0]
        other = NetworkIXLan.objects.create(
            network=netixlan.network, ixlan=netixlan.ixlan, speed=1000,
            status="ok", asn=netixlan.asn + 1, ipaddr4=netixlan.ipaddr4)

        for entry in ixlan.ixf_import_log_set.last().entries.all():
            if entry.netixlan == netixlan:
                self.assertEqual(entry.rollback_status(), 2)

        ixlan.ixf_import_log_set.last().rollback()
        netixlan.refresh_from_db()
        self.assertEqual(netixlan.status, "deleted")

        other.delete(hard=True)

    def test_export_view_ixlan(self):
        """
        Test that the /export/ixlan/<ixlan_id>/ixp-member-list endpoint
        generates the expected result after importing a test data set
        """
        # we only export 0.6 version of the schema, so can skip this test
        # for the other versions
        if self.version != "0.6":
            return

        # import the data
        ixlan = self.entities["ixlan"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        # request the view and compare it agaisnt expected data
        c = Client()
        resp = c.get("/export/ixlan/{}/ixp-member-list".format(ixlan.id))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        with open(
                os.path.join(
                    os.path.dirname(__file__), "data", "json_members_list",
                    "export.json"), "r") as fh:
            expected = json.load(fh)
            data["timestamp"] = expected["timestamp"]
            self.assertEqual(data, expected)

        schema = requests.get(self.schema_url).json()
        jsonschema.validate(data, schema)

    def test_export_view_ix(self):
        """
        Test that the /export/ix/<ix_id>/ixp-member-list endpoint
        generates the expected result after importing a test data set
        """
        # we only export 0.6 version of the schema, so can skip this test
        # for the other versions
        if self.version != "0.6":
            return

        # import the data
        ixlan = self.entities["ixlan"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)

        # request the view and compare it agaisnt expected data
        c = Client()
        resp = c.get("/export/ix/{}/ixp-member-list".format(ixlan.ix.id))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        with open(
                os.path.join(
                    os.path.dirname(__file__), "data", "json_members_list",
                    "export.json"), "r") as fh:
            other = json.load(fh)
            data["timestamp"] = other["timestamp"]
            self.assertEqual(data, other)

        schema = requests.get(self.schema_url).json()
        jsonschema.validate(data, schema)

    def test_ixp_allow_update_default(self):
        self.assertEqual(self.entities["net"][2].allow_ixp_update, False)

    def test_command(self):
        """
        Test the ixf_ixp_member_import command
        """

        ixlan = self.entities["ixlan"][0]
        ixlan.ixf_ixp_member_list_url = "http://localhost:12345/ixf/member/import"
        ixlan.ixf_ixp_import_enabled = True
        ixlan.save()

        stdout = StringIO.StringIO()
        stderr = StringIO.StringIO()

        r = call_command("pdb_ixf_ixp_member_import", ixlan=[ixlan.id], commit=True, stdout=stdout, stderr=stderr)
        self.assertEqual(stdout.getvalue().find("Fetching data for -ixlan1 from"), 0)

        # importer should skip ixlans where ixf_ixp_import_enabled is
        # turned off

        ixlan.ixf_ixp_import_enabled = False
        ixlan.save()

        stdout = StringIO.StringIO()
        stderr = StringIO.StringIO()

        r = call_command("pdb_ixf_ixp_member_import", ixlan=[ixlan.id], commit=True, stdout=stdout, stderr=stderr)
        self.assertEqual(stdout.getvalue().find("Fetching data for -ixlan1 from"), -1)


    def test_postmortem(self):
        ixlan = self.entities["ixlan"][0]
        net = self.entities["net"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)
        request = RequestFactory().get("/import/net/{}/ixf/preview/".format(net.id))
        request.user = self.admin_user
        response = view_import_net_ixf_postmortem(request, net.id)

        assert response.status_code == 200
        content = json.loads(response.content)
        for entry in content["data"]:
            del entry["created"]
        self.assertLog(content, "postmortem_01")



    def test_postmortem_limit(self):
        ixlan = self.entities["ixlan"][0]
        net = self.entities["net"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)
        request = RequestFactory().get("/import/net/{}/ixf/postmortem/".format(net.id),{"limit":1})
        request.user = self.admin_user
        response = view_import_net_ixf_postmortem(request, net.id)

        content = json.loads(response.content)
        assert len(content["data"]) == 1


    def test_postmortem_limit_max(self):
        ixlan = self.entities["ixlan"][0]
        net = self.entities["net"][0]
        r, netixlans, netixlans_deleted, log = self.ixf_importer.update(ixlan, data=self.json_data)
        request = RequestFactory().get("/import/net/{}/ixf/postmortem/".format(net.id),{"limit":1000})
        request.user = self.admin_user
        response = view_import_net_ixf_postmortem(request, net.id)

        content = json.loads(response.content)
        assert len(content["data"]) == 6
        assert content["non_field_errors"] == ["Postmortem length cannot exceed 250 entries"]


    def test_import_postmortem_fail_ratelimit(self):
        net = self.entities["net"][0]
        request = RequestFactory().get("/import/net/{}/ixf/postmortem/".format(net.id))
        request.user = self.admin_user

        response = view_import_net_ixf_postmortem(request, net.id)
        assert response.status_code == 200

        response = view_import_net_ixf_postmortem(request, net.id)
        assert response.status_code == 400


    def test_import_postmortem_fail_permission(self):
        net = self.entities["net"][0]
        request = RequestFactory().get("/import/net/{}/ixf/postmortem/".format(net.id))
        request.user = self.guest_user

        response = view_import_net_ixf_postmortem(request, net.id)
        assert response.status_code == 403


    def test_net_preview(self):
        ixlan = self.entities["ixlan"][0]
        net = self.entities["net"][0]

        # simulate cached IX-F data
        ixlan.ixf_ixp_import_enabled = True
        ixlan.ixf_ixp_member_list_url = "test"
        ixlan.save()
        cache.set("IXF-CACHE-test", self.json_data)

        request = RequestFactory().get("/import/net/{}/ixf/preview/".format(net.id))
        request.user = self.admin_user
        response = view_import_net_ixf_preview(request, net.id)

        assert response.status_code == 200
        content = json.loads(response.content)
        self.assertLog(content, "preview_02")

    def test_net_preview_fail_ratelimit(self):
        net = self.entities["net"][0]
        request = RequestFactory().get("/import/net/{}/ixf/preview/".format(net.id))
        request.user = self.admin_user

        response = view_import_net_ixf_preview(request, net.id)
        assert response.status_code == 200

        response = view_import_net_ixf_preview(request, net.id)
        assert response.status_code == 400


    def test_net_preview_fail_permission(self):
        net = self.entities["net"][0]
        request = RequestFactory().get("/import/net/{}/ixf/preview/".format(net.id))
        request.user = self.guest_user

        response = view_import_net_ixf_preview(request, net.id)
        assert response.status_code == 403





class JsonMembersListTestCase_V05(JsonMembersListTestCase):
    version = "0.5"


class JsonMembersListTestCase_V04(JsonMembersListTestCase):
    version = "0.4"


class TestImportPreview(ClientCase):

    """
    Test the ixf import preview
    """

    @classmethod
    def setUpTestData(cls):
        super(TestImportPreview, cls).setUpTestData()
        cls.org = Organization.objects.create(name="Test Org", status="ok")
        cls.ix = InternetExchange.objects.create(name="Test IX", status="ok", org=cls.org)

        cls.ixlan = IXLan.objects.create(status="ok", ix=cls.ix)
        IXLanPrefix.objects.create(ixlan=cls.ixlan, status="ok",
                                   prefix="195.69.144.0/22", protocol="IPv4")
        IXLanPrefix.objects.create(ixlan=cls.ixlan, status="ok",
                                   prefix="2001:7f8:1::/64", protocol="IPv6")

        cls.net = Network.objects.create(org=cls.org, status="ok",
                                         asn=1000, name="net01")
        cls.net_2 = Network.objects.create(org=cls.org, status="ok",
                                           asn=1001, name="net02")


        cls.admin_user = User.objects.create_user("admin","admin@localhost","admin")

        cls.org.admin_usergroup.user_set.add(cls.admin_user)


    def test_import_preview(self):
        request = RequestFactory().get("/import/ixlan/{}/ixf/preview/".format(self.ixlan.id))
        request.user = self.admin_user

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)

        assert response.status_code == 200
        assert json.loads(response.content)["errors"] == ["IXF import url not specified"]


    def test_import_preview_fail_ratelimit(self):
        request = RequestFactory().get("/import/ixlan/{}/ixf/preview/".format(self.ixlan.id))
        request.user = self.admin_user

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)
        assert response.status_code == 200

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)
        assert response.status_code == 400


    def test_import_preview_fail_permission(self):
        request = RequestFactory().get("/import/ixlan/{}/ixf/preview/".format(self.ixlan.id))
        request.user = self.guest_user

        response = view_import_ixlan_ixf_preview(request, self.ixlan.id)
        assert response.status_code == 403


    def test_import_net_preview(self):
        request = RequestFactory().get("/import/net/{}/ixf/preview/".format(self.net.id))
        request.user = self.admin_user

        response = view_import_net_ixf_preview(request, self.net.id)

        assert response.status_code == 200


    def test_import_net_preview_fail_ratelimit(self):
        request = RequestFactory().get("/import/net/{}/ixf/preview/".format(self.net.id))
        request.user = self.admin_user

        response = view_import_net_ixf_preview(request, self.net.id)
        assert response.status_code == 200

        response = view_import_net_ixf_preview(request, self.net.id)
        assert response.status_code == 400


    def test_import_net_preview_fail_permission(self):
        request = RequestFactory().get("/import/net/{}/ixf/preview/".format(self.net.id))
        request.user = self.guest_user

        response = view_import_net_ixf_preview(request, self.net.id)
        assert response.status_code == 403


    def test_netixlan_diff(self):
        netix1 = NetworkIXLan.objects.create(
            network=self.net,
            ixlan=self.ixlan,
            status="ok",
            ipaddr4="195.69.146.250",
            ipaddr6="2001:7f8:1::a500:2906:1",
            asn=self.net.asn,
            speed=1000,
            is_rs_peer=True)

        netix2 = NetworkIXLan(
            network=self.net_2,
            status="ok",
            ipaddr4="195.69.146.250",
            ipaddr6="2001:7f8:1::a500:2906:2",
            asn=self.net_2.asn,
            speed=10000,
            is_rs_peer=False)

        result = self.ixlan.add_netixlan(netix2, save=False,
                                         save_others=False)

        self.assertEqual(sorted(result["changed"]), ['asn', 'ipaddr6',
                         'is_rs_peer', 'network_id', 'speed'])


        netix2.ipaddr4 = "195.69.146.251"
        netix2.ipaddr6 = netix1.ipaddr6

        result = self.ixlan.add_netixlan(netix2, save=False,
                                         save_others=False)

        self.assertEqual(sorted(result["changed"]), ['asn', 'ipaddr4',
                         'is_rs_peer', 'network_id', 'speed'])






