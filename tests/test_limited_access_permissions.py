"""
Tests for limited access organization permissions.
"""

import pytest
from django_grainy.models import GroupPermission
from grainy.const import PERM_CRUD, PERM_READ

from peeringdb_server.models import Organization, User
from tests.util import reset_group_ids


@pytest.fixture
def limited_access_org():
    """
    Create a limited access organization with manually configured permissions.

    Limited access orgs have restricted permissions:
    - User group: READ on org namespace only
    - Admin group: READ on org namespace, CRUD on oauth namespace only
    """
    reset_group_ids()
    org = Organization.objects.create(name="Limited Access Org", status="ok")

    # Remove default permissions that shouldn't exist for limited access orgs
    user_group = org.usergroup
    admin_group = org.admin_usergroup

    # Clear all user group permissions and set only READ on org namespace
    GroupPermission.objects.filter(group=user_group).delete()
    GroupPermission.objects.create(
        group=user_group, namespace=org.grainy_namespace, permission=PERM_READ
    )

    # Clear all admin group permissions and set limited access permissions
    GroupPermission.objects.filter(group=admin_group).delete()

    # READ on org namespace
    GroupPermission.objects.create(
        group=admin_group, namespace=org.grainy_namespace, permission=PERM_READ
    )

    # CRUD on oauth namespace (note: manage namespace is NOT included)
    GroupPermission.objects.create(
        group=admin_group, namespace=org.grainy_namespace_oauth, permission=PERM_CRUD
    )

    return org


@pytest.fixture
def regular_org():
    """Create a regular organization with default full permissions."""
    reset_group_ids()
    org = Organization.objects.create(name="Regular Org", status="ok")
    return org


@pytest.mark.django_db
def test_limited_access_org_has_limited_permissions(limited_access_org):
    """Test that limited access orgs have manually configured limited permissions."""
    org = limited_access_org

    user_group = org.usergroup
    user_perms = GroupPermission.objects.filter(group=user_group)

    # Limited access orgs should only have READ permission on the org namespace
    assert user_perms.count() == 1
    basic_perm = user_perms.get(namespace=org.grainy_namespace)
    assert basic_perm.permission == PERM_READ

    # No POC or IXF permissions for user group
    assert not GroupPermission.objects.filter(
        group=user_group, namespace__contains=".network.*.poc_set.private"
    ).exists()
    assert not GroupPermission.objects.filter(
        group=user_group,
        namespace__contains=".internetexchange.*.ixf_ixp_member_list_url.private",
    ).exists()

    admin_group = org.admin_usergroup
    admin_perms = GroupPermission.objects.filter(group=admin_group)

    # Limited access admin should have READ on org, CRUD on oauth
    # (manage namespace is NOT included)
    assert admin_perms.count() == 2

    org_perm = admin_perms.get(namespace=org.grainy_namespace)
    assert org_perm.permission == PERM_READ

    oauth_perm = admin_perms.get(namespace=org.grainy_namespace_oauth)
    assert oauth_perm.permission == PERM_CRUD

    # Verify manage namespace does NOT exist
    assert not GroupPermission.objects.filter(
        group=admin_group, namespace=org.grainy_namespace_manage
    ).exists()

    # No POC or IXF permissions for admin group
    assert not GroupPermission.objects.filter(
        group=admin_group, namespace__contains=".network.*.poc_set.private"
    ).exists()
    assert not GroupPermission.objects.filter(
        group=admin_group,
        namespace__contains=".internetexchange.*.ixf_ixp_member_list_url.private",
    ).exists()


@pytest.mark.django_db
def test_regular_org_has_full_permissions(regular_org):
    """Test that regular orgs get full permissions during creation."""
    org = regular_org

    user_group = org.usergroup
    user_perms = GroupPermission.objects.filter(group=user_group)

    # Regular orgs get READ on org namespace plus POC and IXF permissions
    assert user_perms.count() == 3

    basic_perm = user_perms.get(namespace=org.grainy_namespace)
    assert basic_perm.permission == PERM_READ

    assert GroupPermission.objects.filter(
        group=user_group, namespace=f"{org.grainy_namespace}.network.*.poc_set.private"
    ).exists()
    assert GroupPermission.objects.filter(
        group=user_group,
        namespace=f"{org.grainy_namespace}.internetexchange.*.ixf_ixp_member_list_url.private",
    ).exists()

    admin_group = org.admin_usergroup
    admin_perms = GroupPermission.objects.filter(group=admin_group)

    # Regular org admin gets CRUD on org, manage, POC, and IXF namespaces
    assert admin_perms.count() == 4

    org_perm = admin_perms.get(namespace=org.grainy_namespace)
    assert org_perm.permission == PERM_CRUD

    assert GroupPermission.objects.filter(
        group=admin_group, namespace=org.grainy_namespace_manage
    ).exists()


@pytest.mark.django_db
def test_converting_org_to_limited_access():
    """Test that existing org permissions can be manually converted to limited access."""
    reset_group_ids()
    org = Organization.objects.create(name="Regular Org", status="ok")

    admin_group = org.admin_usergroup
    user_group = org.usergroup

    # Verify initial full permissions
    initial_admin_perms = GroupPermission.objects.filter(group=admin_group).count()
    assert initial_admin_perms == 4

    # Manually convert to limited access by updating permissions
    # Clear all user group permissions and set only READ on org namespace
    GroupPermission.objects.filter(group=user_group).delete()
    GroupPermission.objects.create(
        group=user_group, namespace=org.grainy_namespace, permission=PERM_READ
    )

    # Clear all admin group permissions and set limited access permissions
    GroupPermission.objects.filter(group=admin_group).delete()

    # READ on org namespace
    GroupPermission.objects.create(
        group=admin_group, namespace=org.grainy_namespace, permission=PERM_READ
    )

    # CRUD on oauth namespace (manage namespace NOT included)
    GroupPermission.objects.create(
        group=admin_group, namespace=org.grainy_namespace_oauth, permission=PERM_CRUD
    )

    # Verify limited access permissions
    remaining_admin_perms = GroupPermission.objects.filter(group=admin_group)
    assert remaining_admin_perms.count() == 2

    org_perm = remaining_admin_perms.get(namespace=org.grainy_namespace)
    assert org_perm.permission == PERM_READ

    oauth_perm = remaining_admin_perms.get(namespace=org.grainy_namespace_oauth)
    assert oauth_perm.permission == PERM_CRUD

    # Verify manage namespace does NOT exist
    assert not GroupPermission.objects.filter(
        group=admin_group, namespace=org.grainy_namespace_manage
    ).exists()


@pytest.mark.django_db
def test_limited_access_user_and_admin_permissions():
    """Test permission differences between regular and admin users in limited access orgs."""
    reset_group_ids()

    # Create org with default permissions first
    org = Organization.objects.create(name="Limited Org", status="ok")

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

    # Add users
    regular_user = User.objects.create_user("regular", "regular", "regular@localhost")
    admin_user = User.objects.create_user("admin", "admin", "admin@localhost")

    org.usergroup.user_set.add(regular_user)
    org.admin_usergroup.user_set.add(admin_user)

    assert not regular_user.is_org_admin(org)
    assert admin_user.is_org_admin(org)

    user_group_perms = GroupPermission.objects.filter(group=org.usergroup)
    admin_group_perms = GroupPermission.objects.filter(group=org.admin_usergroup)

    assert user_group_perms.count() == 1
    assert user_group_perms.get().permission == PERM_READ

    assert admin_group_perms.count() == 2
    org_perm = admin_group_perms.get(namespace=org.grainy_namespace)
    oauth_perm = admin_group_perms.get(namespace=org.grainy_namespace_oauth)
    assert org_perm.permission == PERM_READ
    assert oauth_perm.permission == PERM_CRUD
