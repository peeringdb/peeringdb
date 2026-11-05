import time
from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import SESSION_KEY
from django.core.cache import caches
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from peeringdb_server.models import User
from peeringdb_server.util import get_client_ident

pytestmark = pytest.mark.django_db
PASSWORD = "throttle-test-password"
LIMITED = b"Please wait a bit before trying to login again."


LIMIT = 4


@pytest.fixture(autouse=True)
def throttle(settings, monkeypatch):
    # the views module holds the same dict
    monkeypatch.setitem(settings.RATELIMITS, "request_login_POST", f"{LIMIT}/m")
    monkeypatch.setitem(
        settings.RATELIMITS, "request_login_username_POST", f"{LIMIT}/m"
    )
    # keep the users outside MFA enforcement so a right password logs in
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=1)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=2)
    cache = caches[getattr(settings, "RATELIMIT_USE_CACHE", "default")]
    cache.clear()
    # one fixed window, so a minute boundary during the test can't reset it
    with mock.patch(
        "django_ratelimit.core._get_window",
        return_value=int(time.time()) + 3600,
    ):
        yield
    cache.clear()


@pytest.fixture
def user():
    return User.objects.create_user("throttled", password=PASSWORD)


def password_post(client, username, password, xff="203.0.113.1"):
    return client.post(
        reverse("two_factor:login"),
        {
            "login_view-current_step": "auth",
            "auth-username": username,
            "auth-password": password,
        },
        HTTP_X_FORWARDED_FOR=xff,
    )


def test_password_attempts_limited_per_username(user):
    # every attempt from another address: only the username limit applies
    for i in range(LIMIT):
        response = password_post(Client(), user.username, "wrong", f"203.0.113.{i}")
        assert LIMITED not in response.content

    client = Client()
    response = password_post(client, user.username.upper(), PASSWORD, "198.51.100.1")
    assert response.status_code == 200
    assert LIMITED in response.content
    assert SESSION_KEY not in client.session


def test_password_attempts_limited_per_address(user):
    for i in range(LIMIT):
        response = password_post(Client(), f"nobody-{i}", "wrong")
        assert LIMITED not in response.content

    client = Client()
    response = password_post(client, user.username, PASSWORD)
    assert LIMITED in response.content
    assert SESSION_KEY not in client.session

    # a different address is not affected
    client = Client()
    response = password_post(client, user.username, PASSWORD, "198.51.100.1")
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)


def test_client_supplied_forwarded_entries_do_not_change_the_key(user):
    for i in range(LIMIT):
        password_post(Client(), f"nobody-{i}", "wrong", f"10.0.0.{i}, 203.0.113.1")

    response = password_post(Client(), user.username, PASSWORD, "10.9.9.9, 203.0.113.1")
    assert LIMITED in response.content


def test_username_spellings_share_one_budget(user):
    # fullwidth and upper case forms resolve to the same account
    spellings = ["ｔｈｒｏｔｔｌｅｄ", "THROTTLED", "Throttled", " throttled "]
    for i in range(LIMIT):
        password_post(
            Client(), spellings[i % len(spellings)], "wrong", f"203.0.113.{i}"
        )

    response = password_post(Client(), user.username, PASSWORD, "198.51.100.1")
    assert LIMITED in response.content


def test_ipv6_addresses_counted_by_64(user):
    for i in range(LIMIT):
        password_post(Client(), f"nobody-{i}", "wrong", f"2001:db8:1:2::{i + 1}")

    response = password_post(Client(), user.username, PASSWORD, "2001:db8:1:2:ffff::9")
    assert LIMITED in response.content

    client = Client()
    response = password_post(client, user.username, PASSWORD, "2001:db8:1:3::1")
    assert response.status_code == 302


def test_limited_address_does_not_use_up_account_budget(user):
    for i in range(LIMIT):
        password_post(Client(), f"nobody-{i}", "wrong", "203.0.113.66")

    # the address is limited now, naming the account no longer counts for it
    for _ in range(LIMIT * 3):
        response = password_post(Client(), user.username, "wrong", "203.0.113.66")
        assert LIMITED in response.content

    client = Client()
    response = password_post(client, user.username, PASSWORD, "198.51.100.1")
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)


def test_posts_without_username_are_not_counted(user):
    client = Client()
    for _ in range(LIMIT + 1):
        client.post(reverse("two_factor:login"), {"login_view-current_step": "auth"})

    response = password_post(client, user.username, PASSWORD)
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)


@pytest.mark.parametrize(
    "num_proxies,xff,expected",
    (
        (1, "", "192.0.2.1"),
        (1, "203.0.113.5", "203.0.113.5"),
        (1, "10.0.0.1, 203.0.113.5", "203.0.113.5"),
        (2, "10.0.0.1, 203.0.113.5, 198.51.100.7", "203.0.113.5"),
        (2, "198.51.100.7", "192.0.2.1"),
        (0, "10.0.0.1, 203.0.113.5", "192.0.2.1"),
        (1, "10.0.0.1, 203.0.113.5:4321", "203.0.113.5"),
        (1, "[2001:db8::5]:443", "2001:db8::5"),
        (1, "::ffff:203.0.113.5", "203.0.113.5"),
        (1, "[::ffff:203.0.113.5]:443", "203.0.113.5"),
    ),
)
def test_get_client_ident(rf, settings, num_proxies, xff, expected):
    settings.NUM_PROXIES = num_proxies
    request = rf.get("/", REMOTE_ADDR="192.0.2.1", HTTP_X_FORWARDED_FOR=xff)
    assert get_client_ident(request) == expected


def test_get_client_ident_normalizes_remote_addr(rf, settings):
    settings.NUM_PROXIES = 0
    request = rf.get("/", REMOTE_ADDR="::ffff:192.0.2.1")
    assert get_client_ident(request) == "192.0.2.1"


def test_ipv4_mapped_addresses_counted_per_address(user):
    for i in range(LIMIT):
        password_post(Client(), f"nobody-{i}", "wrong", "::ffff:203.0.113.1")

    response = password_post(Client(), user.username, PASSWORD, "203.0.113.1:5555")
    assert LIMITED in response.content

    # another mapped address is another client, not the same ::/64
    client = Client()
    response = password_post(client, user.username, PASSWORD, "::ffff:203.0.113.2")
    assert response.status_code == 302
