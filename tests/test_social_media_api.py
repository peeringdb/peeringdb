"""
A profile URL pasted into a social media identifier is stored as the bare
identifier the service's URL format expects (#2066).
"""

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from peeringdb_server.models import Organization, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(settings):
    Group.objects.get_or_create(id=settings.GUEST_GROUP_ID, defaults={"name": "guest"})
    Group.objects.get_or_create(id=settings.USER_GROUP_ID, defaults={"name": "user"})
    user = User.objects.create_user(
        username="social-media-owner", email="social-media@example.com"
    )
    user.set_verified()
    org = Organization.objects.create(name="Social Media Owner", status="ok")
    org.admin_usergroup.user_set.add(user)
    client = APIClient()
    client.force_login(user)
    return client, org


def put_social_media(client, org, social_media):
    data = client.get(f"/api/org/{org.pk}").json()["data"][0]
    data["social_media"] = social_media
    return client.put(f"/api/org/{org.pk}", data, format="json")


def test_pasted_url_is_stored_as_identifier(owner):
    client, org = owner
    response = put_social_media(
        client,
        org,
        [
            {
                "service": "linkedin",
                "identifier": "https://www.linkedin.com/company/tbax/",
            }
        ],
    )
    assert response.status_code == 200, response.content

    org.refresh_from_db()
    assert org.social_media == [{"service": "linkedin", "identifier": "tbax"}]


def test_url_of_another_page_is_rejected(owner):
    client, org = owner
    response = put_social_media(
        client,
        org,
        [{"service": "linkedin", "identifier": "https://www.linkedin.com/in/jane"}],
    )
    assert response.status_code == 400, response.content


def test_encoded_markup_link_is_rejected_without_decoded_markup(owner):
    client, org = owner
    link = (
        "https://www.linkedin.com/company/"
        "%3Cimg%20src%3Dx%20onerror%3D%22window.__pdbtest%3D1%22%3E"
    )
    before = org.social_media
    response = put_social_media(
        client, org, [{"service": "linkedin", "identifier": link}]
    )
    assert response.status_code == 400, response.content
    assert b"%3Cimg" in response.content
    assert b"<img" not in response.content

    org.refresh_from_db()
    assert org.social_media == before
