from base64 import b64encode

import pytest
from django.core.cache import caches
from django_security_keys.models import SecurityKey
from rest_framework.test import APIClient

from peeringdb_server.models import Network, Organization, User

from .util import reset_group_ids


@pytest.mark.django_db
def test_mfa_basic_auth_block_writes():
    reset_group_ids()
    user = User.objects.create_user(
        username="user", password="password", email="user@localhost"
    )
    org = Organization.objects.create(name="Test", status="ok")
    net = Network.objects.create(name="Test", asn=63311, status="ok", org=org)
    net_2 = Network.objects.create(name="Test 2", asn=63312, status="ok", org=org)

    user.set_verified()
    org.admin_usergroup.user_set.add(user)

    client = APIClient()
    basic_auth = b64encode(b"user:password").decode("ascii")
    client.credentials(HTTP_AUTHORIZATION=f"Basic {basic_auth}")

    # test 1: no MFA added, POST, PUT, DELETE should return BadRequest as we
    # are supplying no data

    response = client.post("/api/net", data={})

    assert response.status_code == 400

    response = client.put("/api/net/1", data={})

    assert response.status_code == 400

    response = client.delete("/api/net/2", data={})

    assert response.status_code == 204

    # test 2: add MFA, POST PUT DELETE should return permission error

    SecurityKey.objects.create(
        name="test",
        type="security-key",
        user=user,
        credential_id="1234",
        credential_public_key="deadbeef",
    )

    response = client.post("/api/net", data={})

    assert response.status_code == 403
    assert (
        response.json()["meta"]["error"]
        == "Cannot perform write operations with a MFA enabled account when authenticating with Basic authentication."
    )

    response = client.put("/api/net/1", data={})

    assert response.status_code == 403
    assert (
        response.json()["meta"]["error"]
        == "Cannot perform write operations with a MFA enabled account when authenticating with Basic authentication."
    )

    response = client.delete("/api/net/1", data={})

    assert response.status_code == 403
    assert (
        response.json()["meta"]["error"]
        == "Cannot perform write operations with a MFA enabled account when authenticating with Basic authentication."
    )

    # clear negative cache

    caches["negative"].clear()

    # test 3: remove MFA

    SecurityKey.objects.all().delete()

    response = client.post("/api/net", data={})

    assert response.status_code == 400

    response = client.put("/api/net/1", data={})

    assert response.status_code == 400

    response = client.delete("/api/net/1", data={})

    assert response.status_code == 204
