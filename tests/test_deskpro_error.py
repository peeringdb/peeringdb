import io
from unicodedata import name

import pytest
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase

import peeringdb_server.deskpro as deskpro
from peeringdb_server.models import DeskProTicket, Group, User

APIClient = deskpro.APIClient


def setup_module(module):
    deskpro.APIClient = deskpro.FailingMockAPIClient


def teardown_module(module):
    deskpro.APIClient = APIClient


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
def test_deskpro_error_handling(admin_user):
    ticket = DeskProTicket.objects.create(
        subject="test",
        body="",
        user=admin_user,
    )

    out = io.StringIO()

    call_command("pdb_deskpro_publish", stdout=out)

    captured = out.getvalue()

    ticket.refresh_from_db()

    assert "[mock-error]" in ticket.subject
    assert "mock-error" in ticket.body
    assert "[FAILED]" in ticket.subject

    assert (
        "This email was sent because publishing to the deskpro API resulted in an error"
        in captured
    )

    call_command("pdb_deskpro_requeue", ticket.id, commit=True)

    ticket.refresh_from_db()

    assert ticket.subject == "test"
    assert "mock-error" not in ticket.body
