import StringIO

from util import ClientCase, Group

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.conf import settings

from peeringdb_server.models import REFTAG_MAP


class TestWipe(ClientCase):

    @classmethod
    def setUpTestData(cls):
        super(TestWipe, cls).setUpTestData()
        call_command("pdb_generate_test_data", limit=1, commit=True)

    def test_run(self):
        ix = REFTAG_MAP["ix"].objects.all().first()

        ixlan = ix.ixlan_set_active.all().first()

        for ixpfx in ixlan.ixpfx_set.all():
            print(ixpfx.descriptive_name)

        for netixlan in ixlan.netixlan_set.all():
            print(netixlan.descriptive_name)

        #ixpfx1 206.223.116.0/23
        #ixpfx2 2001:504:0:1::/64
        #netixlan1 AS63314 206.223.116.101 2001:504:0:1::65

        call_command("pdb_renumber_lans", ix=1, old=u"206.223.116.0/23", new=u"206.223.110.0/23", commit=True)

        assert ixlan.ixpfx_set.get(id=1).prefix.compressed == u"206.223.110.0/23"
        assert ixlan.netixlan_set.get(id=1).ipaddr4.compressed == u"206.223.110.101"

        call_command("pdb_renumber_lans", ix=1, old=u"2001:504:0:1::/64", new=u"2001:504:0:2::/64", commit=True)

        assert ixlan.ixpfx_set.get(id=2).prefix.compressed == u"2001:504:0:2::/64"
        assert ixlan.netixlan_set.get(id=1).ipaddr6.compressed == u"2001:504:0:2::65"


