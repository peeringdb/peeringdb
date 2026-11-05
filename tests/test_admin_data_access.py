import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_grainy.models import GroupPermission
from django_otp.plugins.otp_email.models import EmailDevice
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_grant_model,
    get_refresh_token_model,
)

import peeringdb_server.admin as admin
from peeringdb_server.models import EnvironmentSetting, Organization, User
from peeringdb_server.templatetags.util import sanitize_notification_banner
from peeringdb_server.validators import validate_notification_banner

pytestmark = pytest.mark.django_db
PASSWORD = "admin-data-access-password"

LOOKUPS = (
    "/grappelli/lookup/related/",
    "/grappelli/lookup/m2m/",
    "/grappelli/lookup/autocomplete/",
)


@pytest.fixture(autouse=True)
def mfa_rollout_in_future(settings):
    settings.MFA_FORCE_SOFT_START = timezone.now() + timedelta(days=10)
    settings.MFA_FORCE_HARD_START = timezone.now() + timedelta(days=20)


@pytest.fixture
def superuser():
    return User.objects.create_user(
        "data-access-super",
        email="data-access-super@example.net",
        password=PASSWORD,
        status="ok",
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def staff():
    """
    Staff account without any model permission
    """
    return User.objects.create_user(
        "data-access-staff",
        email="data-access-staff@example.net",
        password=PASSWORD,
        status="ok",
        is_staff=True,
    )


@pytest.fixture
def readonly_staff():
    """
    Staff account with view permission on the peeringdb_server models
    """
    user = User.objects.create_user(
        "data-access-readonly",
        email="data-access-readonly@example.net",
        password=PASSWORD,
        status="ok",
        is_staff=True,
    )
    group = Group.objects.create(name="data-access-readonly")
    for app_label in admin.PERMISSION_APP_LABELS:
        GroupPermission.objects.create(
            group=group, namespace=app_label, permission=0x01
        )
    group.user_set.add(user)
    return user


def lookup(client, path, model, object_id, **extra):
    params = {
        "app_label": model._meta.app_label,
        "model_name": model._meta.model_name,
    }
    if path.endswith("autocomplete/"):
        params["term"] = str(object_id)
    else:
        params["object_id"] = object_id
    params.update(extra)
    return client.get(path, params)


@pytest.mark.parametrize("path", LOOKUPS)
@pytest.mark.parametrize("model", [User, TOTPDevice])
def test_lookups_require_view_permission(client, staff, superuser, path, model):
    TOTPDevice.objects.create(user=superuser, name="phone")
    client.force_login(staff)
    obj = model.objects.first()
    response = lookup(client, path, model, obj.pk)
    assert response.status_code == 403


@pytest.mark.parametrize("path", LOOKUPS)
def test_lookups_refuse_models_not_registered_in_admin(client, superuser, path):
    client.force_login(superuser)
    response = lookup(client, path, ContentType, ContentType.objects.first().pk)
    assert response.status_code == 403


@pytest.mark.parametrize("path", LOOKUPS)
def test_lookups_ignore_query_string_filters(client, readonly_staff, superuser, path):
    client.force_login(readonly_staff)
    # the autocomplete searches by term, the others resolve an id
    target = superuser.username if path.endswith("autocomplete/") else superuser.pk

    labels = []
    for prefix in (superuser.password[:8], "nomatch"):
        response = lookup(
            client,
            path,
            User,
            target,
            query_string=f"password__startswith={prefix}",
        )
        assert response.status_code == 200
        labels.append(json.loads(response.content)[0]["label"])

    # a matching and a non-matching filter must give the same answer
    assert labels[0] == labels[1]
    assert superuser.username in labels[0]


@pytest.mark.parametrize("path", LOOKUPS)
@pytest.mark.parametrize("to_field", ["password", ""])
def test_lookups_refuse_arbitrary_to_field(client, superuser, path, to_field):
    client.force_login(superuser)
    response = lookup(client, path, User, superuser.pk, to_field=to_field)
    assert response.status_code == 403


def test_superuser_autocomplete_keeps_working(client, superuser):
    client.force_login(superuser)
    response = lookup(client, LOOKUPS[2], User, superuser.username, to_field="id")
    assert response.status_code == 200
    data = json.loads(response.content)
    assert data[0]["value"] == superuser.pk


@pytest.mark.parametrize("path", LOOKUPS[:2])
def test_superuser_lookups_keep_working(client, superuser, path):
    device = TOTPDevice.objects.create(user=superuser, name="phone")
    client.force_login(superuser)
    response = lookup(client, path, TOTPDevice, device.pk)
    assert response.status_code == 200
    assert json.loads(response.content)[0]["label"] == str(device)


def test_readonly_staff_lookup_of_viewable_model(client, readonly_staff, superuser):
    client.force_login(readonly_staff)
    response = lookup(client, LOOKUPS[0], User, superuser.pk)
    assert response.status_code == 200
    assert superuser.username in json.loads(response.content)[0]["label"]


def export(client, model, fields, model_name=None):
    prefix = "userresource" if model is User else f"{model._meta.model_name}resource"
    data = {"format": "0", "resource": "0"}
    for field in fields:
        data[f"{prefix}_{field}"] = "on"
    model_name = model_name or model._meta.model_name
    return client.post(f"/cp/{model._meta.app_label}/{model_name}/export/", data)


USER_EXPORT_FIELDS = ("username", "email", "password", "is_superuser")


@pytest.mark.parametrize("model", [User, Organization])
def test_export_requires_view_permission(client, staff, superuser, model):
    client.force_login(staff)
    url = f"/cp/{model._meta.app_label}/{model._meta.model_name}/export/"
    assert client.get(url).status_code == 403
    assert export(client, model, ["id"]).status_code == 403


@pytest.mark.parametrize("model", [User, Organization])
def test_export_with_view_permission(client, readonly_staff, superuser, model):
    Organization.objects.create(name="Data access export org", status="ok")
    client.force_login(readonly_staff)
    response = export(client, model, ["id"])
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")


def test_export_with_change_permission_only(client, superuser):
    user = User.objects.create_user(
        "data-access-change-only",
        email="data-access-change-only@example.net",
        password=PASSWORD,
        status="ok",
        is_staff=True,
    )
    group = Group.objects.create(name="data-access-change-only")
    GroupPermission.objects.create(
        group=group, namespace="peeringdb_server", permission=0x02
    )
    group.user_set.add(user)
    Organization.objects.create(name="Data access change-only org", status="ok")
    client.force_login(user)

    response = client.get("/cp/peeringdb_server/organization/")
    assert response.status_code == 200
    assert "/cp/peeringdb_server/organization/export/" in response.content.decode()
    response = export(client, Organization, ["id"])
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")


@pytest.mark.parametrize("model_name", ["user", "userpermission"])
@pytest.mark.parametrize("login", ["readonly_staff", "superuser"])
def test_user_export_omits_password_hashes(
    client, request, superuser, login, model_name
):
    client.force_login(request.getfixturevalue(login))
    response = export(client, User, USER_EXPORT_FIELDS, model_name=model_name)
    assert response.status_code == 200
    content = response.content.decode()
    header = content.splitlines()[0].split(",")
    assert "email" in header
    assert "password" not in header
    assert "user_permissions" not in header
    assert superuser.email in content
    assert superuser.password not in content


@pytest.fixture
def mfa_device_staff():
    """
    Staff account with view and change permission on the MFA device admins
    """
    user = User.objects.create_user(
        "data-access-mfa",
        email="data-access-mfa@example.net",
        password=PASSWORD,
        status="ok",
        is_staff=True,
    )
    group = Group.objects.create(name="data-access-mfa")
    for app_label in ("otp_totp", "otp_static"):
        GroupPermission.objects.create(
            group=group, namespace=app_label, permission=0x03
        )
    group.user_set.add(user)
    return user


@pytest.fixture
def mfa_devices(superuser):
    totp = TOTPDevice.objects.create(user=superuser, name="phone", confirmed=True)
    static = StaticDevice.objects.create(user=superuser, name="backup", confirmed=True)
    for token in BACKUP_TOKENS:
        static.token_set.create(token=token)
    return totp, static


BACKUP_TOKENS = ("dataacc1", "dataacc2")


@pytest.mark.parametrize("login", ["mfa_device_staff", "superuser"])
def test_device_admins_hide_totp_seed_and_backup_tokens(
    client, request, mfa_devices, login
):
    totp, static = mfa_devices
    client.force_login(request.getfixturevalue(login))

    response = client.get(f"/cp/otp_totp/totpdevice/{totp.pk}/change/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Throttling" in content
    assert totp.key not in content
    assert 'name="key"' not in content

    response = client.get("/cp/otp_totp/totpdevice/")
    assert response.status_code == 200
    assert "qrcode" not in response.content.decode()

    for view in ("config", "qrcode"):
        response = client.get(f"/cp/otp_totp/totpdevice/{totp.pk}/{view}/")
        assert response.status_code == 403

    response = client.get(f"/cp/otp_static/staticdevice/{static.pk}/change/")
    assert response.status_code == 200
    content = response.content.decode()
    for token in BACKUP_TOKENS:
        assert token not in content


def test_totp_add_form_keeps_the_new_key(client, superuser):
    # the seed on the add form is the one being created, as in django-otp;
    # existing devices never show theirs (see the test above)
    client.force_login(superuser)
    response = client.get("/cp/otp_totp/totpdevice/add/")
    assert response.status_code == 200
    assert 'name="key"' in response.content.decode()


def clear_totp_lockout(client, totp):
    return client.post(
        f"/cp/otp_totp/totpdevice/{totp.pk}/change/",
        {
            "user": totp.user_id,
            "name": totp.name,
            "confirmed": "on",
            "step": totp.step,
            "t0": totp.t0,
            "digits": totp.digits,
            "tolerance": totp.tolerance,
            "drift": totp.drift,
            "throttling_failure_timestamp_0": "",
            "throttling_failure_timestamp_1": "",
            "throttling_failure_count": 0,
        },
    )


def locked_totp(user):
    return TOTPDevice.objects.create(
        user=user,
        name="phone",
        confirmed=True,
        throttling_failure_count=5,
        throttling_failure_timestamp=timezone.now(),
    )


def test_totp_lockout_can_still_be_cleared(client, mfa_device_staff):
    user = User.objects.create_user(
        "data-access-locked", email="data-access-locked@example.net", status="ok"
    )
    totp = locked_totp(user)
    key = totp.key

    client.force_login(mfa_device_staff)
    response = clear_totp_lockout(client, totp)
    assert response.status_code == 302, response.content.decode()[:2000]
    totp.refresh_from_db()
    assert totp.throttling_failure_count == 0
    assert totp.key == key


def test_staff_totp_lockout_is_cleared_by_superusers(
    client, mfa_device_staff, superuser
):
    # devices of staff and superuser accounts are managed by superusers only
    other_staff = User.objects.create_user(
        "data-access-other-staff", status="ok", is_staff=True
    )
    totp = locked_totp(other_staff)

    client.force_login(mfa_device_staff)
    assert clear_totp_lockout(client, totp).status_code == 403
    totp.refresh_from_db()
    assert totp.throttling_failure_count == 5

    client.force_login(superuser)
    assert clear_totp_lockout(client, totp).status_code == 302
    totp.refresh_from_db()
    assert totp.throttling_failure_count == 0


def changelist_url(model):
    return f"/cp/{model._meta.app_label}/{model._meta.model_name}/"


SECRET_LOOKUPS = (
    # django.contrib.auth's UserAdmin refuses password lookups itself
    (User, "password__startswith=a"),
    (admin.UserPermission, "password__startswith=a"),
    (TOTPDevice, "key__startswith=a"),
    (EmailDevice, "token__startswith=1"),
    (get_application_model(), "client_secret__startswith=a"),
    (get_access_token_model(), "token__startswith=a"),
    (get_access_token_model(), "token_checksum__startswith=a"),
    (get_refresh_token_model(), "token__startswith=a"),
    (get_grant_model(), "code__startswith=a"),
    (User, "password=x"),
)


@pytest.mark.parametrize("model,query", SECRET_LOOKUPS)
def test_changelist_refuses_filters_on_secret_columns(client, superuser, model, query):
    client.force_login(superuser)
    response = client.get(f"{changelist_url(model)}?{query}")
    assert response.status_code == 400


@pytest.mark.parametrize("model_name", ["user", "userpermission"])
def test_export_refuses_filters_on_secret_columns(client, superuser, model_name):
    client.force_login(superuser)
    response = client.post(
        f"/cp/peeringdb_server/{model_name}/export/?password__startswith=a",
        {"format": "0", "resource": "0", "userresource_id": "on"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "model,query",
    [
        (User, "is_superuser__exact=1"),
        (TOTPDevice, "confirmed__exact=1"),
        (get_access_token_model(), "id__gte=1"),
    ],
)
def test_changelist_keeps_other_filters(client, superuser, model, query):
    client.force_login(superuser)
    response = client.get(f"{changelist_url(model)}?{query}")
    assert response.status_code == 200


ALLOWED_BANNERS = (
    "Plain text & more",
    "<b>Vote</b> <strong>now</strong> <i>in</i> <em>the</em><br>election<br/>",
    '<a href="https://www.peeringdb.com/poll">Poll</a>',
    '<a href="/elections" target="_blank" rel="noopener">Vote now</a>',
)

REFUSED_BANNERS = (
    "<script>alert(1)</script>",
    '<img src="x" onerror="alert(1)">',
    '<a href="https://example.com" onclick="alert(1)">x</a>',
    '<a href="javascript:alert(1)">x</a>',
    '<a href="&#106;avascript:alert(1)">x</a>',
    '<a href="https://example.com" target="_self">x</a>',
    '<b style="color: red">x</b>',
    "<p>x</p>",
    "<!-- x -->",
    # parsed differently on save and render before both used bleach's parser
    '<a href="http://[::1&amp;#93;">x</a>',
    '<a href="http://[">x</a>',
    # dropped by the tree builder at render, so refused rather than stripped
    '<body onload="alert(1)">Vote',
    '<frame src="https://example.com">Vote',
    "<!DOCTYPE html><b>Vote</b>",
    "</div>Vote",
    # each URL parser misses the scheme in one of these
    '<a href="1:abc">Vote</a>',
    '<a href="javascript:1">Vote</a>',
    '<a href="vbscript:1">Vote</a>',
)

UNPARSEABLE_LINKS = (
    '<a href="http://[::1&amp;#93;">Vote</a>',
    '<a href="http://[">Vote</a>',
)


@pytest.mark.parametrize("value", ALLOWED_BANNERS)
def test_notification_banner_validator_accepts_allowlist(value):
    assert validate_notification_banner(value) == value


@pytest.mark.parametrize("value", REFUSED_BANNERS)
def test_notification_banner_validator_refuses_other_markup(value):
    with pytest.raises(ValidationError):
        validate_notification_banner(value)


def test_notification_banner_admin_refuses_disallowed_markup(client, superuser):
    client.force_login(superuser)
    response = client.post(
        "/cp/peeringdb_server/environmentsetting/add/",
        {
            "setting": "NOTIFICATION_BANNER_CONTENT",
            "value": "<script>alert(1)</script>",
        },
    )
    assert response.status_code == 200
    assert "Not allowed: &lt;script&gt;" in response.content.decode()
    assert not EnvironmentSetting.objects.filter(
        setting="NOTIFICATION_BANNER_CONTENT"
    ).exists()

    value = '<a href="https://www.peeringdb.com/poll" target="_blank">Poll</a>'
    response = client.post(
        "/cp/peeringdb_server/environmentsetting/add/",
        {"setting": "NOTIFICATION_BANNER_CONTENT", "value": value},
    )
    assert response.status_code == 302
    assert EnvironmentSetting.get_setting_value("NOTIFICATION_BANNER_CONTENT") == value


@pytest.mark.parametrize("path", ["/", "/about"])
def test_notification_banner_render_strips_disallowed_markup(client, superuser, path):
    # a row saved before validation existed, or the env var fallback
    EnvironmentSetting.objects.create(
        setting="NOTIFICATION_BANNER_CONTENT",
        value_str=(
            '<script>alert("banner")</script><img src=x onerror=alert(1)>'
            '<a href="https://www.peeringdb.com/poll" target="_blank" '
            'rel="opener" onclick="alert(2)">Vote</a> <b>now</b>'
        ),
        user=superuser,
    )
    response = client.get(path)
    assert response.status_code == 200
    content = response.content.decode()
    assert '<script>alert("banner")' not in content
    assert "onerror" not in content
    assert "alert(2)" not in content
    assert (
        '<a href="https://www.peeringdb.com/poll" target="_blank" '
        'rel="noopener noreferrer">Vote</a> <b>now</b>'
    ) in content


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "&#106;avascript:alert(1)",
        "java&#9;script:alert(1)",
        "javascript:1",
    ],
)
def test_notification_banner_render_drops_script_links(href):
    rendered = sanitize_notification_banner(f'<a href="{href}">x</a>')
    assert "href" not in rendered
    assert "alert" not in rendered


@pytest.mark.parametrize("value", UNPARSEABLE_LINKS)
def test_notification_banner_render_drops_unparseable_link(value):
    assert sanitize_notification_banner(value) == (
        '<a rel="noopener noreferrer">Vote</a>'
    )


@pytest.mark.parametrize("value", UNPARSEABLE_LINKS)
def test_notification_banner_unparseable_link_is_refused_and_pages_render(
    client, superuser, value
):
    client.force_login(superuser)
    response = client.post(
        "/cp/peeringdb_server/environmentsetting/add/",
        {"setting": "NOTIFICATION_BANNER_CONTENT", "value": value},
    )
    assert response.status_code == 200
    assert "Not allowed" in response.content.decode()

    # a row stored before validation, or the env var fallback
    EnvironmentSetting.objects.create(
        setting="NOTIFICATION_BANNER_CONTENT", value_str=value, user=superuser
    )
    client.logout()
    response = client.get("/")
    assert response.status_code == 200
    assert '<a rel="noopener noreferrer">Vote</a>' in response.content.decode()


def test_notification_banner_render_never_raises(monkeypatch):
    def broken(tag, name, value):
        raise ValueError("unparseable")

    monkeypatch.setattr(
        "peeringdb_server.templatetags.util.notification_banner_attribute_allowed",
        broken,
    )
    assert sanitize_notification_banner(
        '<a href="https://example.com">Vote</a> <b>now</b>'
    ) == ("Vote now")


def test_notification_banner_render_keeps_relative_link():
    assert sanitize_notification_banner('<a href="/elections">Vote now</a>') == (
        '<a href="/elections" rel="noopener noreferrer">Vote now</a>'
    )


# a decimal character reference beyond Python's int digit limit
LONG_ENTITY_LINK = '<a href="/&#' + "9" * 4301 + ';">Vote</a>'


def test_notification_banner_long_entity_link_is_refused(client, superuser):
    with pytest.raises(ValidationError):
        validate_notification_banner(LONG_ENTITY_LINK)

    client.force_login(superuser)
    response = client.post(
        "/cp/peeringdb_server/environmentsetting/add/",
        {"setting": "NOTIFICATION_BANNER_CONTENT", "value": LONG_ENTITY_LINK},
    )
    assert response.status_code == 200
    assert "Not allowed" in response.content.decode()


def test_notification_banner_long_entity_link_renders(client, settings):
    # too long for a stored row, but the setting can come from the environment
    settings.NOTIFICATION_BANNER_CONTENT = LONG_ENTITY_LINK
    assert sanitize_notification_banner(LONG_ENTITY_LINK) == (
        '<a rel="noopener noreferrer">Vote</a>'
    )
    response = client.get("/")
    assert response.status_code == 200
    assert '<a rel="noopener noreferrer">Vote</a>' in response.content.decode()
