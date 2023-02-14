from unicodedata import name

import pytest
from django.test import Client, RequestFactory, TestCase

from peeringdb_server.deskpro import MockAPIClient as DeskProClient
from peeringdb_server.models import DeskProTicket, Group, User


@pytest.fixture
def admin_user():
    from django.conf import settings

    guest_group, _ = Group.objects.get_or_create(name="guest")
    user_group, _ = Group.objects.get_or_create(name="user")

    print(f"Guest: {guest_group} {guest_group.id} ")
    print(f"User: {user_group} {user_group.id} ")

    admin_user = User.objects.create_user("admin", "admin@localhost")
    admin_user.is_superuser = True
    admin_user.is_staff = True
    admin_user.save()
    admin_user.set_password("admin")
    admin_user.save()
    return admin_user


@pytest.mark.django_db
def test_deskpro_person_noname(admin_user):
    deskpro_client = DeskProClient("", "")

    payload = deskpro_client.update_person_payload(
        {"primary_email": admin_user.email}, admin_user, admin_user.email
    )

    assert payload.get("name") == admin_user.username


@pytest.mark.django_db
def test_deskpro_person_email(admin_user):
    deskpro_client = DeskProClient("", "")

    admin_user.first_name = "Django"
    admin_user.last_name = "User"
    admin_user.save()

    payload = deskpro_client.update_person_payload(
        {"primary_email": admin_user.email}, None, admin_user.email
    )

    assert payload.get("name") == admin_user.email


@pytest.mark.django_db
def test_deskpro_person(admin_user):
    deskpro_client = DeskProClient("", "")

    admin_user.first_name = "Django"
    admin_user.last_name = "User"
    admin_user.save()

    payload = deskpro_client.update_person_payload(
        {"primary_email": admin_user.email}, admin_user, admin_user.email
    )

    assert payload.get("name") == "Django User"
