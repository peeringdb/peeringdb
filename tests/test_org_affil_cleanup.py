import re
import sys
from datetime import timedelta
from io import StringIO
from sys import stdout
from unittest.mock import ANY, MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from reversion import create_revision

from peeringdb_server.models import Organization, User, UserOrgAffiliationRequest


class TestDeleteOldRequests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with create_revision():
            cls.org = Organization.objects.create(name="Test Org")

            # Add users to admin usergroup
            for index in range(0, 3):
                user = User.objects.create_user(
                    username=f"admin_user_{index}",
                    email=f"admin_user_{index}@localhost",
                    first_name=f"admin_user_{index}",
                    last_name=f"admin_user_{index}",
                )
                cls.org.admin_usergroup.user_set.add(user)
                user.save()
                cls.org.save()

            # Add affiliation requests (all outdated)
            for index in range(0, 3):
                user = User.objects.create_user(
                    username=f"user_{index}",
                    email=f"user_{index}@localhost",
                    first_name=f"user_{index}",
                    last_name=f"user_{index}",
                )
                created_date = timezone.now() - timedelta(days=2)  # Set all outdated
                cls.org.affiliation_requests.create(
                    user=user,
                    status="pending",
                    created=created_date,
                )

    def test_delete_old_requests_dry_run(self):
        # Capture output
        output = StringIO()

        # Call the command with dry-run flag commit=False
        call_command(
            "pdb_delete_outdated_pending_affil_request",
            days_old=0,
            commit=False,
            stdout=output,
        )

        # Verify dry-run message
        expected_message = f"Dry Run: Would have deleted {UserOrgAffiliationRequest.objects.filter(status='pending').count()} old pending requests."
        actual_output = output.getvalue().strip()

        assert expected_message in actual_output

    def test_delete_old_requests_with_limit(self):
        # Capture output
        output = StringIO()

        # Call the command with limit and commit (ensure commit=True)
        call_command(
            "pdb_delete_outdated_pending_affil_request",
            days_old=0,
            commit=True,
            limit=2,
            stdout=output,
        )

        actual_output = output.getvalue().strip()

        # Verify deletion and success message (adjust for limit)
        assert UserOrgAffiliationRequest.objects.count() == 1

        assert "Successfully deleted 2 old pending requests." in actual_output

    def test_delete_old_requests_no_limit(self):
        # Capture output
        output = StringIO()

        count = UserOrgAffiliationRequest.objects.all().count()

        # Call the command with no limit and commit (ensure commit=True)
        call_command(
            "pdb_delete_outdated_pending_affil_request",
            days_old=0,
            commit=True,
            stdout=output,
        )

        # Verify deletion and success message (count from objects)
        assert UserOrgAffiliationRequest.objects.count() == 0
        assert (
            f"Successfully deleted {count} old pending requests."
            in output.getvalue().strip()
        )
