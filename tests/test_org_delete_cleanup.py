import io
from datetime import timedelta
from unicodedata import name

import pytest
import reversion
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone
from reversion.models import Version

from peeringdb_server.models import Organization, User

from .util import ClientCase, Group


class TestOrgCleanup(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with reversion.create_revision():
            cls.org = Organization.objects.create(name="Test Org")

            # Add user to all orgs' admin_usergroups
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

                # Add affiliation request to org
                cls.org.affiliation_requests.create(
                    user=user,
                    status="pending",
                    created=timezone.now() - timedelta(days=1),
                )

            # Add user to all orgs' usergroups
            for index in range(0, 3):
                user = User.objects.create_user(
                    username=f"user_{index}",
                    email=f"user_{index}@localhost",
                    first_name=f"user_{index}",
                    last_name=f"user_{index}",
                )
                cls.org.usergroup.user_set.add(user)
                user.save()
                cls.org.save()

    def test_org_delete(self):
        # Assert that all orgs have 3 users

        assert self.org.admin_usergroup.user_set.count() == 3
        assert self.org.usergroup.user_set.count() == 3

        # Assert that all orgs have 3 affiliation request
        assert self.org.affiliation_requests.count() == 3

        # Delete Organization
        self.org.delete()

        # Assert that all users in org are removed
        assert self.org.admin_usergroup.user_set.count() == 0
        assert self.org.usergroup.user_set.count() == 0

        # Assert that org affiliation requests is cancelled
        assert self.org.affiliation_requests.count() == 0
