import datetime
import json
from datetime import timedelta
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from django.conf import settings as dj_settings
from django.contrib.auth.models import Group
from django.core import mail
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_security_keys.models import SecurityKey
from rest_framework.test import APIClient

from peeringdb_server.forms import OrgUserOptions
from peeringdb_server.models import (
    EmailAddress,
    EmailAddressData,
    Network,
    Organization,
    User,
    UserAPIKey,
)
from peeringdb_server.org_admin_views import update_user_options, users
from peeringdb_server.permissions import (
    check_permissions,
    get_permission_holder_from_request,
    init_permissions_helper,
)
from peeringdb_server.views import LoginView
from tests.util import mock_csrf_session, reset_group_ids


@pytest.fixture(autouse=True)
def override_mfa_settings(settings):
    settings.MFA_FORCE_SOFT_START = datetime.datetime.now() + timedelta(days=1)
    settings.MFA_FORCE_HARD_START = datetime.datetime.now() + timedelta(days=1)


@pytest.fixture
def reauth_objects():
    reset_group_ids()

    # verified users read every org through the user group, as in production
    Group.objects.get(id=dj_settings.USER_GROUP_ID).grainy_permissions.add_permission(
        "peeringdb.organization", 1
    )

    org = Organization.objects.create(name="Test", status="ok")
    org_b = Organization.objects.create(name="Test B", status="ok")
    net = Network.objects.create(name="Test", asn=63311, status="ok", org=org)
    net_b = Network.objects.create(name="Test B", asn=63312, status="ok", org=org_b)
    user = User.objects.create_user(
        "user_a", password="user_a", email="user_a@localhost"
    )
    user_b = User.objects.create_user(
        "user_b", password="user_b", email="user_b@domain.com"
    )
    user_c = User.objects.create_user(
        "user_c", password="user_c", email="user_c@domain.com"
    )
    email = EmailAddress.objects.create(user=user, email=user.email, verified=True)
    email_b = EmailAddress.objects.create(user=user, email="user_a@domain.com")
    email_data = EmailAddressData.objects.create(
        email=email, confirmed_date=timezone.now()
    )
    EmailAddressData.objects.create(email=email_b, confirmed_date=timezone.now())
    EmailAddress.objects.create(user=user_b, email="user_b@domain.com", verified=True)
    user.set_verified()
    user_c.set_verified()

    user.grainy_permissions.add_permission(
        f"peeringdb.organization.{org.id}.network.{net.id}", 15
    )
    user.grainy_permissions.add_permission(
        f"peeringdb.organization.{org_b.id}.network.{net_b.id}", 15
    )

    org.usergroup.user_set.add(user)
    org.admin_usergroup.user_set.add(user_c)
    org_b.usergroup.user_set.add(user)

    return {
        "org": org,
        "org_b": org_b,
        "net": net,
        "net_b": net_b,
        "user": user,
        "user_b": user_b,
        "user_c": user_c,
        "email": email,
        "email_data": email_data,
    }


@pytest.mark.django_db
def test_restrict_emails(reauth_objects):
    org = reauth_objects["org"]
    user = reauth_objects["user"]

    # no email restriction in place

    email_qs = EmailAddress.objects.filter(user=user).order_by("-verified")
    email_list = list(email_qs.values_list("email", flat=True))

    assert org.user_meets_email_requirements(user) == ([], email_list)

    # test 1: restrict user emails but provide no domains
    # email should not be restricted

    org.restrict_user_emails = True
    org.save()

    assert org.user_meets_email_requirements(user) == ([], email_list)

    # test 2: restrict user emails and provide domains
    # restriction should be in place
    # user does not meet requirements

    org.email_domains = "xyz.com"
    org.save()

    assert org.user_meets_email_requirements(user) == (email_list, [])

    # test 3: user meets requirements
    # email matching domain requirements should be returned

    EmailAddress.objects.create(user=user, email="user_b@xyz.com", verified=True)

    updated_email_qs = EmailAddress.objects.filter(user=user).order_by("-verified")
    updated_email_list = list(updated_email_qs.values_list("email", flat=True))
    valid_email_list = list(
        updated_email_qs.filter(email__endswith="xyz.com").values_list(
            "email", flat=True
        )
    )
    invalid_email_list = list(
        updated_email_qs.exclude(email__endswith="xyz.com").values_list(
            "email", flat=True
        )
    )

    assert org.user_meets_email_requirements(user) == (
        invalid_email_list,
        valid_email_list,
    )

    # test 4: turn off restrictions again, return users primary email

    org.restrict_user_emails = False
    org.save()

    assert org.user_meets_email_requirements(user) == ([], updated_email_list)


@pytest.mark.django_db
def test_restrict_emails_blocks_affiliations(reauth_objects):
    org = reauth_objects["org"]
    user = reauth_objects["user_b"]

    client = Client()
    client.force_login(user)

    org.restrict_user_emails = True
    org.email_domains = "xyz.com"
    org.save()

    email_list = list(
        EmailAddress.objects.filter(user=user)
        .order_by("-verified")
        .values_list("email", flat=True)
    )

    assert org.user_meets_email_requirements(user) == (email_list, [])

    client.post("/affiliate-to-org", data={"asn": 63311})

    assert not user.pending_affiliation_requests.exists()
    assert user.affiliation_requests.filter(status="denied").count() == 1


@pytest.mark.django_db
def test_restrict_emails_ignores_unverified_emails(reauth_objects):
    """
    Test that affiliation only checks verified emails, not unverified ones.
    Even if user has an unverified email matching the domain, they should be denied.
    """
    org = reauth_objects["org"]
    user = reauth_objects["user_b"]

    client = Client()
    client.force_login(user)

    org.restrict_user_emails = True
    org.email_domains = "xyz.com"
    org.save()

    # an unverified email that matches the domain
    EmailAddress.objects.create(user=user, email="user_b@xyz.com", verified=False)

    # User has verified email at domain.com (doesn't match)
    # and unverified email at xyz.com (matches but not verified)
    # Should be DENIED because no VERIFIED emails match

    client.post("/affiliate-to-org", data={"asn": 63311})

    assert not user.pending_affiliation_requests.exists()
    assert user.affiliation_requests.filter(status="denied").count() == 1


@pytest.mark.django_db
def test_restrict_emails_allows_verified_matching_email(reauth_objects):
    """
    Test that affiliation succeeds when user has a verified email matching the domain,
    even if they also have other non-matching emails.
    """
    org = reauth_objects["org"]
    user = reauth_objects["user_b"]

    client = Client()
    client.force_login(user)

    org.restrict_user_emails = True
    org.email_domains = "xyz.com"
    org.save()

    # a verified email that matches the domain
    EmailAddress.objects.create(user=user, email="user_b@xyz.com", verified=True)

    # User now has:
    # - user_b@domain.com (verified, doesn't match)
    # - user_b@xyz.com (verified, matches)
    # Should be ALLOWED because at least one verified email matches

    client.post("/affiliate-to-org", data={"asn": 63311})

    # Should have a pending request (not denied)
    assert user.pending_affiliation_requests.exists()
    assert user.affiliation_requests.filter(status="denied").count() == 0


@pytest.mark.django_db
def test_trigger_reauth(reauth_objects):
    user = reauth_objects["user"]
    org = reauth_objects["org"]
    email = reauth_objects["email"]
    net = reauth_objects["net"]
    net_b = reauth_objects["net_b"]

    client = Client()
    client.force_login(user)

    # check that the user has write permissions to both networks at both organizations

    content = client.get(f"/net/{net.id}").content.decode()

    assert "<!-- toggle edit mode -->" in content

    content = client.get(f"/net/{net_b.id}").content.decode()

    assert "<!-- toggle edit mode -->" in content

    # test 1: test that no re-auth is triggered when its disabled

    content = client.get(f"/org/{org.id}").content.decode()

    assert (
        "Some of your organizations request that you confirm your email address"
        not in content
    )

    email.refresh_from_db()

    assert email.verified

    # test 2: test that no re-auth is triggered when its enabled, but email was
    # confirmed with in period

    org.periodic_reauth = True
    org.periodic_reauth_period = "1y"
    org.save()

    email.data.confirmed_date = timezone.now() - timedelta(days=1)
    email.data.save()

    content = client.get(f"/org/{org.id}").content.decode()

    assert (
        "Some of your organizations request that you confirm your email address"
        not in content
    )

    email.refresh_from_db()

    assert email.verified

    # test 3: test that re-auth is triggered when its enabled, and email wasn't confirmed
    # within period

    email.data.confirmed_date = timezone.now() - timedelta(days=400)
    email.data.save()

    content = client.get(f"/org/{org.id}").content.decode()

    email.refresh_from_db()

    assert not email.verified

    assert (
        "Some of your organizations request that you confirm your email address"
        in content
    )

    # user should no longer have write permissions to network at first organization

    content = client.get(f"/net/{net.id}").content.decode()

    assert "<!-- toggle edit mode -->" not in content

    # user should still have write permissions to network at second organization

    content = client.get(f"/net/{net_b.id}").content.decode()

    assert "<!-- toggle edit mode -->" in content

    # test 4: confirm email

    email.data.confirmed_date = timezone.now()
    email.data.save()
    email.verified = True
    email.save()

    content = client.get(f"/net/{net.id}").content.decode()

    assert "<!-- toggle edit mode -->" in content

    content = client.get(f"/org/{org.id}").content.decode()

    assert (
        "Some of your organizations request that you confirm your email address"
        not in content
    )

    email.refresh_from_db()

    assert email.verified


# --- Passkey policy flag tests ---


def _make_pdb_login_view(user, storage_data=None, done_form_keys=None):
    """
    Create a peeringdb LoginView instance with mocked storage for unit testing
    condition methods and get_org_auth_settings.

    done_form_keys: iterable of step names to include in get_done_form_list()
                    (e.g. ["token"] to simulate a completed TOTP step).
                    Defaults to empty (no extra steps completed).
    """
    view = LoginView.__new__(LoginView)
    view.storage = MagicMock()
    view.storage.data = storage_data or {}
    view.storage.get_step_data = lambda step: None
    view.storage.validated_step_data = {}
    view.get_user = lambda: user
    type(view).remember_agent = PropertyMock(return_value=False)
    _keys = list(done_form_keys or [])
    view.get_done_form_list = lambda: {k: None for k in _keys}
    return view


@pytest.mark.django_db
def test_org_flags_passkey_disable_password_auth(reauth_objects):
    """
    set_org_flag / passkey_disable_password_auth property round-trip.
    """
    org = reauth_objects["org"]
    assert not org.passkey_disable_password_auth

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
    assert org.passkey_disable_password_auth

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, False)
    assert not org.passkey_disable_password_auth


@pytest.mark.django_db
def test_org_flags_disable_totp(reauth_objects):
    """
    set_org_flag / disable_totp property round-trip.
    """
    org = reauth_objects["org"]
    assert not org.disable_totp

    org.set_org_flag(dj_settings.ORG_FLAGS_DISABLE_TOTP, True)
    assert org.disable_totp

    org.set_org_flag(dj_settings.ORG_FLAGS_DISABLE_TOTP, False)
    assert not org.disable_totp


@pytest.mark.django_db
def test_org_flags_passkey_require_mfa(reauth_objects):
    """
    set_org_flag / passkey_require_mfa property round-trip.
    """
    org = reauth_objects["org"]
    assert not org.passkey_require_mfa

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    assert org.passkey_require_mfa

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, False)
    assert not org.passkey_require_mfa


@pytest.mark.django_db
def test_org_flags_independent_bits(reauth_objects):
    """
    Setting one flag does not affect the others.
    """
    org = reauth_objects["org"]
    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
    org.set_org_flag(dj_settings.ORG_FLAGS_DISABLE_TOTP, True)

    assert org.passkey_disable_password_auth
    assert org.disable_totp
    assert not org.passkey_require_mfa

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, False)
    assert not org.passkey_disable_password_auth
    assert org.disable_totp


@pytest.mark.django_db
def test_get_org_auth_settings_no_flags(reauth_objects):
    """
    get_org_auth_settings returns all False when no org has any flag set.
    """
    user = reauth_objects["user"]
    view = _make_pdb_login_view(user)
    result = view.get_org_auth_settings()

    assert not result["disable_password_auth"]
    assert not result["disable_totp"]
    assert not result["require_passkey_mfa"]


@pytest.mark.django_db
def test_get_org_auth_settings_single_org_flag(reauth_objects):
    """
    get_org_auth_settings reflects a flag set on one of the user's orgs.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]

    org.set_org_flag(dj_settings.ORG_FLAGS_DISABLE_TOTP, True)
    org.save()

    view = _make_pdb_login_view(user)
    result = view.get_org_auth_settings()

    assert not result["disable_password_auth"]
    assert result["disable_totp"]
    assert not result["require_passkey_mfa"]


@pytest.mark.django_db
def test_get_org_auth_settings_ors_across_orgs(reauth_objects):
    """
    A flag set on any one org is enough to enforce the restriction,
    even if the user's other orgs don't have it.
    """
    user = reauth_objects["user"]
    org_b = reauth_objects["org_b"]

    org_b.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    org_b.save()

    view = _make_pdb_login_view(user)
    result = view.get_org_auth_settings()

    assert result["require_passkey_mfa"]
    assert not result["disable_password_auth"]
    assert not result["disable_totp"]


@pytest.mark.django_db
def test_get_org_auth_settings_both_flags_coexist_independently(reauth_objects):
    """
    disable_totp and require_passkey_mfa affect different login branches and
    do not conflict. Both can be True simultaneously — the library handles them
    independently (disable_totp on the non-passkey path, require_passkey_mfa
    on the passkey path).
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]
    org_b = reauth_objects["org_b"]

    org.set_org_flag(dj_settings.ORG_FLAGS_DISABLE_TOTP, True)
    org.save()
    org_b.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    org_b.save()

    view = _make_pdb_login_view(user)
    result = view.get_org_auth_settings()

    assert result["require_passkey_mfa"]
    assert result["disable_totp"], (
        "disable_totp must remain True — it controls the non-passkey path "
        "and does not conflict with require_passkey_mfa"
    )


@pytest.mark.django_db
def test_done_blocks_password_login_when_passkey_required(reauth_objects):
    """
    done() redirects to login when org requires passkey auth but user
    authenticated via password (passkey_authenticated not set).
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]
    SecurityKey.objects.create(
        user=user,
        name="Existing passkey",
        passkey_login=True,
        credential_id="existing-passkey",
        credential_public_key="test",
    )

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
    org.save()

    view = _make_pdb_login_view(user, storage_data={})
    rf = RequestFactory()
    http_request = rf.get("/")
    http_request.session = {}
    view.request = http_request
    view.storage.reset = MagicMock()

    response = view.done([], **{})

    assert response.status_code == 302
    view.storage.reset.assert_called_once()


@pytest.mark.django_db
def test_done_allows_passkey_login_when_passkey_required(reauth_objects):
    """
    done() does not trigger the block path when org requires passkey and
    user authenticated via passkey.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
    org.save()

    view = _make_pdb_login_view(user, storage_data={"passkey_authenticated": True})
    rf = RequestFactory()
    http_request = rf.get("/")
    http_request.session = {}
    view.request = http_request
    view.storage.reset = MagicMock()

    # super().done() will fail without full wizard state — that's fine,
    # we just want to confirm the block path (storage.reset) was NOT taken.
    try:
        view.done([], **{})
    except Exception:
        pass

    view.storage.reset.assert_not_called()


@pytest.mark.django_db
def test_org_user_options_form_saves_passkey_flags(reauth_objects):
    """
    Posting passkey flags through update_user_options correctly writes org_flags.
    """
    org = reauth_objects["org"]
    org_admin_user = reauth_objects["user_c"]

    rf = RequestFactory()
    request = rf.post(
        "/",
        data={
            "org_id": org.id,
            "passkey_disable_password_auth": True,
            "disable_totp": False,
            "passkey_require_mfa": False,
        },
    )
    mock_csrf_session(request)
    request.user = org_admin_user

    resp = update_user_options(request, org=org)
    assert resp.status_code == 200

    org.refresh_from_db()
    assert org.passkey_disable_password_auth is True
    assert org.disable_totp is False
    assert org.passkey_require_mfa is False


@pytest.mark.django_db
def test_org_user_options_form_allows_disable_totp_with_require_mfa(reauth_objects):
    """
    disable_totp + passkey_require_mfa is a valid combination: the user can
    satisfy MFA via a second security key (or be redirected to enroll one).
    """
    org = reauth_objects["org"]

    form = OrgUserOptions(
        data={
            "org_id": org.id,
            "disable_totp": True,
            "passkey_require_mfa": True,
        },
        instance=org,
    )

    assert form.is_valid(), form.errors
    form.save()
    org.refresh_from_db()
    assert org.disable_totp
    assert org.passkey_require_mfa


@pytest.mark.django_db
def test_done_sets_session_key_on_block(reauth_objects):
    """
    done() stores passkey_required_error in the session when blocking a password login.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]
    SecurityKey.objects.create(
        user=user,
        name="Existing passkey",
        passkey_login=True,
        credential_id="existing-passkey",
        credential_public_key="test",
    )

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_DISABLE_PASSWORD_AUTH, True)
    org.save()

    view = _make_pdb_login_view(user, storage_data={})
    rf = RequestFactory()
    http_request = rf.get("/")
    http_request.session = {}
    view.request = http_request
    view.storage.reset = MagicMock()

    response = view.done([], **{})

    assert response.status_code == 302
    assert "passkey_required_error" in http_request.session
    assert isinstance(http_request.session["passkey_required_error"], str)


@pytest.mark.django_db
def test_done_redirects_to_mfa_setup_when_no_device(reauth_objects):
    """
    done() redirects to MFA setup when require_passkey_mfa is True but the
    user has no TOTP device registered.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    org.save()

    view = _make_pdb_login_view(
        user, storage_data={"passkey_authenticated": True}, done_form_keys=[]
    )
    rf = RequestFactory()
    http_request = rf.get("/")
    http_request.session = {}
    view.request = http_request
    view.storage.reset = MagicMock()

    with patch("django_security_keys.ext.two_factor.views.auth_login"):
        response = view.done([], **{})

    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:profile")
    view.storage.reset.assert_called_once()
    assert "passkey_mfa_error" in http_request.session
    assert isinstance(http_request.session["passkey_mfa_error"], str)


@pytest.mark.django_db
def test_done_redirects_with_totp_disabled_message_when_has_device(reauth_objects):
    """
    done() redirects with a TOTP-disabled message when require_passkey_mfa is
    True, the user has a TOTP device, but disable_totp is also True.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]
    org_b = reauth_objects["org_b"]

    TOTPDevice.objects.create(user=user, name="default", confirmed=True)

    org.set_org_flag(dj_settings.ORG_FLAGS_DISABLE_TOTP, True)
    org.save()
    org_b.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    org_b.save()

    view = _make_pdb_login_view(
        user, storage_data={"passkey_authenticated": True}, done_form_keys=[]
    )
    rf = RequestFactory()
    http_request = rf.get("/")
    http_request.session = {}
    view.request = http_request
    view.storage.reset = MagicMock()

    with patch("django_security_keys.ext.two_factor.views.auth_login"):
        response = view.done([], **{})

    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:profile")
    view.storage.reset.assert_called_once()
    assert "passkey_mfa_error" in http_request.session
    error = http_request.session["passkey_mfa_error"]
    assert org.name in error
    assert "disabled" in error.lower()


@pytest.mark.django_db
def test_done_password_path_redirects_when_totp_disabled_and_user_has_totp(
    reauth_objects,
):
    """
    When an org disables TOTP and the user logged in via password, but their
    only MFA is TOTP (which they can no longer use), they should be redirected
    to the MFA setup page rather than let through without any MFA challenge.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]

    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    org.set_org_flag(dj_settings.ORG_FLAGS_DISABLE_TOTP, True)
    org.save()

    # Password path: passkey_authenticated is NOT set
    view = _make_pdb_login_view(user, storage_data={}, done_form_keys=[])
    rf = RequestFactory()
    http_request = rf.get("/")
    http_request.session = {}
    view.request = http_request
    view.storage.reset = MagicMock()

    with patch("django_security_keys.ext.two_factor.views.auth_login"):
        response = view.done([], **{})

    assert response.status_code == 302
    assert response["Location"] == reverse("two_factor:profile")
    view.storage.reset.assert_called_once()
    assert "passkey_mfa_error" in http_request.session
    error = http_request.session["passkey_mfa_error"]
    assert org.name in error
    assert "disabled" in error.lower()


@pytest.mark.django_db
def test_done_password_path_allows_through_when_totp_disabled_and_no_totp_device(
    reauth_objects,
):
    """
    When an org disables TOTP but the user has no TOTP device at all,
    there is nothing being bypassed — the login should proceed normally.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]

    # No TOTP device — user has no MFA at all
    org.set_org_flag(dj_settings.ORG_FLAGS_DISABLE_TOTP, True)
    org.save()

    view = _make_pdb_login_view(user, storage_data={}, done_form_keys=[])
    rf = RequestFactory()
    http_request = rf.get("/")
    http_request.session = {}
    view.request = http_request
    view.storage.reset = MagicMock()

    # super().done() will fail without full wizard state — that's fine,
    # we only care that the block path (storage.reset) was NOT taken.
    try:
        view.done([], **{})
    except Exception:
        pass

    view.storage.reset.assert_not_called()


@pytest.mark.django_db
def test_has_security_key_step_passkey_mfa_required_has_2fa_key(reauth_objects):
    """
    When an org requires extra verification after passkey login and the user has
    a separate security key set up as a second factor, the login flow should
    prompt them to tap that key before they're let in.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    org.save()

    view = _make_pdb_login_view(user, storage_data={"passkey_authenticated": True})

    with patch.object(SecurityKey, "credentials", return_value=["fake-cred"]):
        result = view.has_security_key_step()

    assert result is True


@pytest.mark.django_db
def test_has_security_key_step_passkey_mfa_required_no_2fa_key(reauth_objects):
    """
    When an org requires extra verification after passkey login but the user
    hasn't set up any security key as a second factor, the security key step
    is skipped — there's nothing to prompt them with.
    """
    user = reauth_objects["user"]
    org = reauth_objects["org"]

    org.set_org_flag(dj_settings.ORG_FLAGS_PASSKEY_REQUIRE_MFA, True)
    org.save()

    view = _make_pdb_login_view(user, storage_data={"passkey_authenticated": True})

    with patch.object(SecurityKey, "credentials", return_value=[]):
        result = view.has_security_key_step()

    assert result is False


@pytest.mark.django_db
def test_get_form_kwargs_passes_passkey_credential_id(reauth_objects):
    """
    The credential the user tapped to log in with their passkey is passed through
    to the second-factor step, so the form can block someone trying to reuse the
    same key again as their MFA verification.
    """
    user = reauth_objects["user"]
    view = _make_pdb_login_view(
        user,
        storage_data={"passkey_credential_id": "test-cred-id-abc123"},
    )
    rf = RequestFactory()
    http_request = rf.get("/")
    http_request.session = {}
    view.request = http_request
    view._security_key_device = MagicMock()

    parent_kwargs = {"data": None, "files": None}
    with patch(
        "django_security_keys.ext.two_factor.views.LoginView.get_form_kwargs",
        return_value=dict(parent_kwargs),
    ):
        kwargs = view.get_form_kwargs("security-key")

    assert kwargs.get("passkey_credential_id") == "test-cred-id-abc123"


def _expire_reauth(org, user):
    """
    Turn on periodic re-auth for `org` and make `user`'s only email overdue
    """

    email, _ = EmailAddress.objects.get_or_create(
        user=user, email=user.email, defaults={"verified": True}
    )
    # confirmed_date is auto_now_add, so it can only be backdated after create
    data, _ = EmailAddressData.objects.get_or_create(email=email)
    data.confirmed_date = timezone.now() - timedelta(days=400)
    data.save()
    org.periodic_reauth = True
    org.periodic_reauth_period = "1y"
    org.save()


@pytest.mark.django_db
def test_reauth_strips_org_admin_grants(reauth_objects):
    org, net = reauth_objects["org"], reauth_objects["net"]
    admin = reauth_objects["user_c"]

    perms = init_permissions_helper(User.objects.get(id=admin.id))
    assert perms.check(net.grainy_namespace, "u")
    assert perms.check(org.grainy_namespace_manage, "u")

    _expire_reauth(org, admin)

    perms = init_permissions_helper(User.objects.get(id=admin.id))
    assert org.grainy_namespace not in perms.pset.namespaces
    assert not perms.check(net.grainy_namespace, "u")
    assert not perms.check(org.grainy_namespace_manage, "u")
    assert not perms.check(org.grainy_namespace_oauth, "u")


@pytest.mark.django_db
def test_reauth_strips_member_org_root_only_for_that_org(reauth_objects):
    org, org_b = reauth_objects["org"], reauth_objects["org_b"]
    net, net_b = reauth_objects["net"], reauth_objects["net_b"]
    user = reauth_objects["user"]

    _expire_reauth(org, user)

    perms = init_permissions_helper(User.objects.get(id=user.id))
    assert org.grainy_namespace not in perms.pset.namespaces
    assert not perms.check(net.grainy_namespace, "u")
    assert org_b.grainy_namespace in perms.pset.namespaces
    assert perms.check(net_b.grainy_namespace, "u")


@pytest.mark.django_db
def test_reauth_applies_to_user_api_keys(reauth_objects):
    org = reauth_objects["org"]
    net, net_b = reauth_objects["net"], reauth_objects["net_b"]
    user = reauth_objects["user"]

    _expire_reauth(org, user)

    _, key = UserAPIKey.objects.create_key(name="k", user=user)
    request = RequestFactory().put(
        f"/api/net/{net.id}", HTTP_AUTHORIZATION="Api-Key " + key
    )
    holder = get_permission_holder_from_request(request)
    assert not check_permissions(holder, net.grainy_namespace, "u")
    assert check_permissions(holder, net_b.grainy_namespace, "u")


@pytest.mark.django_db
def test_reauth_api_key_delete_error_names_org(reauth_objects):
    org, net = reauth_objects["org"], reauth_objects["net"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)

    _expire_reauth(org, admin)

    response = client.delete(reverse("api:net-detail", args=(net.id,)))
    assert response.status_code == 403
    assert response.json()["meta"]["error"] == (
        f"Re-authentication required for {org.name}: confirm your email"
    )

    net.refresh_from_db()
    assert net.name == "Test"
    assert net.status == "ok"


@pytest.mark.django_db
def test_reauth_session_api_delete_error_names_org(reauth_objects):
    org, net = reauth_objects["org"], reauth_objects["net"]
    admin = reauth_objects["user_c"]

    _expire_reauth(org, admin)

    client = APIClient()
    client.force_login(admin)
    response = client.delete(reverse("api:net-detail", args=(net.id,)))
    assert response.status_code == 403
    assert response.json()["meta"]["error"] == (
        f"Re-authentication required for {org.name}: confirm your email"
    )

    net.refresh_from_db()
    assert net.status == "ok"


@pytest.mark.django_db
@pytest.mark.parametrize("auth", ["api_key", "session"])
def test_reauth_refused_writes_send_one_mail(reauth_objects, auth, settings):
    """
    The rollback of a refused write must not undo the unverified flag, which
    would send the confirmation mail again on every write (#527)
    """

    # a replayed refusal never reaches the view, as writes spaced further
    # apart than the negative cache expiry would

    settings.NEGATIVE_CACHE_ENABLED = False

    org, net = reauth_objects["org"], reauth_objects["net"]
    admin = reauth_objects["user_c"]

    _expire_reauth(org, admin)

    client = APIClient()
    if auth == "api_key":
        _, key = UserAPIKey.objects.create_key(name="k", user=admin)
        client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    else:
        client.force_login(admin)

    mail.outbox = []
    for _ in range(3):
        response = client.put(
            reverse("api:net-detail", args=(net.id,)), {"name": "x"}, format="json"
        )
        assert response.status_code in (401, 403)

    assert [message.to for message in mail.outbox] == [[admin.email]]
    assert not EmailAddress.objects.get(user=admin, email=admin.email).verified


@pytest.mark.django_db
def test_reauth_write_with_key_of_inactive_user_sends_no_mail(reauth_objects, settings):
    """
    A key of a deactivated user is refused before re-auth is evaluated
    """

    settings.NEGATIVE_CACHE_ENABLED = False

    org, net = reauth_objects["org"], reauth_objects["net"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin)

    _expire_reauth(org, admin)
    admin.is_active = False
    admin.save()

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    mail.outbox = []
    response = client.put(
        reverse("api:net-detail", args=(net.id,)), {"name": "x"}, format="json"
    )
    assert response.status_code == 403
    assert "Inactive API key" in response.json()["meta"]["error"]

    assert mail.outbox == []
    assert EmailAddress.objects.get(user=admin, email=admin.email).verified


@pytest.mark.django_db
def test_reauth_api_key_org_users_denied(reauth_objects):
    org = reauth_objects["org"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin)

    _expire_reauth(org, admin)

    url = reverse("api:organization-users-list", kwargs={"org_id": org.id})
    response = APIClient().get(url, HTTP_AUTHORIZATION="Api-Key " + key)
    assert response.status_code == 403
    assert (
        f"Re-authentication required for {org.name}: confirm your email"
        in response.json()["meta"]["error"]
    )


@pytest.mark.django_db
def test_reauth_org_admin_required(reauth_objects):
    org = reauth_objects["org"]
    admin = reauth_objects["user_c"]

    def request_users():
        request = RequestFactory().get(f"/org-admin/users?org_id={org.id}")
        request.user = User.objects.get(id=admin.id)
        return users(request)

    assert request_users().status_code == 200

    _expire_reauth(org, admin)

    response = request_users()
    assert response.status_code == 403
    assert json.loads(response.content) == {
        "non_field_errors": [
            f"Re-authentication required for {org.name}: confirm your email"
        ]
    }


@pytest.mark.django_db
def test_reauth_error_only_for_the_target_org(reauth_objects):
    """
    A denial on an org the user is not due for re-auth with gives no
    re-auth reason
    """

    org, net_b = reauth_objects["org"], reauth_objects["net_b"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin)

    _expire_reauth(org, admin)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    response = client.delete(reverse("api:net-detail", args=(net_b.id,)))
    assert response.status_code == 403
    assert "Re-authentication" not in response.content.decode()


@pytest.mark.django_db
def test_reauth_api_key_create_error_names_org(reauth_objects):
    org, net = reauth_objects["org"], reauth_objects["net"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin)

    _expire_reauth(org, admin)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    response = client.post(
        reverse("api:poc-list"),
        {
            "net_id": net.id,
            "role": "Abuse",
            "visible": "Public",
            "name": "reauth contact",
            "email": "contact@localhost",
        },
        format="json",
    )
    assert response.status_code in (401, 403)
    assert response.json()["meta"]["error"] == (
        f"Re-authentication required for {org.name}: confirm your email"
    )
    assert not net.poc_set.filter(name="reauth contact").exists()


@pytest.mark.django_db
def test_reauth_api_key_user_without_email_address(reauth_objects):
    """
    A key user with nothing to re-confirm keeps read access and loses write
    access to the org, instead of erroring
    """

    org, net = reauth_objects["org"], reauth_objects["net"]
    operator = User.objects.create_user("operator", password="operator", email="")
    operator.set_verified()
    org.admin_usergroup.user_set.add(operator)
    org.periodic_reauth = True
    org.periodic_reauth_period = "1y"
    org.save()

    _, key = UserAPIKey.objects.create_key(name="k", user=operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    url = reverse("api:net-detail", args=(net.id,))

    assert client.get(url).status_code == 200

    response = client.delete(url)
    assert response.status_code == 403
    assert "Re-authentication required for Test:" in response.json()["meta"]["error"]

    net.refresh_from_db()
    assert net.status == "ok"


def _overdue_member(org, username):
    """
    A plain member of `org`, with no write grant of their own, who is due for
    re-auth
    """

    member = User.objects.create_user(
        username, password=username, email=f"{username}@localhost"
    )
    member.set_verified()
    org.usergroup.user_set.add(member)
    _expire_reauth(org, member)
    return member


@pytest.mark.django_db
def test_reauth_error_not_given_when_reauth_would_not_allow(reauth_objects):
    """
    Re-confirming would not give a plain member write access, so their denial
    does not blame re-auth
    """

    org, net = reauth_objects["org"], reauth_objects["net"]
    member = _overdue_member(org, "member_x")
    _, key = UserAPIKey.objects.create_key(name="k", user=member)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    response = client.delete(reverse("api:net-detail", args=(net.id,)))
    assert response.status_code == 403
    assert "Re-authentication" not in response.content.decode()


@pytest.mark.django_db
def test_reauth_error_not_given_to_readonly_key(reauth_objects):
    org, net = reauth_objects["org"], reauth_objects["net"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin, readonly=True)

    _expire_reauth(org, admin)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    response = client.delete(reverse("api:net-detail", args=(net.id,)))
    assert response.status_code == 403
    assert "Re-authentication" not in response.content.decode()


@pytest.mark.django_db
def test_reauth_error_not_given_for_patch(reauth_objects):
    """
    PATCH is refused for everyone, whatever re-auth says
    """

    org, net = reauth_objects["org"], reauth_objects["net"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin)

    _expire_reauth(org, admin)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    response = client.patch(
        reverse("api:net-detail", args=(net.id,)), {"name": "x"}, format="json"
    )
    assert response.status_code == 403
    assert "Re-authentication" not in response.content.decode()


@pytest.mark.django_db
def test_reauth_error_not_given_for_unrelated_parent(reauth_objects):
    """
    A create under another org's network is not blamed on re-auth, even with
    the overdue org named elsewhere in the payload
    """

    org, net_b = reauth_objects["org"], reauth_objects["net_b"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin)

    _expire_reauth(org, admin)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)
    response = client.post(
        reverse("api:poc-list"),
        {
            "net_id": net_b.id,
            "org_id": org.id,
            "role": "Abuse",
            "visible": "Public",
            "name": "unrelated contact",
            "email": "contact@localhost",
        },
        format="json",
    )
    assert response.status_code in (401, 403)
    assert "Re-authentication" not in response.content.decode()


@pytest.mark.django_db
def test_reauth_org_admin_required_member_not_blamed(reauth_objects):
    org = reauth_objects["org"]
    member = _overdue_member(org, "member_y")

    request = RequestFactory().get(f"/org-admin/users?org_id={org.id}")
    request.user = User.objects.get(id=member.id)
    response = users(request)
    assert response.status_code == 403
    assert json.loads(response.content) == {}


@pytest.mark.django_db
def test_reauth_api_key_org_users_readonly_not_blamed(reauth_objects):
    org = reauth_objects["org"]
    admin = reauth_objects["user_c"]
    _, key = UserAPIKey.objects.create_key(name="k", user=admin, readonly=True)

    _expire_reauth(org, admin)

    url = reverse("api:organization-users-add", kwargs={"org_id": org.id})
    response = APIClient().post(
        url,
        {"user_email": "user_b@domain.com", "role": "member"},
        format="json",
        HTTP_AUTHORIZATION="Api-Key " + key,
    )
    assert response.status_code == 403
    assert "API key is readonly" in response.json()["meta"]["error"]


@pytest.mark.django_db
def test_reauth_error_names_only_the_denying_org(reauth_objects):
    """
    A user overdue in two orgs is only told about the org whose grants would
    have allowed the request
    """

    org, org_b = reauth_objects["org"], reauth_objects["org_b"]
    net, net_b = reauth_objects["net"], reauth_objects["net_b"]
    user = reauth_objects["user"]

    _expire_reauth(org, user)
    org_b.periodic_reauth = True
    org_b.periodic_reauth_period = "1y"
    org_b.save()

    _, key = UserAPIKey.objects.create_key(name="k", user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key " + key)

    response = client.delete(reverse("api:net-detail", args=(net.id,)))
    assert response.status_code == 403
    assert response.json()["meta"]["error"] == (
        f"Re-authentication required for {org.name}: confirm your email"
    )

    response = client.delete(reverse("api:net-detail", args=(net_b.id,)))
    assert response.status_code == 403
    assert response.json()["meta"]["error"] == (
        f"Re-authentication required for {org_b.name}: confirm your email"
    )
