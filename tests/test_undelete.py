import datetime

import reversion
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from peeringdb_server.management.commands.pdb_undelete import Command
from peeringdb_server.models import REFTAG_MAP

from .util import ClientCase, Group


class TestUndelete(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("pdb_generate_test_data", limit=2, commit=True)

        cls.org_a = REFTAG_MAP["org"].objects.first()
        cls.org_b = REFTAG_MAP["org"].objects.exclude(id=cls.org_a.id).first()

        cls.net_a = cls.org_a.net_set.first()

        cls.ix_a = cls.org_a.ix_set.first()
        cls.ix_b = cls.org_b.ix_set.first()

        cls.fac_a = cls.org_a.fac_set.first()
        cls.fac_b = cls.org_b.fac_set.first()

        cls.carrier_a = cls.org_a.carrier_set.first()
        cls.carrier_b = cls.org_b.carrier_set.first()

        cls.campus_a = cls.org_a.campus_set.first()
        cls.campus_b = cls.org_b.campus_set.first()

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

        # need to manually delete all the netixlans so
        # the ixlan becomes deletable

        self.ixlan_a.netixlan_set_active.update(status="deleted")
        self.ixlan_a.delete()

        assert self.ixlan_a.status == "deleted"

        self._undelete(self.ixlan_a)

        assert self.ixlan_a.status == "ok"

        # as ixlans with active netixlans can no longer be deleted
        # they will not be recoverable from the same revision
        # TODO: broken and probably not needed anymore?
        # assert self.ixlan_a.netixlan_set_active.count() == 1

        assert self.ixlan_a.ixpfx_set_active.count() == 2

    def test_undelete_carrier(self):
        assert self.carrier_a.carrierfac_set.count() == 1

        # need to manually delete ixfacs and netfacs so
        # the facility becomes deletable

        self.carrier_a.carrierfac_set_active.all().update(status="deleted")
        self.carrier_a.delete()

        assert self.carrier_a.status == "deleted"

        self._undelete(self.carrier_a)

        assert self.carrier_a.status == "ok"

    def test_undelete_fac(self):
        assert self.fac_a.netfac_set_active.count() == 1
        assert self.fac_a.ixfac_set_active.count() == 1

        # need to manually delete ixfacs and netfacs so
        # the facility becomes deletable

        self.fac_a.ixfac_set_active.all().update(status="deleted")
        self.fac_a.netfac_set_active.all().update(status="deleted")
        self.fac_a.delete()

        assert self.fac_a.status == "deleted"

        self._undelete(self.fac_a)

        assert self.fac_a.status == "ok"

        # as facilities with active ixfac or netfac can no longer
        # be deleted they will not be recoverable from the same revision
        # TODO: broken and probably not needed anymore?
        # assert self.fac_a.netfac_set_active.count() == 1
        # assert self.fac_a.ixfac_set_active.count() == 1
