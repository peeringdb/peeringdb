import io
import sys

from django.core.management import call_command

from peeringdb_server.models import REFTAG_MAP

from .util import ClientCase


class TestWhois(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org = REFTAG_MAP["org"].objects.create(name="Test org", status="ok")
        cls.net = REFTAG_MAP["net"].objects.create(
            name="Test net", status="ok", asn=63311, org=cls.org
        )
        cls.pocs = []
        for visibility in ["Private", "Users", "Public"]:
            cls.pocs.append(
                REFTAG_MAP["poc"].objects.create(
                    network=cls.net,
                    status="ok",
                    role="Abuse",
                    name=f"POC-{visibility}",
                    email=f"{visibility}@localhost",
                    visible=visibility,
                )
            )

    def test_whois_perms(self):
        """
        test that anonymous user permissions are applied
        to whois output - any pocs other than public ones should
        be excluded
        """

        # whois does not go to the command's stdout so we need to
        # capture the output through sys.stdout
        out = io.StringIO()
        oldout = sys.stdout
        sys.stdout = out

        call_command("pdb_whois", "as63311")

        # restore sys.stdout
        sys.stdout = oldout

        out = out.getvalue()

        assert "POC-Private" not in out
        assert "POC-Users" not in out
        assert "POC-Public" in out
