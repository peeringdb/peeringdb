import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from peeringdb_server.middleware import PermissionsPolicyMiddleware

pytestmark = pytest.mark.django_db


def assert_policy(response):
    directives = dict(
        directive.strip().split("=", 1)
        for directive in response["Permissions-Policy"].split(",")
    )
    for feature in (
        "camera",
        "microphone",
        "geolocation",
        "payment",
        "usb",
        "browsing-topics",
        "accelerometer",
        "gyroscope",
        "magnetometer",
        "midi",
        "display-capture",
        "hid",
        "serial",
    ):
        assert directives[feature] == "()"
    for feature in ("publickey-credentials-create", "publickey-credentials-get"):
        assert directives[feature] == "(self)"


@pytest.mark.parametrize("status", [200, 302, 403, 404, 500])
def test_policy_on_all_response_statuses(status):
    original = HttpResponse("unchanged", status=status)
    response = PermissionsPolicyMiddleware(lambda request: original)(
        RequestFactory().get("/")
    )
    assert response is original
    assert response.status_code == status
    assert response.content == b"unchanged"
    assert_policy(response)


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/", "/cp/", "/missing-page-for-policy-test"])
def test_policy_through_installed_middleware(client, path):
    assert_policy(client.get(path))
