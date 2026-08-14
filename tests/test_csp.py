from csp.constants import HEADER
from django.conf import settings
from django.test import Client

from .util import ClientCase


class CSPTest(ClientCase):
    """
    django-csp only emits a policy for the settings format of the version
    installed -- the pre-4.0 CSP_* settings are silently ignored by 4.x, so a
    bad settings migration drops the header entirely without failing anything
    else (#1933).
    """

    def test_csp_header_present(self):
        resp = Client().get("/apidocs/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(HEADER, resp)

        policy = resp[HEADER]
        for directive, sources in settings.CONTENT_SECURITY_POLICY[
            "DIRECTIVES"
        ].items():
            self.assertIn(directive, policy)
            for source in sources:
                self.assertIn(source, policy)
