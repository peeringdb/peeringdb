import json

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client

from mainsite.settings import hosts_from_settings
from peeringdb_server.models import Organization, User

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "urls,cookie_domain,expected",
    [
        (
            ["https://www.peeringdb.com"],
            ".peeringdb.com",
            ["www.peeringdb.com", "peeringdb.com"],
        ),
        (["https://dev.example.net:8040/"], "dev.example.net", ["dev.example.net"]),
        (
            ["https://Example.com", "https://auth.example.com", "https://example.com"],
            None,
            ["example.com", "auth.example.com"],
        ),
        (["http://[2001:db8::1]:8000"], "", ["[2001:db8::1]"]),
        (["not a url"], "localhost", ["localhost"]),
        (["https://peeringdb.com"], ".PeeringDB.com", ["peeringdb.com"]),
        ([], ".", []),
    ],
)
def test_hosts_from_settings(urls, cookie_domain, expected):
    assert hosts_from_settings(urls, cookie_domain) == expected


def test_allowed_hosts_is_not_a_wildcard():
    assert "*" not in settings.ALLOWED_HOSTS


def test_foreign_host_is_refused(mailoutbox):
    response = Client().get("/", HTTP_HOST="evil.example")
    assert response.status_code == 400
    # refused hosts must not use up the throttled error email budget
    assert not mailoutbox


def test_password_reset_with_foreign_host_sends_nothing(mailoutbox):
    client = Client()
    response = client.post(
        "/reset-password", {"email": "user@example.net"}, HTTP_HOST="evil.example"
    )
    assert response.status_code == 400
    assert not mailoutbox


@pytest.mark.parametrize("host", ["10.0.0.12:8000", "evil.example"])
def test_healthcheck_accepts_any_host(host):
    response = Client().get("/healthcheck", HTTP_HOST=host)
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/healthcheck/", "/healthcheckx", "/"])
def test_healthcheck_exemption_is_exact_path(path):
    response = Client().get(path, HTTP_HOST="10.0.0.12:8000")
    assert response.status_code == 400


def test_api_cache_builds_logo_urls_on_the_site_host(settings, tmp_path):
    # pytest allows "testserver"; production does not
    settings.ALLOWED_HOSTS = ["localhost"]
    User.objects.create(username="api-cache-admin", is_superuser=True)
    org = Organization.objects.create(name="Logo org", status="ok")
    org.logo = "logos/logo-org.png"
    org.save()
    settings.API_CACHE_LOG = str(tmp_path / "api-cache.log")
    call_command("pdb_api_cache", only="org", depths="0", output_dir=str(tmp_path))

    with open(tmp_path / "org-0.json") as fh:
        rows = json.load(fh)["data"]
    (row,) = [row for row in rows if row["id"] == org.id]
    assert row["logo"] == "https://localhost/m/logos/logo-org.png"
