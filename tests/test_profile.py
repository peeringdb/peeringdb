import pytest
from django.contrib.admin.models import LogEntry
from django.test import Client
from django.urls import reverse

from peeringdb_server.models import EmailAddress, User
from tests.util import reset_group_ids


@pytest.fixture
def profile_user():
    reset_group_ids()

    user = User.objects.create_user(
        username="user", password="user", email="user@localhost"
    )
    user.set_verified()

    EmailAddress.objects.create(
        email="user@localhost", verified=True, user=user, primary=True
    )

    user_b = User.objects.create_user("user_b", "user_b", "user@xyz.com")
    EmailAddress.objects.create(email="user@xyz..com", verified=True, user=user)

    return user


@pytest.mark.django_db
def test_add_email(profile_user):
    user = profile_user

    client = Client()
    client.force_login(profile_user)

    response = client.post(
        reverse("profile-add-email"),
        {"email": "user@domain.com", "password": "user", "primary": False},
    )

    assert response.status_code == 200

    user.refresh_from_db()

    assert user.emailaddress_set.filter(email="user@domain.com").exists()
    assert user.email == "user@localhost"

    assert LogEntry.objects.filter(
        change_message="User added email address user@domain.com"
    ).exists()


@pytest.mark.django_db
def test_add_email_and_make_primary(profile_user):
    user = profile_user

    client = Client()
    client.force_login(profile_user)

    response = client.post(
        reverse("profile-add-email"),
        {"email": "user@domain.com", "password": "user", "primary": "true"},
    )

    assert response.status_code == 200

    user.refresh_from_db()

    assert user.emailaddress_set.filter(email="user@domain.com", primary=True).exists()
    assert user.emailaddress_set.filter(primary=True).count() == 1
    assert user.email == "user@domain.com"


@pytest.mark.django_db
def test_remove_email(profile_user):
    user = profile_user

    client = Client()
    client.force_login(profile_user)

    EmailAddress.objects.create(user=user, email="user@domain.com", verified=True)
    assert user.emailaddress_set.filter(email="user@domain.com").exists()

    response = client.post(
        reverse("profile-remove-email"),
        {
            "email": "user@domain.com",
        },
    )

    assert response.status_code == 200

    user.refresh_from_db()

    assert not user.emailaddress_set.filter(email="user@domain.com").exists()

    assert LogEntry.objects.filter(
        change_message="User removed email address user@domain.com"
    ).exists()


@pytest.mark.django_db
def test_remove_email_cannot_remove_primary(profile_user):
    user = profile_user

    client = Client()
    client.force_login(profile_user)

    EmailAddress.objects.create(user=user, email="user@domain.com", verified=True)
    assert user.emailaddress_set.filter(email="user@domain.com").exists()

    response = client.post(
        reverse("profile-remove-email"),
        {
            "email": "user@localhost",
        },
    )

    assert response.status_code == 400

    user.refresh_from_db()

    assert user.emailaddress_set.filter(email="user@localhost").exists()


@pytest.mark.django_db
def test_change_primary(profile_user):
    user = profile_user

    client = Client()
    client.force_login(profile_user)

    EmailAddress.objects.create(user=user, email="user@domain.com", verified=True)
    assert user.emailaddress_set.filter(email="user@domain.com").exists()

    response = client.post(
        reverse("profile-set-primary-email"),
        {
            "email": "user@domain.com",
        },
    )

    assert response.status_code == 200

    user.refresh_from_db()

    assert user.emailaddress_set.filter(email="user@domain.com", primary=True).exists()
    assert user.emailaddress_set.filter(primary=True).count() == 1
    assert user.email == "user@domain.com"
