import re
from datetime import timedelta

import pytest
import reversion
from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_grainy.models import GroupPermission
from django_otp.plugins.otp_email.models import EmailDevice
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_security_keys.models import SecurityKey
from reversion.models import Version

from peeringdb_server.admin_commandline_tools import ToolReset, is_listed_tool
from peeringdb_server.models import (
    CommandLineTool,
    Facility,
    Organization,
    OrganizationAPIKey,
    OrganizationMerge,
    User,
    UserAPIKey,
    UserOrgAffiliationRequest,
    VerificationQueueItem,
)

pytestmark = pytest.mark.django_db
PASSWORD = "admin-actions-password"


@pytest.fixture(autouse=True)
def mfa_rollout_in_future(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=10)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=20)


@pytest.fixture
def superuser():
    return User.objects.create_user(
        "admin-actions-super",
        email="admin-actions-super@example.net",
        password=PASSWORD,
        status="ok",
        is_staff=True,
        is_superuser=True,
    )


def make_user(name, *grants, is_staff=True):
    """
    Account holding the given (namespace, grainy permission) grants
    """
    user = User.objects.create_user(
        f"admin-actions-{name}",
        email=f"admin-actions-{name}@example.net",
        password=PASSWORD,
        status="ok",
        is_staff=is_staff,
    )
    if grants:
        group = Group.objects.create(name=f"admin-actions-{name}")
        for namespace, permission in grants:
            GroupPermission.objects.create(
                group=group, namespace=namespace, permission=permission
            )
        group.user_set.add(user)
    return user


@pytest.fixture
def csrf_client():
    return Client(enforce_csrf_checks=True)


def csrf_token(response):
    return re.search(
        r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()
    ).group(1)


# URL actions


@pytest.fixture
def org():
    return Organization.objects.create(name="Admin actions org", status="ok")


@pytest.fixture
def vq_item(org):
    Facility.objects.create(name="Admin actions facility", org=org, status="pending")
    return VerificationQueueItem.objects.get(object_id=Facility.objects.get().id)


@pytest.fixture
def user_groups(settings):
    settings.GUEST_GROUP_ID = Group.objects.create(name="guest").id
    settings.USER_GROUP_ID = Group.objects.create(name="user").id


@pytest.fixture
def affiliation_request(org, user_groups):
    user = make_user("requester", is_staff=False)
    return UserOrgAffiliationRequest.objects.create(org=org, user=user)


@pytest.fixture
def org_merge(org):
    source = Organization.objects.create(name="Admin actions merged", status="deleted")
    return OrganizationMerge.objects.create(from_org=source, to_org=org)


def action_url(obj, action):
    return reverse(
        f"admin:{obj._meta.app_label}_{obj._meta.model_name}_actions",
        args=(obj.id, action),
    )


def action_state(name, obj):
    """
    Whether the action has taken effect on obj
    """
    if name in ("vq_approve", "vq_deny"):
        facility = Facility.objects.filter(name="Admin actions facility").first()
        if name == "vq_deny":
            return facility is None
        return facility.status == "ok"
    if name == "undo":
        return not OrganizationMerge.objects.filter(id=obj.id).exists()
    if name == "deny":
        obj.refresh_from_db()
        return obj.status == "denied"
    # an approved request is deleted once the user holds the role
    return obj.user.is_org_admin(obj.org)


ACTIONS = [
    ("vq_item", "vq_approve"),
    ("vq_item", "vq_deny"),
    ("affiliation_request", "approve"),
    ("affiliation_request", "approve_and_notify"),
    ("affiliation_request", "deny"),
    ("org_merge", "undo"),
]


@pytest.mark.parametrize("fixture,name", ACTIONS)
def test_url_action_get_shows_confirmation_only(
    csrf_client, request, superuser, fixture, name
):
    obj = request.getfixturevalue(fixture)
    csrf_client.force_login(superuser)

    response = csrf_client.get(action_url(obj, name))
    assert response.status_code == 200
    content = response.content.decode()
    assert '<form method="post"' in content
    assert 'name="csrfmiddlewaretoken"' in content
    assert not action_state(name, obj)


@pytest.mark.parametrize("fixture,name", ACTIONS)
def test_url_action_post_needs_csrf_token(
    csrf_client, request, superuser, fixture, name
):
    obj = request.getfixturevalue(fixture)
    csrf_client.force_login(superuser)
    url = action_url(obj, name)

    response = csrf_client.post(url)
    assert response.status_code == 403
    assert not action_state(name, obj)

    token = csrf_token(csrf_client.get(url))
    response = csrf_client.post(url, {"csrfmiddlewaretoken": token})
    assert response.status_code == 302
    assert action_state(name, obj)


@pytest.mark.parametrize("fixture,name", ACTIONS)
def test_url_action_refuses_non_superusers(client, request, fixture, name):
    obj = request.getfixturevalue(fixture)
    client.force_login(make_user("changer", ("peeringdb_server", 0x0F)))
    url = action_url(obj, name)
    assert client.get(url).status_code == 403
    assert client.post(url).status_code == 403
    assert not action_state(name, obj)


@pytest.mark.parametrize("method", ["get", "post"])
def test_url_action_only_runs_declared_actions(client, superuser, org_merge, method):
    client.force_login(superuser)
    response = getattr(client, method)(action_url(org_merge, "delete_queryset"))
    assert response.status_code == 302
    assert OrganizationMerge.objects.filter(id=org_merge.id).exists()


def test_vq_controls_post_from_change_form(client, superuser, vq_item):
    client.force_login(superuser)
    facility = vq_item.item
    response = client.get(
        reverse("admin:peeringdb_server_facility_change", args=(facility.id,))
    )
    assert response.status_code == 200
    content = response.content.decode()
    for name in ("vq_approve", "vq_deny"):
        assert f'data-post-action="{action_url(vq_item, name)}"' in content


def test_merge_log_undo_posts_from_change_form(client, superuser, org_merge):
    client.force_login(superuser)
    response = client.get(
        reverse("admin:peeringdb_server_organizationmerge_change", args=(org_merge.id,))
    )
    assert response.status_code == 200
    assert f'data-post-action="{action_url(org_merge, "undo")}"' in (
        response.content.decode()
    )


ORG_MERGE_URL = "/cp/peeringdb_server/organization/org-merge-tool/merge"


def test_org_merge_needs_post_and_csrf_token(csrf_client, superuser, org):
    source = Organization.objects.create(name="Admin actions source", status="ok")
    data = {"ids": str(source.id), "id": str(org.id)}
    csrf_client.force_login(superuser)

    response = csrf_client.get(ORG_MERGE_URL, data)
    assert response.status_code == 405

    response = csrf_client.post(ORG_MERGE_URL, data)
    assert response.status_code == 403

    source.refresh_from_db()
    assert source.status == "ok"

    tool = csrf_client.get("/cp/peeringdb_server/organization/org-merge-tool/")
    assert tool.status_code == 200
    response = csrf_client.post(
        ORG_MERGE_URL, data, headers={"X-CSRFToken": csrf_token(tool)}
    )
    assert response.status_code == 200
    source.refresh_from_db()
    assert source.status == "deleted"


# API keys

KEY_ADMINS = [
    ("userapikey", "user"),
    ("organizationapikey", "org"),
]


def key_add_data(owner_field, owner):
    data = {"name": "minted", "status": "active", owner_field: owner.id}
    if owner_field == "org":
        data["email"] = "admin-actions-key@example.net"
    return data


@pytest.mark.parametrize("model_name,owner_field", KEY_ADMINS)
def test_staff_cannot_mint_api_keys(client, superuser, org, model_name, owner_field):
    staff = make_user("minter", (f"peeringdb_server.{model_name}", 0x07))
    client.force_login(staff)
    url = f"/cp/peeringdb_server/{model_name}/add/"
    owner = superuser if owner_field == "user" else org

    assert client.get(url).status_code == 403
    response = client.post(url, key_add_data(owner_field, owner))
    assert response.status_code == 403
    assert not UserAPIKey.objects.exists()
    assert not OrganizationAPIKey.objects.exists()


@pytest.mark.parametrize("model_name,owner_field", KEY_ADMINS)
def test_superuser_can_mint_api_keys(client, superuser, org, model_name, owner_field):
    client.force_login(superuser)
    owner = superuser if owner_field == "user" else org
    response = client.post(
        f"/cp/peeringdb_server/{model_name}/add/",
        key_add_data(owner_field, owner),
        follow=True,
    )
    assert response.status_code == 200
    assert "The API key for minted is:" in response.content.decode()


def existing_key(owner_field, org):
    if owner_field == "user":
        key, _ = UserAPIKey.objects.create_key(
            name="existing", user=make_user("key-owner", is_staff=False)
        )
        new_owner = make_user("key-new-owner", is_staff=False)
    else:
        key, _ = OrganizationAPIKey.objects.create_key(
            name="existing", org=org, email="admin-actions-key@example.net"
        )
        new_owner = Organization.objects.create(name="Admin actions other", status="ok")
    return key, new_owner


@pytest.mark.parametrize("model_name,owner_field", KEY_ADMINS)
def test_api_key_owner_is_read_only_for_staff(client, org, model_name, owner_field):
    key, new_owner = existing_key(owner_field, org)
    client.force_login(
        make_user("key-changer", (f"peeringdb_server.{model_name}", 0x03))
    )
    url = f"/cp/peeringdb_server/{model_name}/{key.pk}/change/"
    response = client.get(url)
    assert response.status_code == 200
    assert f'name="{owner_field}"' not in response.content.decode()

    response = client.post(url, key_add_data(owner_field, new_owner))
    assert response.status_code == 302
    key.refresh_from_db()
    assert getattr(key, f"{owner_field}_id") != new_owner.id


@pytest.mark.parametrize("model_name,owner_field", KEY_ADMINS)
def test_superuser_can_move_api_key(client, superuser, org, model_name, owner_field):
    key, new_owner = existing_key(owner_field, org)
    client.force_login(superuser)
    url = f"/cp/peeringdb_server/{model_name}/{key.pk}/change/"
    assert f'name="{owner_field}"' in client.get(url).content.decode()

    response = client.post(url, key_add_data(owner_field, new_owner))
    assert response.status_code == 302
    key.refresh_from_db()
    assert getattr(key, f"{owner_field}_id") == new_owner.id


# Accounts


def change_form_data(response, **fields):
    """
    Management form data for every inline on an admin change form, plus fields
    """
    data = {}
    for inline in response.context["inline_admin_formsets"]:
        management = inline.formset.management_form
        for name in management.fields:
            data[management.add_prefix(name)] = management.initial.get(name, 0)
    data.update(fields)
    return data


def full_change_form_data(response, **fields):
    """
    The change form as the browser would post it back, plus fields
    """
    form = response.context["adminform"].form
    data = change_form_data(response)
    for name in form.fields:
        if name in fields:
            continue
        bound = form[name]
        widget = bound.field.widget.get_context(bound.html_name, bound.value(), {})
        for sub in widget["widget"].get("subwidgets", [widget["widget"]]):
            if sub["template_name"].endswith("checkbox.html"):
                if sub["attrs"].get("checked"):
                    data[sub["name"]] = "on"
            elif sub["value"] is not None:
                data[sub["name"]] = sub["value"]
    data.update(fields)
    return data


def userpermission_url(user):
    return reverse("admin:peeringdb_server_userpermission_change", args=(user.id,))


def test_userpermission_flags_read_only_for_staff(client):
    staff = make_user("roles", ("peeringdb_server.userpermission", 0x03))
    target = make_user("target", is_staff=False)
    client.force_login(staff)

    url = userpermission_url(target)
    response = client.get(url)
    assert response.status_code == 200
    content = response.content.decode()
    for flag in ("is_active", "is_staff", "is_superuser"):
        assert f'name="{flag}"' not in content

    response = client.post(
        url,
        change_form_data(response, is_staff="on", is_superuser="on", groups=[]),
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert not target.is_staff
    assert not target.is_superuser
    assert target.is_active


def test_staff_cannot_change_own_or_other_staff_permissions(client, superuser):
    staff = make_user("roles", ("peeringdb_server.userpermission", 0x03))
    client.force_login(staff)

    for target in (staff, superuser):
        url = userpermission_url(target)
        response = client.get(url)
        assert response.status_code == 200
        assert 'name="groups"' not in response.content.decode()
        response = client.post(url, {"is_superuser": "on", "groups": []})
        assert response.status_code == 403

    staff.refresh_from_db()
    assert not staff.is_superuser


def test_superuser_keeps_permission_flags(client, superuser):
    target = make_user("promoted", is_staff=False)
    client.force_login(superuser)
    url = userpermission_url(target)
    response = client.get(url)
    assert 'name="is_superuser"' in response.content.decode()

    response = client.post(
        url,
        change_form_data(
            response, is_active="on", is_staff="on", is_superuser="on", groups=[]
        ),
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.is_staff
    assert target.is_superuser


# the password view is registered by the User and the UserPermission admin


def password_url(model_name, user):
    return f"/cp/peeringdb_server/{model_name}/{user.id}/password/"


ACCOUNT_ADMINS = ["user", "userpermission"]
NEW_PASSWORD = {"password1": "Replaced-pass-951", "password2": "Replaced-pass-951"}


def account_staff():
    return make_user(
        "accounts",
        ("peeringdb_server.user", 0x0F),
        ("peeringdb_server.userpermission", 0x0F),
    )


@pytest.mark.parametrize("model_name", ACCOUNT_ADMINS)
def test_staff_cannot_replace_staff_or_superuser_password(
    client, superuser, model_name
):
    staff = account_staff()
    other_staff = make_user("other-staff")
    client.force_login(staff)

    for target in (superuser, other_staff, staff):
        response = client.post(password_url(model_name, target), NEW_PASSWORD)
        assert response.status_code == 403
        target.refresh_from_db()
        assert target.check_password(PASSWORD)


def test_staff_cannot_change_or_delete_staff_accounts(client, superuser):
    staff = account_staff()
    client.force_login(staff)

    url = reverse("admin:peeringdb_server_user_change", args=(superuser.id,))
    assert client.get(url).status_code == 200
    assert client.post(url, {"username": "renamed"}).status_code == 403

    url = reverse("admin:peeringdb_server_user_delete", args=(superuser.id,))
    assert client.post(url, {"post": "yes"}).status_code == 403

    response = client.post(
        reverse("admin:peeringdb_server_user_changelist"),
        {
            "action": "delete_selected",
            "_selected_action": [superuser.id],
            "post": "yes",
        },
    )
    assert User.objects.filter(id=superuser.id).exists()
    superuser.refresh_from_db()
    assert superuser.username == "admin-actions-super"


@pytest.mark.parametrize("model_name", ACCOUNT_ADMINS)
def test_staff_still_manages_regular_accounts(client, model_name):
    target = make_user("regular", is_staff=False)
    client.force_login(account_staff())
    response = client.post(password_url(model_name, target), NEW_PASSWORD)
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.check_password(NEW_PASSWORD["password1"])


@pytest.mark.parametrize("model_name", ACCOUNT_ADMINS)
def test_superuser_can_replace_superuser_password(client, superuser, model_name):
    other = make_user("other-super")
    other.is_superuser = True
    other.save()
    client.force_login(superuser)
    response = client.post(password_url(model_name, other), NEW_PASSWORD)
    assert response.status_code == 302
    other.refresh_from_db()
    assert other.check_password(NEW_PASSWORD["password1"])


# Command-line tools

TOOL_VIEWS = ("prepare", "preview", "run")
VALIDATE_DATA = {"tool": "pdb_validate_data", "model": "fac", "field": "name"}


def tool_url(view):
    return reverse(f"admin:peeringdb_server_commandlinetool_{view}")


@pytest.mark.parametrize("view", TOOL_VIEWS)
def test_commandline_tools_need_staff_login(client, view):
    user = make_user(
        "tool-runner", ("peeringdb_server.commandlinetool", 0x0F), is_staff=False
    )
    client.force_login(user)
    response = client.post(tool_url(view), VALIDATE_DATA)
    assert response.status_code == 302
    assert "/login/" in response["Location"]
    assert not CommandLineTool.objects.exists()


@pytest.mark.parametrize("view", TOOL_VIEWS)
def test_commandline_tools_are_superuser_only(client, view):
    client.force_login(
        make_user("tool-staff", ("peeringdb_server.commandlinetool", 0x0F))
    )
    assert client.get(tool_url(view)).status_code == 403
    assert client.post(tool_url(view), VALIDATE_DATA).status_code == 403
    assert not CommandLineTool.objects.exists()


@pytest.mark.parametrize("view", ["preview", "run"])
def test_commandline_tools_refuse_unlisted_tool(client, superuser, view):
    # offered only in tutorial mode, which the test settings leave off
    assert not is_listed_tool("pdb_wipe")
    client.force_login(superuser)
    response = client.post(tool_url(view), {"tool": "pdb_wipe", "keep_users": "on"})
    assert response.status_code == 400
    assert not CommandLineTool.objects.exists()


def test_org_merge_tool_needs_staff_login(client):
    user = make_user("super-not-staff", is_staff=False)
    user.is_superuser = True
    user.save()
    client.force_login(user)
    for url in ("/cp/peeringdb_server/organization/org-merge-tool/", ORG_MERGE_URL):
        response = client.get(url)
        assert response.status_code == 302
        assert "/login/" in response["Location"]


@pytest.mark.parametrize(
    "url,valid",
    [
        ("https://www.peeringdb.com/api", True),
        ("http://localhost:8000/api", True),
        ("file:///etc/passwd", False),
        ("ftp://example.com/api", False),
        ("javascript:alert(1)", False),
        ("not a url", False),
    ],
)
def test_reset_tool_load_data_url_must_be_http(url, valid):
    form = ToolReset.Form({"load_data": "on", "load_data_url": url})
    assert form.is_valid() == valid


# MFA enforcement


@pytest.fixture
def mfa_enforced(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() - timedelta(days=20)
    settings.MFA_FORCE_HARD_START = timezone.now() - timedelta(days=10)


def unverified(user):
    EmailAddress.objects.create(user=user, email=user.email, primary=True)
    return user


def verified(user):
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=True
    )
    return user


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_unverified_staff_is_sent_to_email_verification(client, mfa_enforced, flag):
    user = unverified(make_user("unverified", is_staff=False))
    setattr(user, flag, True)
    user.save()
    client.force_login(user)

    for path in ("/cp/", "/"):
        response = client.get(path)
        assert response.status_code == 302
        assert response["Location"] == reverse("user-profile")

    assert client.get("/profile").status_code == 200

    # the verification pages answer for themselves, the middleware stays out
    setup_urls = (reverse("user-profile"), reverse("two_factor:profile"))
    for path in (
        "/resend_email_confirmation",
        "/profile/email/add",
        "/accounts/confirm-email/abc/",
    ):
        response = client.get(path)
        assert response.get("Location") not in setup_urls, path


def test_unverified_staff_with_second_factor_passes(client, mfa_enforced):
    user = unverified(make_user("unverified-2fa"))
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    response = client.get("/cp/")
    assert response.status_code == 200


def test_verified_staff_is_sent_to_enrollment(client, mfa_enforced):
    user = verified(make_user("verified"))
    client.force_login(user)
    response = client.get("/cp/")
    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:profile")


def test_unverified_regular_user_keeps_exemption(client, mfa_enforced):
    user = unverified(make_user("regular-unverified", is_staff=False))
    client.force_login(user)
    response = client.get("/")
    assert response.status_code == 200


def test_cp_user_creation_sends_confirmation_mail(client, superuser, mailoutbox):
    client.force_login(superuser)
    url = "/cp/peeringdb_server/user/add/"
    response = client.post(
        url,
        change_form_data(
            client.get(url),
            username="admin-actions-created",
            email="admin-actions-created@example.net",
            password1="Created-pass-951",
            password2="Created-pass-951",
        ),
    )
    assert response.status_code == 302
    user = User.objects.get(username="admin-actions-created")
    assert not user.email_confirmed
    assert [m.to for m in mailoutbox] == [["admin-actions-created@example.net"]]


# History rollback and revert


@pytest.fixture
def versioned_org():
    with reversion.create_revision():
        org = Organization.objects.create(name="Admin actions versioned", status="ok")
    with reversion.create_revision():
        org.name = "Admin actions renamed"
        org.save()
    return org


def rollback_urls(org, version):
    name = "admin:peeringdb_server_organization_version_rollback"
    return (
        reverse(name, args=(org.id, version.id)),
        reverse(f"{name}_process", args=(org.id, version.id)),
    )


def test_history_rollback_needs_post_and_csrf_token(
    csrf_client, superuser, versioned_org
):
    original = Version.objects.get_for_object(versioned_org).last()
    view_url, process_url = rollback_urls(versioned_org, original)
    csrf_client.force_login(superuser)

    assert csrf_client.get(process_url).status_code == 405
    assert csrf_client.post(process_url).status_code == 403
    versioned_org.refresh_from_db()
    assert versioned_org.name == "Admin actions renamed"

    token = csrf_token(csrf_client.get(view_url))
    response = csrf_client.post(process_url, {"csrfmiddlewaretoken": token})
    assert response.status_code == 302
    versioned_org.refresh_from_db()
    assert versioned_org.name == "Admin actions versioned"


def test_history_rollback_refuses_another_objects_version(
    client, superuser, versioned_org
):
    other = Organization.objects.create(name="Admin actions other org", status="ok")
    original = Version.objects.get_for_object(versioned_org).last()
    _, process_url = rollback_urls(other, original)
    client.force_login(superuser)
    assert client.post(process_url).status_code == 404


def test_history_revert_needs_post_and_csrf_token(
    csrf_client, superuser, versioned_org
):
    url = reverse(
        "admin:peeringdb_server_organization_version_revert_process",
        args=(versioned_org.id,),
    )
    csrf_client.force_login(superuser)
    assert csrf_client.get(url).status_code == 405
    assert csrf_client.post(url).status_code == 403


def user_change_url(user):
    return reverse("admin:peeringdb_server_user_change", args=(user.id,))


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_superuser_manages_staff_accounts(client, superuser, flag):
    target = make_user("managed", is_staff=False)
    setattr(target, flag, True)
    target.save()
    client.force_login(superuser)

    url = user_change_url(target)
    response = client.post(
        url, full_change_form_data(client.get(url), first_name="Renamed")
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.first_name == "Renamed"

    url = reverse("admin:peeringdb_server_user_delete", args=(target.id,))
    assert client.post(url, {"post": "yes"}).status_code == 302
    assert not User.objects.filter(id=target.id).exists()


def test_superuser_bulk_deletes_staff_accounts(client, superuser):
    targets = [make_user("bulk-staff"), make_user("bulk-super")]
    targets[1].is_superuser = True
    targets[1].save()
    client.force_login(superuser)
    response = client.post(
        reverse("admin:peeringdb_server_user_changelist"),
        {
            "action": "delete_selected",
            "_selected_action": [user.id for user in targets],
            "post": "yes",
        },
    )
    assert response.status_code == 302
    assert not User.objects.filter(id__in=[user.id for user in targets]).exists()


def test_staff_saves_regular_account(client):
    target = make_user("regular-edit", is_staff=False)
    client.force_login(account_staff())
    url = user_change_url(target)
    response = client.post(
        url, full_change_form_data(client.get(url), first_name="Renamed")
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.first_name == "Renamed"


# Rows that belong to an account

ACCOUNT_ROW_APPS = (
    "account",
    "otp_totp",
    "otp_static",
    "otp_email",
    "django_security_keys",
)


def account_row_staff():
    return make_user(
        "account-rows",
        *[(app_label, 0x0F) for app_label in ACCOUNT_ROW_APPS],
        ("peeringdb_server.userapikey", 0x0F),
    )


ROW_ADD_URLS = (
    "/cp/account/emailaddress/add/",
    "/cp/otp_totp/totpdevice/add/",
    "/cp/otp_static/staticdevice/add/",
    "/cp/otp_email/emaildevice/add/",
    "/cp/django_security_keys/securitykey/add/",
)


def add_row(client, url, owner):
    fields = {"user": owner.id, "name": "planted", "confirmed": "on"}
    if "emailaddress" in url:
        fields = {"user": owner.id, "email": "planted@example.net", "verified": "on"}
    elif "emaildevice" in url:
        fields["email"] = "planted@example.net"
    elif "securitykey" in url:
        fields = {
            "user": owner.id,
            "name": "planted",
            "credential_id": f"planted-{owner.id}",
            "credential_public_key": "planted",
            "sign_count": 0,
            "type": "public-key",
            "passkey_login": "on",
        }
    return client.post(url, full_change_form_data(client.get(url), **fields))


def planted_rows(owner):
    return (
        EmailAddress.objects.filter(user=owner, email="planted@example.net").count()
        + TOTPDevice.objects.filter(user=owner, name="planted").count()
        + StaticDevice.objects.filter(user=owner, name="planted").count()
        + EmailDevice.objects.filter(user=owner, name="planted").count()
        + SecurityKey.objects.filter(user=owner, name="planted").count()
    )


@pytest.mark.parametrize("url", ROW_ADD_URLS)
def test_staff_cannot_add_rows_to_staff_accounts(client, superuser, url):
    client.force_login(account_row_staff())
    response = add_row(client, url, superuser)
    assert response.status_code == 200
    assert "Only superusers can do this" in response.content.decode()
    assert planted_rows(superuser) == 0


@pytest.mark.parametrize("url", ROW_ADD_URLS)
def test_staff_still_add_rows_to_regular_accounts(client, url):
    owner = make_user("row-owner", is_staff=False)
    client.force_login(account_row_staff())
    assert add_row(client, url, owner).status_code == 302
    assert planted_rows(owner) == 1


@pytest.mark.parametrize("url", ROW_ADD_URLS)
def test_superuser_adds_rows_to_staff_accounts(client, superuser, url):
    other = make_user("row-staff")
    client.force_login(superuser)
    assert add_row(client, url, other).status_code == 302
    assert planted_rows(other) == 1


def test_staff_cannot_change_rows_of_staff_accounts(client, superuser):
    rows = [
        EmailAddress.objects.create(user=superuser, email="second@example.net"),
        TOTPDevice.objects.create(user=superuser, name="phone", confirmed=True),
        StaticDevice.objects.create(user=superuser, name="backup", confirmed=True),
        EmailDevice.objects.create(user=superuser, name="mail", confirmed=True),
        SecurityKey.objects.create(
            user=superuser,
            name="passkey",
            credential_id="superuser-key",
            credential_public_key="key",
            type="public-key",
            passkey_login=True,
        ),
    ]
    client.force_login(account_row_staff())
    for row in rows:
        opts = row._meta
        change = f"/cp/{opts.app_label}/{opts.model_name}/{row.pk}/change/"
        delete = f"/cp/{opts.app_label}/{opts.model_name}/{row.pk}/delete/"
        assert client.get(change).status_code == 200
        assert client.post(change, {"user": superuser.id}).status_code == 403
        assert client.post(delete, {"post": "yes"}).status_code == 403
        assert type(row).objects.filter(pk=row.pk).exists()


def test_staff_cannot_bulk_verify_staff_addresses(client, superuser):
    address = EmailAddress.objects.create(user=superuser, email="second@example.net")
    client.force_login(account_row_staff())
    client.post(
        "/cp/account/emailaddress/",
        {"action": "make_verified", "_selected_action": [address.pk]},
    )
    address.refresh_from_db()
    assert not address.verified


def test_staff_cannot_change_superuser_api_key(client, superuser):
    key, _ = UserAPIKey.objects.create_key(
        name="handed out", user=superuser, readonly=True
    )
    client.force_login(account_row_staff())
    url = f"/cp/peeringdb_server/userapikey/{key.pk}/change/"
    assert client.get(url).status_code == 200
    response = client.post(url, {"name": "handed out", "status": "active"})
    assert response.status_code == 403
    key.refresh_from_db()
    assert key.readonly


def test_staff_still_change_regular_api_key(client):
    key, _ = UserAPIKey.objects.create_key(
        name="regular", user=make_user("key-holder", is_staff=False), readonly=True
    )
    client.force_login(account_row_staff())
    url = f"/cp/peeringdb_server/userapikey/{key.pk}/change/"
    response = client.post(url, full_change_form_data(client.get(url), readonly=""))
    assert response.status_code == 302
    key.refresh_from_db()
    assert not key.readonly


def test_bulk_verify_needs_change_permission(client):
    owner = make_user("verify-owner", is_staff=False)
    address = EmailAddress.objects.create(user=owner, email="unverified@example.net")
    client.force_login(make_user("verify-viewer", ("account", 0x01)))
    response = client.get("/cp/account/emailaddress/")
    assert response.status_code == 200
    assert 'value="make_verified"' not in response.content.decode()
    client.post(
        "/cp/account/emailaddress/",
        {"action": "make_verified", "_selected_action": [address.pk]},
    )
    address.refresh_from_db()
    assert not address.verified


def regular_rows(owner):
    return [
        EmailAddress.objects.create(user=owner, email="regular@example.net"),
        TOTPDevice.objects.create(user=owner, name="phone", confirmed=True),
        StaticDevice.objects.create(user=owner, name="backup", confirmed=True),
        EmailDevice.objects.create(user=owner, name="mail", confirmed=True),
        SecurityKey.objects.create(
            user=owner,
            name="passkey",
            credential_id="regular-key",
            credential_public_key="key",
            type="public-key",
            passkey_login=True,
        ),
    ]


def row_url(row, view="change"):
    opts = row._meta
    return f"/cp/{opts.app_label}/{opts.model_name}/{row.pk}/{view}/"


def test_staff_cannot_move_rows_onto_staff_accounts(client, superuser):
    owner = make_user("row-mover-owner", is_staff=False)
    client.force_login(account_row_staff())
    for row in regular_rows(owner):
        url = row_url(row)
        response = client.post(
            url, full_change_form_data(client.get(url), user=superuser.id)
        )
        assert response.status_code == 200, url
        assert "Only superusers can do this" in response.content.decode()
        row.refresh_from_db()
        assert row.user_id == owner.id


def test_staff_cannot_bulk_delete_rows_of_staff_accounts(client, superuser):
    rows = [
        TOTPDevice.objects.create(user=superuser, name="phone", confirmed=True),
        TOTPDevice.objects.create(
            user=make_user("bulk-row-owner", is_staff=False), name="phone"
        ),
    ]
    client.force_login(account_row_staff())
    client.post(
        "/cp/otp_totp/totpdevice/",
        {
            "action": "delete_selected",
            "_selected_action": [row.pk for row in rows],
            "post": "yes",
        },
    )
    # a selection with a row the actor may not delete deletes nothing
    assert TOTPDevice.objects.filter(pk__in=[row.pk for row in rows]).count() == 2

    client.post(
        "/cp/otp_totp/totpdevice/",
        {"action": "delete_selected", "_selected_action": [rows[1].pk], "post": "yes"},
    )
    assert not TOTPDevice.objects.filter(pk=rows[1].pk).exists()


def test_staff_bulk_verify_skips_only_staff_addresses(client, superuser):
    staff_address = EmailAddress.objects.create(
        user=superuser, email="second@example.net"
    )
    regular_address = EmailAddress.objects.create(
        user=make_user("verify-regular", is_staff=False), email="regular@example.net"
    )
    client.force_login(account_row_staff())
    response = client.post(
        "/cp/account/emailaddress/",
        {
            "action": "make_verified",
            "_selected_action": [staff_address.pk, regular_address.pk],
        },
        follow=True,
    )
    assert "Skipped second@example.net" in response.content.decode()
    staff_address.refresh_from_db()
    regular_address.refresh_from_db()
    assert not staff_address.verified
    assert regular_address.verified
