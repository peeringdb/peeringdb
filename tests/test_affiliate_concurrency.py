"""
Concurrency test for issue #1945 — verifies that two simultaneous
affiliation POSTs from the same user to the same org cannot create
duplicate pending UserOrgAffiliationRequest rows.

Requires a DB with real SELECT ... FOR UPDATE row-level locking
(PostgreSQL or MySQL/InnoDB). Skipped on SQLite where the statement
is a no-op.
"""

import json
import threading

from django.contrib.auth.models import Group
from django.db import connection, connections
from django.test import RequestFactory, TransactionTestCase

import peeringdb_server.models as models
import peeringdb_server.views as pdbviews

from .util import mock_csrf_session


class AffiliateConcurrencyTestCase(TransactionTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        Group.objects.get_or_create(name="guest")
        Group.objects.get_or_create(name="user")
        self.user = models.User.objects.create_user(
            "race_user", "race_user@localhost", "race_user"
        )
        models.EmailAddress.objects.create(
            user=self.user,
            email="race_user@localhost",
            verified=True,
            primary=True,
        )
        self.org = models.Organization.objects.create(name="Race Org", status="ok")

    def test_concurrent_affiliation_no_duplicates(self):
        """
        Two threads POST the same (user, org) affiliation simultaneously.
        Exactly one UOAR row must be created; the other thread must see
        a 400 "already requested" response. Verifies the select_for_update
        lock in view_affiliate_to_org closes the TOCTOU race described in
        issue #1945.
        """
        if connection.vendor == "sqlite":
            self.skipTest(
                "SQLite does not honor SELECT ... FOR UPDATE row-level locking"
            )

        barrier = threading.Barrier(2)
        responses = []
        errors = []
        result_lock = threading.Lock()

        def submit():
            try:
                barrier.wait()
                request = self.factory.post(
                    "/affiliate-to-org", data={"org": str(self.org.id)}
                )
                request.user = self.user
                mock_csrf_session(request)
                resp = pdbviews.view_affiliate_to_org(request)
                with result_lock:
                    responses.append((resp.status_code, json.loads(resp.content)))
            except Exception as exc:
                with result_lock:
                    errors.append(exc)
            finally:
                connections.close_all()

        t1 = threading.Thread(target=submit)
        t2 = threading.Thread(target=submit)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(errors, [])

        status_codes = sorted(r[0] for r in responses)
        self.assertEqual(status_codes, [200, 400])

        rejected = next(body for status, body in responses if status == 400)
        self.assertIn("non_field_errors", rejected)
        self.assertIn("already requested", rejected["non_field_errors"][0].lower())

        self.assertEqual(
            models.UserOrgAffiliationRequest.objects.filter(
                user=self.user, org=self.org, status="pending"
            ).count(),
            1,
        )
