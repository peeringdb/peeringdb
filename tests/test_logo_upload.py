import io
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from peeringdb_server.models import Facility, Organization, User

pytestmark = pytest.mark.django_db


def png_upload(name="logo.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def org_admin(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    Group.objects.get_or_create(id=settings.GUEST_GROUP_ID, defaults={"name": "guest"})
    Group.objects.get_or_create(id=settings.USER_GROUP_ID, defaults={"name": "user"})
    user = User.objects.create_user(username="logo-admin", email="logo@example.com")
    user.set_verified()
    org = Organization.objects.create(name="Logo Org", status="ok", floor="3")
    org.admin_usergroup.user_set.add(user)
    client = Client()
    client.force_login(user)
    return client, org


@pytest.fixture
def facility(org_admin):
    return Facility.objects.create(
        org=org_admin[1],
        name="Logo Facility",
        status="ok",
        floor="2",
        city="Chicago",
        country="US",
        state="IL",
        zipcode="60601",
    )


@pytest.mark.parametrize("ref_tag", ["org", "fac"])
def test_logo_upload_ignores_legacy_floor(org_admin, facility, ref_tag):
    # floor's deprecation check in Model.clean() used to 500 the upload (#485)
    client, org = org_admin
    instance = org if ref_tag == "org" else facility
    response = client.post(
        f"/{ref_tag}/{instance.id}/upload-logo", {"logo": png_upload()}
    )
    assert response.status_code == 200, response.content
    instance.refresh_from_db()
    assert instance.logo
    assert instance.floor


def test_logo_upload_keeps_non_field_errors(org_admin):
    client, org = org_admin
    with patch.object(
        Organization, "clean", side_effect=ValidationError("Parent not ok")
    ):
        response = client.post(f"/org/{org.id}/upload-logo", {"logo": png_upload()})
    assert response.status_code == 400
    assert response.json()["__all__"] == ["Parent not ok"]


def test_logo_upload_still_validates_logo(org_admin):
    client, org = org_admin
    response = client.post(
        f"/org/{org.id}/upload-logo", {"logo": png_upload("logo.gif")}
    )
    assert response.status_code == 400
    assert "logo" in response.json()
