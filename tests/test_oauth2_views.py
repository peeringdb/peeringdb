import pytest
from django.conf import settings
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from oauth2_provider.settings import oauth2_settings

from peeringdb_server.models import OAuthApplication, Organization, User
from peeringdb_server.views import (
    ApplicationDelete,
    ApplicationDetail,
    ApplicationList,
    ApplicationRegistration,
    ApplicationUpdate,
)


def override_app_model():
    oauth2_settings.APPLICATION_MODEL = "peeringdb_server.OAuthApplication"


def restore_app_model():
    oauth2_settings.APPLICATION_MODEL = "oauth2_provider.Application"


@pytest.fixture
def oauth2_org_admin_user():
    user = User.objects.create_user("test", "test", "test@localhost")
    org = Organization.objects.create(name="Test Org 001", status="ok")
    org.admin_usergroup.user_set.add(user)

    org_other = Organization.objects.create(name="Unprovisioned org", status="ok")

    return user, org, org_other


@pytest.fixture
def oauth2_apps(oauth2_org_admin_user):
    user, org, org_other = oauth2_org_admin_user

    user_app = OAuthApplication.objects.create(
        user=user,
        name="User app",
        client_id="client_id_user",
        client_secret="client_secret_user",
    )

    org_app = OAuthApplication.objects.create(
        org=org,
        name="Org app",
        client_id="client_id_org",
        client_secret="client_secret_org",
    )

    other_app = OAuthApplication.objects.create(
        org=org_other,
        name="Unprovisioned app",
        client_id="client_id_other",
        client_secret="client_secret_other",
    )

    return user_app, org_app, other_app


@pytest.mark.django_db
def test_app_list(oauth2_apps):
    override_app_model()

    user_app, org_app, other_app = oauth2_apps
    user = user_app.user

    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:list")

    resp = client.get(url)

    content = resp.content.decode("utf-8")

    assert resp.status_code == 200
    assert org_app.name in content
    assert user_app.name in content
    assert other_app.name not in content
    assert org_app.org.name in content

    # test that oauth app is listed in org admin view as well

    resp = client.get(f"/org/{org_app.org.id}/")
    content = resp.content.decode("utf-8")

    assert org_app.name in content
    assert other_app.name not in content
    assert user_app.name not in content

    restore_app_model()


@pytest.mark.django_db
def test_app_detail(oauth2_apps):
    override_app_model()

    def check_cache_headers(resp):
        assert resp.has_header("Cache-Control")
        cache_control_header = resp.headers.get("Cache-Control")
        assert "max-age=0" in cache_control_header
        assert "no-cache" in cache_control_header
        assert "no-store" in cache_control_header
        assert "must-revalidate" in cache_control_header
        assert "private" in cache_control_header

    user_app, org_app, other_app = oauth2_apps
    user = user_app.user

    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:list")

    # detail user owned app

    url = reverse("oauth2_provider:detail", args=(user_app.id,))
    resp = client.get(url)

    assert resp.status_code == 200
    check_cache_headers(resp)

    # detail org owned app

    url = reverse("oauth2_provider:detail", args=(org_app.id,))
    resp = client.get(url)

    assert resp.status_code == 200
    assert f"{org_app.org.name}'s management" in resp.content.decode("utf-8")
    check_cache_headers(resp)

    # detail unprovisioned org owned app (prohibited)

    url = reverse("oauth2_provider:detail", args=(other_app.id,))
    resp = client.get(url)

    assert resp.status_code == 404

    restore_app_model()


@pytest.mark.django_db
def test_app_delete(oauth2_apps):
    override_app_model()

    user_app, org_app, other_app = oauth2_apps
    user = user_app.user

    client = Client()
    client.force_login(user)

    # delete user owned app

    url = reverse("oauth2_provider:delete", args=(user_app.id,))
    resp = client.post(url)

    assert resp.status_code == 302
    assert not OAuthApplication.objects.filter(id=user_app.id).exists()

    # delete org owned app

    url = reverse("oauth2_provider:delete", args=(org_app.id,))
    resp = client.post(url)

    assert resp.status_code == 302
    assert not OAuthApplication.objects.filter(id=org_app.id).exists()

    # delete unprovisioned org owned app (prohibited)

    url = reverse("oauth2_provider:delete", args=(other_app.id,))
    resp = client.post(url)

    assert resp.status_code == 404
    assert OAuthApplication.objects.filter(id=other_app.id).exists()

    restore_app_model()


@pytest.mark.django_db
def test_app_registration_and_update(oauth2_org_admin_user):
    override_app_model()

    user, org, org_other = oauth2_org_admin_user

    client = Client()
    client.force_login(user)
    url = reverse("oauth2_provider:register")

    # TEST CREATE

    resp = client.get(url, follow=True)

    assert resp.status_code == 200

    content = resp.content.decode("utf-8")

    assert f'<option value="{org.id}">{org.name}</option>' in content
    assert f'<option value="{org_other.id}">{org_other.name}</option>' not in content

    # test submitting user owned oauth app

    form_data = {
        "name": "User app",
        "client_id": "client_id",
        "client_secret": "client_secret",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(user=user, name="User app").exists()

    # test submitting org owner oauth app

    form_data = {
        "org": org.id,
        "name": "Org app",
        "client_id": "client_idB",
        "client_secret": "client_secretB",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(
        user__isnull=True, org=org, name="Org app"
    ).exists()

    # test permissions

    form_data = {
        "org": org_other.id,
        "name": "Org other app",
        "client_id": "client_idC",
        "client_secret": "client_secretC",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 200
    assert "That choice is not one of the available choices" in resp.content.decode(
        "utf-8"
    )
    assert not OAuthApplication.objects.filter(org=org_other).exists()

    # TEST UPDATE

    app = org.oauth_applications.first()

    url = reverse("oauth2_provider:update", args=(app.id,))

    resp = client.get(url, follow=True)

    assert resp.status_code == 200

    content = resp.content.decode("utf-8")

    assert f'<option value="{org.id}" selected>{org.name}</option>' in content
    assert f'<option value="{org_other.id}">{org_other.name}</option>' not in content

    form_data = {
        "org": org.id,
        "name": "Updated name",
        "client_id": "client_idB",
        "client_secret": "client_secretB",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(
        user__isnull=True, org=org, name="Updated name"
    ).exists()

    # test permissions

    form_data = {
        "org": org_other.id,
        "name": "Updated name",
        "client_id": "client_idB",
        "client_secret": "client_secretB",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    assert resp.status_code == 200
    assert "That choice is not one of the available choices" in resp.content.decode(
        "utf-8"
    )
    assert not OAuthApplication.objects.filter(org=org_other).exists()

    # test promote

    user_app = OAuthApplication.objects.filter(user=user, name="User app").first()
    url = reverse("oauth2_provider:update", args=(user_app.id,))

    form_data = {
        "org": org.id,
        "name": "Promoted app",
        "client_id": "client_id",
        "client_secret": "client_secret",
        "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
        "redirect_uris": "https://example.com",
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "",
    }

    resp = client.post(url, form_data)

    print(resp.content.decode("utf-8"))

    assert resp.status_code == 302
    assert OAuthApplication.objects.filter(
        user__isnull=True, org=org, id=user_app.id
    ).exists()

    restore_app_model()
