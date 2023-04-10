from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from peeringdb_server.models import (
    EmailAddress,
    EmailAddressData,
    Network,
    Organization,
    User,
)
from tests.util import reset_group_ids


@pytest.mark.django_db
@pytest.fixture
def reauth_objects():
    reset_group_ids()

    org = Organization.objects.create(name="Test", status="ok")
    org_b = Organization.objects.create(name="Test B", status="ok")
    net = Network.objects.create(name="Test", asn=63311, status="ok", org=org)
    net_b = Network.objects.create(name="Test B", asn=63312, status="ok", org=org_b)
    user = User.objects.create_user(
        "user_a", password="user_a", email="user_a@localhost"
    )
    user_b = User.objects.create_user(
        "user_b", password="user_b", email="user_b@domain.com"
    )
    user_c = User.objects.create_user(
        "user_c", password="user_c", email="user_c@domain.com"
    )
    email = EmailAddress.objects.create(user=user, email=user.email, verified=True)
    email_b = EmailAddress.objects.create(user=user, email="user_a@domain.com")
    email_data = EmailAddressData.objects.create(
        email=email, confirmed_date=timezone.now()
    )
    email_data_b = EmailAddressData.objects.create(
        email=email_b, confirmed_date=timezone.now()
    )
    email_c = EmailAddress.objects.create(
        user=user_b, email="user_b@domain.com", verified=True
    )
    user.set_verified()
    user_c.set_verified()

    user.grainy_permissions.add_permission(
        f"peeringdb.organization.{org.id}.network.{net.id}", 15
    )
    user.grainy_permissions.add_permission(
        f"peeringdb.organization.{org_b.id}.network.{net_b.id}", 15
    )

    org.usergroup.user_set.add(user)
    org.admin_usergroup.user_set.add(user_c)
    org_b.usergroup.user_set.add(user)

    return {
        "org": org,
        "org_b": org_b,
        "net": net,
        "net_b": net_b,
        "user": user,
        "user_b": user_b,
        "email": email,
        "email_data": email_data,
    }


@pytest.mark.django_db
def test_restrict_emails(reauth_objects):
    org = reauth_objects["org"]
    user = reauth_objects["user"]

    # no email restriction in place

    email_qs = EmailAddress.objects.filter(user=user).order_by("-verified")
    email_list = list(email_qs.values_list("email", flat=True))

    assert org.user_meets_email_requirements(user) == ([], email_list)

    # test 1: restrict user emails but provide no domains
    # email should not be restricted

    org.restrict_user_emails = True
    org.save()

    assert org.user_meets_email_requirements(user) == ([], email_list)

    # test 2: restrict user emails and provide domains
    # restriction should be in place
    # user does not meet requirements

    org.email_domains = "xyz.com"
    org.save()

    assert org.user_meets_email_requirements(user) == (email_list, [])

    # test 3: user meets requirements
    # email matching domain requirements should be returned

    EmailAddress.objects.create(user=user, email="user_b@xyz.com", verified=True)

    updated_email_qs = EmailAddress.objects.filter(user=user).order_by("-verified")
    updated_email_list = list(updated_email_qs.values_list("email", flat=True))
    valid_email_list = list(
        updated_email_qs.filter(email__endswith="xyz.com").values_list(
            "email", flat=True
        )
    )
    invalid_email_list = list(
        updated_email_qs.exclude(email__endswith="xyz.com").values_list(
            "email", flat=True
        )
    )

    assert org.user_meets_email_requirements(user) == (
        invalid_email_list,
        valid_email_list,
    )

    # test 4: turn off restrictions again, return users primary email

    org.restrict_user_emails = False
    org.save()

    assert org.user_meets_email_requirements(user) == ([], updated_email_list)


@pytest.mark.django_db
def test_restrict_emails_blocks_affiliations(reauth_objects):
    org = reauth_objects["org"]
    user = reauth_objects["user_b"]

    client = Client()
    client.force_login(user)

    org.restrict_user_emails = True
    org.email_domains = "xyz.com"
    org.save()

    email_list = list(
        EmailAddress.objects.filter(user=user)
        .order_by("-verified")
        .values_list("email", flat=True)
    )

    assert org.user_meets_email_requirements(user) == (email_list, [])

    client.post("/affiliate-to-org", data={"asn": 63311})

    assert not user.pending_affiliation_requests.exists()
    assert user.affiliation_requests.filter(status="denied").count() == 1


@pytest.mark.django_db
def test_trigger_reauth(reauth_objects):
    user = reauth_objects["user"]
    org = reauth_objects["org"]
    email = reauth_objects["email"]
    net = reauth_objects["net"]
    net_b = reauth_objects["net_b"]

    client = Client()
    client.force_login(user)

    # check that the user has write permissions to both networks at both organizations

    content = client.get(f"/net/{net.id}").content.decode()

    assert "<!-- toggle edit mode -->" in content

    content = client.get(f"/net/{net_b.id}").content.decode()

    assert "<!-- toggle edit mode -->" in content

    # test 1: test that no re-auth is triggered when its disabled

    content = client.get(f"/org/{org.id}").content.decode()

    assert (
        "Some of your organizations request that you confirm your email address"
        not in content
    )

    email.refresh_from_db()

    assert email.verified

    # test 2: test that no re-auth is triggered when its enabled, but email was
    # confirmed with in period

    org.periodic_reauth = True
    org.periodic_reauth_period = "1y"
    org.save()

    email.data.confirmed_date = timezone.now() - timedelta(days=1)
    email.data.save()

    content = client.get(f"/org/{org.id}").content.decode()

    assert (
        "Some of your organizations request that you confirm your email address"
        not in content
    )

    email.refresh_from_db()

    assert email.verified

    # test 3: test that re-auth is triggered when its enabled, and email wasn't confirmed
    # within period

    email.data.confirmed_date = timezone.now() - timedelta(days=400)
    email.data.save()

    content = client.get(f"/org/{org.id}").content.decode()

    email.refresh_from_db()

    assert not email.verified

    assert (
        "Some of your organizations request that you confirm your email address"
        in content
    )

    # user should no longer have write permissions to network at first organization

    content = client.get(f"/net/{net.id}").content.decode()

    assert "<!-- toggle edit mode -->" not in content

    # user should still have write permissions to network at second organization

    content = client.get(f"/net/{net_b.id}").content.decode()

    assert "<!-- toggle edit mode -->" in content

    # test 4: confirm email

    email.data.confirmed_date = timezone.now()
    email.data.save()
    email.verified = True
    email.save()

    content = client.get(f"/net/{net.id}").content.decode()

    assert "<!-- toggle edit mode -->" in content

    content = client.get(f"/org/{org.id}").content.decode()

    assert (
        "Some of your organizations request that you confirm your email address"
        not in content
    )

    email.refresh_from_db()

    assert email.verified
