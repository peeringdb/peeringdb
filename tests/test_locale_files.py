import os
import re
from string import Formatter

from django.conf import settings
from django.test import Client, TestCase

from peeringdb_server.models import Organization, User


class LocaleFilesTest(TestCase):
    def load_messages(self, language, filename="django.po"):
        path = os.path.join(
            os.path.dirname(__file__), "..", "locale", language, "LC_MESSAGES"
        )
        with open(os.path.join(path, filename)) as fh:
            content = fh.read()
            message_id = re.findall(r"\nmsgid (.+)\n", content)
            message_str = re.findall(r"\nmsgstr (.+)\n", content)
            messages = dict(list(zip(message_id, message_str)))
        return messages

    # weblate handles all this now, and these tests are failing
    # atm because the locale files no longer reside here
    #
    # weblate also makes sure that variable formatting matches, so this
    # test is somewhat redundant at this point.
    #
    # either need to redo this test and make sure it generates the locale
    # or remove it.
    def _test_pt(self):
        """
        Test portuguese locale files
        """
        self.assert_variables(
            self.load_messages("en_US"), self.load_messages("pt"), "PT"
        )
        self.assert_variables(
            self.load_messages("en_US", filename="djangojs.po"),
            self.load_messages("pt", filename="djangojs.po"),
            "PT",
        )

    def assert_variables(self, en_messages, other_messages, language):
        """
        Assert that the correct formatting variables exist
        """
        errors = 0

        for msgid, msgstr in list(en_messages.items()):
            # %(name)s and %s type variables
            variables_a = sorted(re.findall(r"%\([^\(]+\)s|%s", msgid))
            variables_b = sorted(re.findall(r"%\([^\(]+\)s|%s", other_messages[msgid]))
            if variables_a != variables_b:
                errors += 1
                print(
                    f"{language} Locale variable error at msgid {msgid} -> {other_messages[msgid]}"
                )

            # {name} and {} type variables
            variables_a = sorted(
                fn for _, fn, _, _ in Formatter().parse(msgid) if fn is not None
            )
            variables_b = [
                fn
                for _, fn, _, _ in Formatter().parse(other_messages[msgid])
                if fn is not None
            ]
            if variables_a != variables_b:
                errors += 1
                print(
                    f"{language} Locale variable error at msgid {msgid} -> {other_messages[msgid]}"
                )

        assert errors == 0
