import io

import pytest
from django.core.management import call_command
from django_grainy.util import Permissions
from grainy.const import PERM_CREATE, PERM_CRUD, PERM_READ, PERM_UPDATE

from peeringdb_server.management.commands.pdb_fix_org_admin_perms import (
    ORG_NAMESPACE_RE,
)
from peeringdb_server.models import Organization, User


def run_command(commit=False, list_unaffiliated=False):
    out = io.StringIO()
    kwargs = {"stdout": out}
    if commit:
        kwargs["commit"] = True
    if list_unaffiliated:
        kwargs["list_unaffiliated"] = True
    call_command("pdb_fix_org_admin_perms", **kwargs)
    return out.getvalue()


def make_org_admin(name, permission=PERM_CRUD):
    """
    An org admin holding their own grainy rows for the org they administer --
    the state the uncleaned role transitions left behind.
    """

    org = Organization.objects.create(name=name, status="ok")
    user = User.objects.create_user(name, f"{name}@localhost", name)
    org.admin_usergroup.user_set.add(user)

    user.grainy_permissions.create(
        namespace=org.grainy_namespace, permission=permission
    )
    user.grainy_permissions.create(
        namespace=f"{org.grainy_namespace}.network", permission=permission
    )

    return org, user


def org_permission_count(user, org):
    return user.grainy_permissions.filter(
        namespace__startswith=org.grainy_namespace
    ).count()


@pytest.mark.django_db
def test_org_namespace_re():
    """
    Test the org id parse, the only boundary this command draws by itself.
    """

    assert ORG_NAMESPACE_RE.match("peeringdb.organization.5").group(1) == "5"
    assert ORG_NAMESPACE_RE.match("peeringdb.organization.5.network").group(1) == "5"
    assert ORG_NAMESPACE_RE.match("peeringdb.organization.50").group(1) == "50"
    assert ORG_NAMESPACE_RE.match("peeringdb.organization.5x") is None
    assert ORG_NAMESPACE_RE.match("peeringdb.organization.") is None
    assert ORG_NAMESPACE_RE.match("peeringdb.manage_organization.5") is None


@pytest.mark.django_db
def test_report_only_by_default():
    org, user = make_org_admin("admin-report")

    output = run_command()

    assert "[pretend]" in output
    assert f"org {org.id}" in output
    assert org_permission_count(user, org) == 2


@pytest.mark.django_db
def test_commit_removes_shadowing_permissions():
    org, user = make_org_admin("admin-commit", permission=PERM_CREATE | PERM_READ)

    # the user's own row decides while it exists, and it grants no update

    assert not Permissions(user).check(org.grainy_namespace, PERM_UPDATE)

    output = run_command(commit=True)

    assert "[pretend]" not in output
    assert org_permission_count(user, org) == 0

    # with the row gone the admin group's CRUD grant applies again

    assert Permissions(User.objects.get(id=user.id)).check(
        org.grainy_namespace, PERM_CRUD
    )


@pytest.mark.django_db
def test_member_permissions_are_left_alone():
    """
    Members are meant to hold granular permissions, so nothing about them is a
    leftover.
    """

    org = Organization.objects.create(name="member-org", status="ok")
    user = User.objects.create_user("member", "member@localhost", "member")
    org.usergroup.user_set.add(user)
    user.grainy_permissions.create(
        namespace=f"{org.grainy_namespace}.network", permission=PERM_CRUD
    )

    output = run_command(commit=True)

    assert f"org {org.id}" not in output
    assert org_permission_count(user, org) == 1


@pytest.mark.django_db
def test_unaffiliated_listed_but_never_deleted():
    """
    Invisible in the org UI, so the count is unknown until this runs. Reported,
    never deleted.
    """

    org = Organization.objects.create(name="unaffiliated-org", status="ok")
    user = User.objects.create_user("outsider", "outsider@localhost", "outsider")
    user.grainy_permissions.create(namespace=org.grainy_namespace, permission=PERM_CRUD)

    output = run_command(commit=True)
    assert "[unaffiliated]" not in output
    assert org_permission_count(user, org) == 1

    output = run_command(commit=True, list_unaffiliated=True)
    assert f"[unaffiliated] {user}" in output
    assert f"org {org.id}" in output
    assert org_permission_count(user, org) == 1
