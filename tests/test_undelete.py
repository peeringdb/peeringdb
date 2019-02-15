import datetime

from util import ClientCase, Group

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.conf import settings

from peeringdb_server.models import REFTAG_MAP
from peeringdb_server.management.commands.pdb_undelete import Command


class TestUndelete(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super(TestUndelete, cls).setUpTestData()
        call_command("pdb_generate_test_data", limit=2, commit=True)

        cls.org_a = REFTAG_MAP["org"].objects.get(id=1)
        cls.org_b = REFTAG_MAP["org"].objects.get(id=2)

        cls.net_a = cls.org_a.net_set.first()

        cls.ix_a = cls.org_a.ix_set.first()
        cls.ix_b = cls.org_b.ix_set.first()

        cls.fac_a = cls.org_a.fac_set.first()
        cls.fac_b = cls.org_b.fac_set.first()

        cls.ixlan_a = cls.ix_a.ixlan_set.first()
        cls.ixlan_b = cls.ix_b.ixlan_set.first()

        cls.date = datetime.date

    @property
    def _command(self):
        command = Command()
        command.commit = True
        return command

    def _undelete(self, obj):
        command = self._command
        command.date = obj.updated
        command.undelete(obj.HandleRef.tag, obj.id)
        obj.refresh_from_db()

    def test_undelete_ixlan(self):
        assert self.ixlan_a.netixlan_set_active.count() == 1
        assert self.ixlan_a.ixpfx_set_active.count() == 2

        self.ixlan_a.delete()

        assert self.ixlan_a.status == "deleted"

        self._undelete(self.ixlan_a)

        assert self.ixlan_a.status == "ok"
        assert self.ixlan_a.netixlan_set_active.count() == 1
        assert self.ixlan_a.ixpfx_set_active.count() == 2

    def test_undelete_fac(self):
        assert self.fac_a.netfac_set_active.count() == 1
        assert self.fac_a.ixfac_set_active.count() == 1

        self.fac_a.delete()

        assert self.fac_a.status == "deleted"

        self._undelete(self.fac_a)

        assert self.fac_a.status == "ok"
        assert self.fac_a.netfac_set_active.count() == 1
        assert self.fac_a.ixfac_set_active.count() == 1

    def test_undelete_ixlan_netixlan_dupe_other(self):
        netixlan_a = self.ixlan_a.netixlan_set.first()
        self.ixlan_a.delete()
        netixlan_c = REFTAG_MAP["netixlan"].objects.create(
            asn=self.net_a.asn, ixlan=self.ixlan_b, status="ok",
            ipaddr4=netixlan_a.ipaddr4, network=self.net_a, speed=100)
        self._undelete(self.ixlan_a)

        assert self.ixlan_a.status == "ok"
        assert self.ixlan_a.netixlan_set_active.count() == 0

    def test_undelete_ixlan_netixlan_dupe_other_ipv6(self):
        netixlan_a = self.ixlan_a.netixlan_set.first()
        self.ixlan_a.delete()
        netixlan_c = REFTAG_MAP["netixlan"].objects.create(
            asn=self.net_a.asn, ixlan=self.ixlan_b, status="ok",
            ipaddr6=netixlan_a.ipaddr6, network=self.net_a, speed=100)
        self._undelete(self.ixlan_a)

        assert self.ixlan_a.status == "ok"
        assert self.ixlan_a.netixlan_set_active.count() == 0

    def test_undelete_ixlan_netixlan_dupe_same_ix(self):
        ixlan_c = REFTAG_MAP["ixlan"].objects.create(ix=self.ix_a, status="ok")
        netixlan_a = self.ixlan_a.netixlan_set.first()
        self.ixlan_a.delete()
        netixlan_c = REFTAG_MAP["netixlan"].objects.create(
            asn=self.net_a.asn, ixlan=ixlan_c, status="ok",
            ipaddr4=netixlan_a.ipaddr4, network=self.net_a, speed=100)

        assert ixlan_c.netixlan_set_active.count() == 1

        self._undelete(self.ixlan_a)

        assert self.ixlan_a.status == "ok"
        assert self.ixlan_a.netixlan_set_active.count() == 1
        assert ixlan_c.netixlan_set_active.count() == 0

    def test_undelete_ixlan_netixlan_dupe_same_ix_ipv6(self):
        ixlan_c = REFTAG_MAP["ixlan"].objects.create(ix=self.ix_a, status="ok")
        netixlan_a = self.ixlan_a.netixlan_set.first()
        self.ixlan_a.delete()
        netixlan_c = REFTAG_MAP["netixlan"].objects.create(
            asn=self.net_a.asn, ixlan=ixlan_c, status="ok",
            ipaddr6=netixlan_a.ipaddr6, network=self.net_a, speed=100)

        assert ixlan_c.netixlan_set_active.count() == 1

        self._undelete(self.ixlan_a)

        assert self.ixlan_a.status == "ok"
        assert self.ixlan_a.netixlan_set_active.count() == 1
        assert ixlan_c.netixlan_set_active.count() == 0
