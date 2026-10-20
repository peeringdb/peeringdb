import pytest
from django.urls import reverse
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken

from peeringdb_server.models import User

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("method", ["get", "post"])
def test_anonymous_disable_redirects_to_login(client, method):
    response = getattr(client, method)(reverse("two_factor:disable"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("two_factor:login") + "?next=")
    assert "no-store" in response["Cache-Control"]


def test_authenticated_disable_keeps_factor_verification(client):
    user = User.objects.create_user(
        "disable-security", password="disable-security-password"
    )
    device = StaticDevice.objects.create(user=user, name="backup", confirmed=True)
    StaticToken.objects.create(device=device, token="testcode478")
    client.force_login(user)
    url = reverse("two_factor:disable")
    response = client.get(url)
    assert response.status_code == 200
    response = client.post(url, {"understand": "on"})
    assert response.status_code == 200
    assert StaticDevice.objects.filter(pk=device.pk).exists()
    response = client.post(url, {"understand": "on", "otp_token": "testcode478"})
    assert response.status_code == 302
    assert not StaticDevice.objects.filter(pk=device.pk).exists()
