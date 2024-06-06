from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.template import loader
from django.utils import timezone

from peeringdb_server.management.commands.pdb_delete_outdated_pending_affil_request import (
    Command,
)
from peeringdb_server.models import Group, Organization, User, UserOrgAffiliationRequest


def send_mail(recipient, subject, template_name, context):
    return loader.get_template(template_name).render(context)


@pytest.mark.django_db
def test_pdb_delete_outdated_pending_affil_request():
    org = Organization.objects.create(id=1000, name="test_org")
    group = Group.objects.get(name=org.admin_usergroup)
    user = User.objects.create(
        username="user", email="user@user.com", first_name="test ", last_name="user"
    )
    User.objects.create(username="user_1", email="user1@test.com").groups.add(group)
    User.objects.create(username="user_2", email="user2@test.com").groups.add(group)
    uoar_list = [
        UserOrgAffiliationRequest(
            user=user,
            asn=123,
            org_id=org.pk,
            org_name="test uoar",
            status="pending",
        ),
        UserOrgAffiliationRequest(
            user=user,
            asn=123,
            org_id=None,
            org_name="test uoar 2",
            status="pending",
        ),
        UserOrgAffiliationRequest(
            user=user,
            asn=None,
            org_id=None,
            org_name="test uoar 3",
            status="pending",
        ),
    ]

    expected_uoar_email_org_name = ["test_org", "AS123", "test uoar 3"]
    UserOrgAffiliationRequest.objects.bulk_create(uoar_list)
    UserOrgAffiliationRequest.objects.all().update(
        created=timezone.now() - timezone.timedelta(days=100)
    )
    with patch.object(Command, "send_email", side_effect=send_mail) as mock_send_email:
        call_command("pdb_delete_outdated_pending_affil_request", commit=True)
        calls = mock_send_email.call_args_list
        assert mock_send_email.call_count == 5
        # notify-org-admin = 2
        # notify-user = 3
        for call in calls:
            if (
                call[1].get("template_name")
                == "email/notify-user-old-pending-uoar-deleted.txt"
            ):
                expected_uoar_email_org_name.remove(call[1]["context"]["org"])
        assert expected_uoar_email_org_name == []
