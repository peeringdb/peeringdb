from datetime import timedelta

import pytest
from django.contrib.auth import SESSION_KEY
from django.test import Client
from django.utils import timezone

from peeringdb_server.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(settings):
    # keep the user outside MFA enforcement so the pages under test render
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=1)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=2)
    return User.objects.create_user("logout-user", password="logout-password")


def test_logout_get_is_refused(user):
    client = Client()
    client.force_login(user)
    response = client.get("/logout")
    assert response.status_code == 405
    assert client.session[SESSION_KEY] == str(user.pk)


def test_logout_post_requires_csrf_token(user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.post("/logout")
    assert response.status_code == 403
    assert client.session[SESSION_KEY] == str(user.pk)


def test_logout_post_from_header_form(user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    page = client.get("/")
    assert page.status_code == 200
    assert b'<form method="post" action="/logout">' in page.content
    response = client.post(
        "/logout", {"csrfmiddlewaretoken": str(page.context["csrf_token"])}
    )
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert SESSION_KEY not in client.session
