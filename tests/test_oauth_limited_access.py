"""
Tests for OAuth functionality with limited access organizations.
"""

import pytest
from django_grainy.models import GroupPermission
from grainy.const import PERM_CRUD, PERM_READ
from oauth2_provider.models import Application

from peeringdb_server.models import OAuthApplication, Organization, User
from tests.util import reset_group_ids


@pytest.fixture
def limited_access_org_admin():
    """
    Create a limited access organization with an admin user.

    Limited access orgs have manually configured restricted permissions.
    """
    reset_group_ids()
    admin_user = User.objects.create_user("admin", "admin", "admin@localhost")
    org = Organization.objects.create(name="Limited Access Org", status="ok")

    # Manually configure as limited access org
    user_group = org.usergroup
    admin_group = org.admin_usergroup

    # Clear and set limited user permissions
    GroupPermission.objects.filter(group=user_group).delete()
    GroupPermission.objects.create(
        group=user_group, namespace=org.grainy_namespace, permission=PERM_READ
    )

    # Clear and set limited admin permissions
    GroupPermission.objects.filter(group=admin_group).delete()
    GroupPermission.objects.create(
        group=admin_group, namespace=org.grainy_namespace, permission=PERM_READ
    )
    GroupPermission.objects.create(
        group=admin_group, namespace=org.grainy_namespace_oauth, permission=PERM_CRUD
    )

    org.admin_usergroup.user_set.add(admin_user)
    return admin_user, org


@pytest.fixture
def limited_access_org_user():
    """
    Create a limited access organization with a regular user.

    Limited access orgs have manually configured restricted permissions.
    """
    reset_group_ids()
    user = User.objects.create_user("limited_user", "limited_user", "limited@localhost")
    org = Organization.objects.create(name="Limited Access Org", status="ok")

    # Manually configure as limited access org
    user_group = org.usergroup
    admin_group = org.admin_usergroup

    # Clear and set limited user permissions
    GroupPermission.objects.filter(group=user_group).delete()
    GroupPermission.objects.create(
        group=user_group, namespace=org.grainy_namespace, permission=PERM_READ
    )

    # Clear and set limited admin permissions
    GroupPermission.objects.filter(group=admin_group).delete()
    GroupPermission.objects.create(
        group=admin_group, namespace=org.grainy_namespace, permission=PERM_READ
    )
    GroupPermission.objects.create(
        group=admin_group, namespace=org.grainy_namespace_oauth, permission=PERM_CRUD
    )

    org.usergroup.user_set.add(user)
    return user, org


@pytest.mark.django_db
def test_limited_access_admin_can_create_oauth_app(limited_access_org_admin):
    """Test that admin users in limited access orgs can create OAuth applications."""
    admin_user, org = limited_access_org_admin

    oauth_app = OAuthApplication.objects.create(
        org=org,
        name="Limited Access OAuth App",
        client_id="limited_client_123",
        client_secret="limited_secret_456",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://example.com/oauth/callback",
    )

    assert oauth_app.org == org
    assert oauth_app.name == "Limited Access OAuth App"
    assert oauth_app.user is None
    assert admin_user.is_org_admin(org) == True

    # Verify org has limited permissions (only oauth CRUD)
    admin_group_perms = GroupPermission.objects.filter(group=org.admin_usergroup)
    oauth_perm = admin_group_perms.get(namespace=org.grainy_namespace_oauth)
    assert oauth_perm.permission == PERM_CRUD


@pytest.mark.django_db
def test_limited_access_vs_regular_org_oauth_capabilities():
    """Test OAuth capabilities between limited access orgs and regular orgs."""
    reset_group_ids()

    limited_admin = User.objects.create_user(
        "limited_admin", "limited_admin", "limited@localhost"
    )
    limited_org = Organization.objects.create(name="Limited Org", status="ok")

    # Manually configure as limited access org
    user_group = limited_org.usergroup
    admin_group = limited_org.admin_usergroup

    GroupPermission.objects.filter(group=user_group).delete()
    GroupPermission.objects.create(
        group=user_group, namespace=limited_org.grainy_namespace, permission=PERM_READ
    )

    GroupPermission.objects.filter(group=admin_group).delete()
    GroupPermission.objects.create(
        group=admin_group, namespace=limited_org.grainy_namespace, permission=PERM_READ
    )
    GroupPermission.objects.create(
        group=admin_group,
        namespace=limited_org.grainy_namespace_oauth,
        permission=PERM_CRUD,
    )

    limited_org.admin_usergroup.user_set.add(limited_admin)

    regular_admin = User.objects.create_user(
        "regular_admin", "regular_admin", "regular@localhost"
    )
    regular_org = Organization.objects.create(name="Regular Org", status="ok")
    regular_org.admin_usergroup.user_set.add(regular_admin)

    limited_app = OAuthApplication.objects.create(
        org=limited_org,
        name="Limited OAuth App",
        client_id="limited_123",
        client_secret="limited_secret",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
    )

    regular_app = OAuthApplication.objects.create(
        org=regular_org,
        name="Regular OAuth App",
        client_id="regular_123",
        client_secret="regular_secret",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
    )

    assert OAuthApplication.objects.filter(id=limited_app.id).exists()
    assert OAuthApplication.objects.filter(id=regular_app.id).exists()

    # Verify permission differences
    limited_admin_perms = GroupPermission.objects.filter(
        group=limited_org.admin_usergroup
    )
    regular_admin_perms = GroupPermission.objects.filter(
        group=regular_org.admin_usergroup
    )

    # Limited org has only 2 permissions (READ org, CRUD oauth)
    assert limited_admin_perms.count() == 2
    # Regular org has 4 permissions (CRUD org, CRUD manage, CRUD POC, CRUD IXF)
    assert regular_admin_perms.count() == 4

    assert limited_admin.is_org_admin(limited_org) == True
    assert regular_admin.is_org_admin(regular_org) == True


@pytest.mark.django_db
def test_limited_access_org_oauth_namespace_permissions(limited_access_org_admin):
    """Test that OAuth namespace permissions work correctly for limited access orgs."""
    admin_user, org = limited_access_org_admin

    oauth_namespace = org.grainy_namespace_oauth
    assert oauth_namespace == f"peeringdb.manage_organization.{org.id}.oauth"

    assert admin_user.is_org_admin(org) == True

    oauth_app = OAuthApplication.objects.create(
        org=org,
        name="OAuth Test App",
        client_id="test_client_123",
        client_secret="test_secret_456",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
    )

    assert oauth_app.org == org


@pytest.mark.django_db
def test_multiple_oauth_apps_per_limited_access_org(limited_access_org_admin):
    """Test that limited access orgs can have multiple OAuth applications."""
    _, org = limited_access_org_admin

    app1 = OAuthApplication.objects.create(
        org=org,
        name="OAuth App 1",
        client_id="client_1",
        client_secret="secret_1",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
    )

    app2 = OAuthApplication.objects.create(
        org=org,
        name="OAuth App 2",
        client_id="client_2",
        client_secret="secret_2",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
    )

    assert app1.org == org
    assert app2.org == org
    assert OAuthApplication.objects.filter(org=org).count() == 2
