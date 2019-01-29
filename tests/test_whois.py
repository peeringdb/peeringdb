from peeringdb_server.models import REFTAG_MAP
from django.core.management import call_command
from util import ClientCase

import StringIO
import sys


class TestWhois(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super(TestWhois, cls).setUpTestData()
        cls.org = REFTAG_MAP["org"].objects.create(name="Test org",
                                                   status="ok")
        cls.net = REFTAG_MAP["net"].objects.create(
            name="Test net", status="ok", asn=63311, org=cls.org)
        cls.pocs = []
        for visibility in ["Private", "Users", "Public"]:
            cls.pocs.append(REFTAG_MAP["poc"].objects.create(
                network=cls.net, status="ok", role="Abuse",
                name="POC-{}".format(visibility),
                email="{}@localhost".format(visibility), visible=visibility))

    def test_whois_perms(self):
        """
        test that anonymous user permissions are applied
        to whois output - any pocs other than public ones should
        be excluded
        """

        # whois does not go to the command's stdout so we need to
        # capture the output through sys.stdout
        out = StringIO.StringIO()
        oldout = sys.stdout
        sys.stdout = out

        call_command("pdb_whois", "as63311")

        # restore sys.stdout
        sys.stdout = oldout

        out = out.getvalue()

        assert out.find("POC-Private") == -1
        assert out.find("POC-Users") == -1
        assert out.find("POC-Public") > -1
