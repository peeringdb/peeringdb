"""
Caller identity (#487) and the redacted URI (#495) in the uWSGI request log.
"""

import base64
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import include, path, re_path, resolve
from django.utils.timezone import make_aware
from oauth2_provider.models import AccessToken
from rest_framework.test import APITestCase

from peeringdb_server.middleware import (
    UwsgiLogUriMiddleware,
    UwsgiLogVarsMiddleware,
    get_log_auth_id,
    get_log_invalid_key_id,
    get_log_uri,
    is_log_api_query_param,
    is_log_sensitive_param,
    truncate_log_uri,
)
from peeringdb_server.models import Organization, OrganizationAPIKey, User, UserAPIKey

from .util import reset_group_ids

# the autouse cache cleanup fixture needs the database
pytestmark = pytest.mark.django_db


class FakeUwsgi:
    """
    Stands in for the uwsgi module, recording the request's log variables.
    """

    def __init__(self):
        self.logvars = {}

    def set_logvar(self, key, value):
        self.logvars[key] = value


def fake_view(request, **kwargs):
    return HttpResponse()


# routes for the path redaction tests (ROOT_URLCONF="tests.test_request_log_auth")
urlpatterns = [
    path("fake/<str:token>/<slug:slug>", fake_view),
    re_path(r"^n/(?P<token>[^/]+?)$", fake_view),
    re_path(r"^a/(?P<token>(?P<key>ABC)DEF)$", fake_view),
    path("inc/<str:token>/", include([path("<str:token>", fake_view)])),
    path("default/<slug:slug>", fake_view, {"token": "x"}),
    path("num/<int:key>", fake_view),
]


@override_settings(
    API_CACHE_ENABLED=False,
    # once MFA enforcement is live basic auth is answered with a 403 before
    # the auth middleware sees it, so push both start dates out of the way
    MFA_FORCE_SOFT_START=make_aware(datetime(2099, 1, 1)),
    MFA_FORCE_HARD_START=make_aware(datetime(2099, 1, 1)),
)
class UwsgiLogVarsTest(APITestCase):
    def setUp(self):
        reset_group_ids()
        caches["negative"].clear()
        self.user = User.objects.create(username="log_auth_user")
        self.user.set_password("log_auth_pass")
        self.user.save()
        # the client loads its middleware on its first request
        self.uwsgi = FakeUwsgi()
        patcher = patch("peeringdb_server.middleware.uwsgi", self.uwsgi)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, path="/api/fac", method="get"):
        """
        Requests `path` and returns the response and its log variables.
        """
        self.uwsgi.logvars.clear()
        response = getattr(self.client, method)(path)
        logvars = dict(self.uwsgi.logvars)
        # covered by UwsgiLogUriTest
        logvars.pop("log_uri", None)
        return response, logvars

    def basic_auth(self, username, password):
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {encoded}")

    def test_anonymous(self):
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars == {"auth_id": "anon", "auth_status": "unauthenticated"}

    def test_session_auth(self):
        self.client.force_login(self.user)
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars == {
            "auth_id": f"u{self.user.id}",
            "auth_status": "authenticated",
        }

    def test_basic_auth(self):
        self.basic_auth("log_auth_user", "log_auth_pass")
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars == {
            "auth_id": f"u{self.user.id}",
            "auth_status": "authenticated",
        }

    def test_failed_basic_auth_never_logs_username(self):
        for username in ("log_auth_user", "no_such_log_user"):
            with self.subTest(username=username):
                caches["negative"].clear()
                self.basic_auth(username, "wrong-password")
                response, logvars = self.request()
                assert response.status_code == 401
                # the header keeps reporting the attempted username
                assert response.headers["X-Auth-ID"] == username
                assert logvars == {
                    "auth_id": "unverified",
                    "auth_status": "unauthenticated",
                }

    def test_user_api_key(self):
        api_key, key = UserAPIKey.objects.create_key(
            name="log", user=self.user, readonly=True
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars["auth_id"] == f"u{self.user.id}_apikey_{api_key.prefix}"
        # key auth doesn't set request.user, same as the header
        assert logvars["auth_status"] == "unauthenticated"

    def test_org_api_key(self):
        org = Organization.objects.create(name="Log Auth Org", status="ok")
        api_key, key = OrganizationAPIKey.objects.create_key(name="log", org=org)
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars["auth_id"] == f"o{org.id}_apikey_{api_key.prefix}"

    def test_denied_api_key_logs_full_identity(self):
        org = Organization.objects.create(name="Log Auth Org", status="ok")
        api_key, key = OrganizationAPIKey.objects.create_key(name="log", org=org)
        auth_id = f"o{org.id}_apikey_{api_key.prefix}"
        assert len(auth_id) > 16
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        # as-set is read-only, DRF answers a write with a 401
        response, logvars = self.request("/api/as_set", method="post")
        assert response.status_code == 401
        # the header keeps cutting the identity to 16 characters on a 401
        assert response.headers["X-Auth-ID"] == auth_id[:16]
        assert logvars["auth_id"] == auth_id

    def test_invalid_api_key_logs_prefix_only(self):
        api_key, real_key = UserAPIKey.objects.create_key(
            name="log", user=self.user, readonly=True
        )
        prefix, secret = real_key.split(".", 1)
        typo = "x" if secret[-1] != "x" else "y"
        key = f"{prefix}.{secret[:-1]}{typo}"
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response, logvars = self.request()
        assert response.status_code == 401
        # the header keeps reporting the first 16 characters
        assert response.headers["X-Auth-ID"] == f"apikey_{key[:16]}"
        assert logvars == {
            "auth_id": f"apikey_{prefix}",
            "auth_status": "unauthenticated",
        }

    def test_invalid_api_key_unexpected_shape(self):
        for key in (
            "bogus",
            "nodotbutverylongkey",
            "S3cr3tS3cr3tS3cr3tS3cr3tS3cr3t",
            "ghp_A1b2.C3d4E5f6G7h8",
            "short.secretpart",
        ):
            with self.subTest(key=key):
                caches["negative"].clear()
                self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
                response, logvars = self.request()
                assert response.status_code == 401
                assert logvars["auth_id"] == "apikey_invalid"

    def test_inactive_api_key(self):
        api_key, key = UserAPIKey.objects.create_key(
            name="log", user=self.user, readonly=True
        )
        api_key.status = "inactive"
        api_key.save()
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response, logvars = self.request()
        assert response.status_code == 401
        assert logvars["auth_id"] == "unverified"

    def test_negative_cache_response(self):
        self.basic_auth("no_such_log_user", "wrong-password")
        self.client.get("/api/fac")
        response, logvars = self.request()
        assert response.headers.get("X-Cached-Response") == "True"
        assert response.status_code == 401
        assert logvars == {"auth_id": "unverified", "auth_status": "unauthenticated"}

    def test_oauth_bearer(self):
        AccessToken.objects.create(
            user=self.user,
            token="log-auth-access-token",
            expires=make_aware(datetime.now() + timedelta(days=1)),
            scope="openid profile email",
        )
        for path in ("/profile/v1", "/oauth2/userinfo/"):
            for header in (
                "Bearer log-auth-access-token",
                "bearer  log-auth-access-token",
            ):
                with self.subTest(path=path, header=header):
                    self.client.credentials(HTTP_AUTHORIZATION=header)
                    response, logvars = self.request(path)
                    assert response.status_code == 200
                    assert "X-Auth-ID" not in response.headers
                    assert response.headers["X-Auth-Status"] == "authenticated"
                    assert logvars == {
                        "auth_id": f"u{self.user.id}_oauth",
                        "auth_status": "authenticated",
                    }

    def test_oauth_bearer_rejected_by_api(self):
        AccessToken.objects.create(
            user=self.user,
            token="log-auth-access-token",
            expires=make_aware(datetime.now() + timedelta(days=1)),
            scope="profile email",
        )
        self.client.credentials(HTTP_AUTHORIZATION="Bearer log-auth-access-token")
        response, logvars = self.request()
        assert response.status_code == 401
        assert logvars == {"auth_id": "unverified", "auth_status": "unauthenticated"}

    def test_invalid_oauth_bearer(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer no-such-token")
        response, logvars = self.request("/profile/v1")
        assert response.status_code == 403
        assert logvars == {"auth_id": "unverified", "auth_status": "unauthenticated"}

    def test_view_exception(self):
        self.client.raise_request_exception = False
        self.basic_auth("log_auth_user", "log_auth_pass")
        with patch(
            "peeringdb_server.rest.FacilityViewSet.list",
            side_effect=RuntimeError("boom"),
        ):
            response, logvars = self.request()
        assert response.status_code == 500
        assert logvars == {
            "auth_id": f"u{self.user.id}",
            "auth_status": "authenticated",
        }

    def test_logvar_failure_does_not_change_response(self):
        with (
            patch.object(self.uwsgi, "set_logvar", side_effect=RuntimeError("boom")),
            # the django logger runs at ERROR outside DEBUG
            self.assertLogs("django", "ERROR") as logs,
        ):
            response = self.client.get("/api/fac")
        assert response.status_code == 200
        assert "setting uwsgi log variables failed" in "\n".join(logs.output)


@override_settings(API_CACHE_ENABLED=False)
class UwsgiLogUriTest(APITestCase):
    def setUp(self):
        caches["negative"].clear()
        self.uwsgi = FakeUwsgi()
        patcher = patch("peeringdb_server.middleware.uwsgi", self.uwsgi)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, path):
        """
        Requests `path` and returns the response and its `log_uri`.
        """
        self.uwsgi.logvars.clear()
        response = self.client.get(path)
        return response, self.uwsgi.logvars["log_uri"]

    def test_runs_first(self):
        assert settings.MIDDLEWARE[0] == (
            "peeringdb_server.middleware.UwsgiLogUriMiddleware"
        )

    def test_path_without_query(self):
        response, log_uri = self.request("/api/fac")
        assert log_uri == "/api/fac"

    def test_password_reset_token_not_logged(self):
        token = "ResetTokenValue0123456789"
        response, log_uri = self.request(f"/reset-password?token={token}&target=1")
        assert log_uri == "/reset-password?[redacted]"

    def test_oauth_authorize_query_not_logged(self):
        response, log_uri = self.request(
            "/oauth2/authorize/?response_type=code&client_id=log-client"
            "&state=OAuthStateValue0123&code_challenge=OAuthChallengeValue0123"
        )
        assert log_uri == "/oauth2/authorize/?[redacted]"

    def test_confirm_email_key_not_logged(self):
        response, log_uri = self.request(
            "/accounts/confirm-email/ConfirmKeyValue0123:abc/"
        )
        assert log_uri == "/accounts/confirm-email/[redacted]/"

    def test_confirm_email_key_without_slash_not_logged(self):
        # redirected to the slashed URL before it resolves
        response, log_uri = self.request(
            "/accounts/confirm-email/ConfirmKeyValue0123:abc"
        )
        assert response.status_code == 301
        assert log_uri == "/accounts/confirm-email/[redacted]"

    def test_short_confirm_email_key_redacts_only_its_segment(self):
        response, log_uri = self.request("/accounts/confirm-email/a/")
        assert log_uri == "/accounts/confirm-email/[redacted]/"

    def test_device_user_code_not_logged(self):
        response, log_uri = self.request(
            "/oauth2/device-confirm/log-client/UserCode0123"
        )
        assert log_uri == "/oauth2/device-confirm/log-client/[redacted]"

    def test_api_query_keeps_filters_and_redacts_the_rest(self):
        key = "AbCd1234.ApiQuerySecretValue0123"
        # base64 of log_auth_user:hunter22, padded
        basic = "bG9nX2F1dGhfdXNlcjpodW50ZXIyMg=="
        response, log_uri = self.request(
            "/api/fac?name__contains=equinix&state=CA&org_id__in=1,2,3&depth=1"
            f"&authorization=Api-Key+{key}&key={key}&pwd=hunter2&{key}&{key}="
            f"&{basic}&name__password=s3cr3t"
        )
        # values log as sent, unknown parameters are redacted whole
        assert log_uri == (
            "/api/fac?name__contains=equinix&state=CA&org_id__in=1,2,3&depth=1"
            + "&[redacted]" * 7
        )

    def test_private_filter_redacted(self):
        response, log_uri = self.request("/api/poc?email=someone@example.com&net_id=1")
        assert log_uri == "/api/poc?[redacted]&net_id=1"

    def test_control_characters_escaped(self):
        response, log_uri = self.request("/api/fac%0Afake%20line?name=a%0Ab")
        assert log_uri == "/api/fac%0Afake%20line?name=a%0Ab"

    def test_early_response(self):
        # answered by the negative cache before URL resolution
        self.client.credentials(HTTP_AUTHORIZATION="Api-Key bogus")
        self.client.get("/api/fac?key=CachedSecret0123")
        response, log_uri = self.request("/api/fac?key=CachedSecret0123")
        assert response.headers.get("X-Cached-Response") == "True"
        assert log_uri == "/api/fac?[redacted]"

    def test_failure_does_not_change_response(self):
        with (
            patch(
                "peeringdb_server.middleware.build_log_uri",
                side_effect=RuntimeError("boom"),
            ),
            self.assertLogs("django", "ERROR") as logs,
        ):
            response, log_uri = self.request("/api/fac")
        assert response.status_code == 200
        assert log_uri == "[redacted]"
        assert "get_log_uri failed" in "\n".join(logs.output)


@pytest.mark.parametrize(
    "url,logged",
    [
        ("/fake/ed/edited", "/fake/[redacted]/edited"),
        ("/fake/a/a", "/fake/[redacted]/a"),
        ("/fake/Secret%20Value/x", "/fake/[redacted]/x"),
        # an endpoint regex ending in $ is matched whole
        ("/n/abc%0A", "/n/[redacted]"),
        # overlapping captures
        ("/a/ABCDEF", "/a/[redacted]"),
        # the same name captured at two levels
        ("/inc/outer/inner", "/inc/[redacted]/[redacted]"),
        # a sensitive default kwarg has no segment, a converted value no
        # longer reads as captured: the whole path goes
        ("/default/x", "[redacted]"),
        ("/num/007", "[redacted]"),
    ],
)
@override_settings(ROOT_URLCONF="tests.test_request_log_auth")
def test_log_uri_redacts_captured_segment(url, logged):
    assert get_log_uri(RequestFactory().get(url)) == logged


@pytest.mark.parametrize(
    "url,logged",
    [
        ("/captcha/audio/a.wav", "/captcha/audio/[redacted].wav"),
        ("/captcha/image/a/", "/captcha/image/[redacted]/"),
        ("/captcha/image/a@2/", "/captcha/image/[redacted]@2/"),
    ],
)
def test_log_uri_captcha_key(url, logged):
    assert get_log_uri(RequestFactory().get(url)) == logged


def log_uri_for(path, query):
    """
    Returns the `log_uri` of a GET to `path` with the raw query string `query`.
    """
    request = RequestFactory().get(path, QUERY_STRING=query)
    return get_log_uri(request)


def test_log_uri_semicolon_separator():
    assert log_uri_for("/api/net", "depth=1;api_key=SecretKey0123&asn=42") == (
        "/api/net?depth=1&[redacted]&asn=42"
    )


def test_log_uri_unresolved_api_path():
    # only the API-wide parameters are known without a view
    assert log_uri_for("/api/nosuchtag", "asn=42&state=CA&key=SecretKey0123") == (
        "/api/nosuchtag?asn=42&[redacted]&[redacted]"
    )


def test_log_uri_utf8_query():
    # WSGI decodes the raw bytes as latin-1
    raw = "name=café".encode().decode("latin-1")
    assert log_uri_for("/api/net", raw) == "/api/net?name=caf%C3%A9"


def test_log_uri_long_query_stops_early():
    with patch(
        "peeringdb_server.middleware.is_log_api_query_param", return_value=False
    ) as checked:
        log_uri = log_uri_for("/api/net", "&".join(["a"] * 32000))
    assert log_uri.endswith("[truncated]")
    assert len(log_uri) <= 255
    assert checked.call_count < 30


def test_log_uri_static_path_not_resolved():
    with patch("peeringdb_server.middleware.resolve_for_log") as resolve_for_log:
        log_uri = log_uri_for(f"{settings.STATIC_URL}site.js", "v=1")
    assert log_uri == f"{settings.STATIC_URL}site.js?[redacted]"
    resolve_for_log.assert_not_called()


def test_log_uri_raw_control_characters_escaped():
    request = RequestFactory().get("/api/fac", QUERY_STRING="name=a\nb c")
    request.resolver_match = resolve("/api/fac")
    assert get_log_uri(request) == "/api/fac?name=a%0Ab%20c"


@pytest.mark.parametrize(
    "uri,logged",
    [
        ("/api/fac", "/api/fac"),
        ("/api/fac?id__in=" + "1" * 239, "/api/fac?id__in=" + "1" * 239),
        (
            "/api/fac?id__in=" + "1" * 240,
            "/api/fac?id__in=" + "1" * 228 + "[truncated]",
        ),
        # a percent escape cut in half is dropped whole
        (
            "/api/fac?name=" + "a" * 228 + "%2C" * 10,
            "/api/fac?name=" + "a" * 228 + "[truncated]",
        ),
    ],
)
def test_truncate_log_uri(uri, logged):
    assert truncate_log_uri(uri) == logged
    assert len(truncate_log_uri(uri).encode()) <= 255


@pytest.mark.parametrize(
    "name,sensitive",
    [
        ("key", True),
        ("token", True),
        ("user_code", True),
        ("access_token", True),
        ("api_key", True),
        ("apiKey", True),
        ("password1", True),
        ("client_secret", True),
        ("client_id", False),
        ("uoar_id", False),
        ("object_id", False),
        ("zipcode", False),
        ("path", False),
    ],
)
def test_is_log_sensitive_param(name, sensitive):
    assert is_log_sensitive_param(name) is sensitive


@pytest.mark.parametrize(
    "path,name,kept",
    [
        ("/api/fac", "state", True),
        ("/api/fac", "name__contains", True),
        ("/api/fac", "org_id__in", True),
        ("/api/fac", "campus_id", True),
        ("/api/fac", "net_count", True),
        ("/api/fac", "org__name", True),
        ("/api/fac", "org__name__contains", True),
        ("/api/fac", "net_id", True),
        ("/api/fac", "depth", True),
        ("/api/ix", "confirm", True),
        ("/api/carrier", "carrierfac_set__facility_id", True),
        ("/api/carrier", "carrierfac_set__facility_id__in", False),
        ("/api/carrier", "carrierfac_set__facility_id__contains", False),
        ("/api/carrier", "carrierfac_set__facility__name", False),
        ("/api/netixlan", "meta__planned_status_change__status", True),
        ("/api/netixlan", "net__name", True),
        ("/api/ix", "net__asn", True),
        ("/api/ix", "net__asn__in", True),
        ("/api/net", "ix__name", True),
        ("/api/net", "fac__country", True),
        ("/api/ix", "net__password", False),
        ("/api/net", "netixlan_set__ipaddr4", False),
        ("/api/net", "notes_private", False),
        ("/api/netixlan", "meta__token", False),
        ("/api/netixlan", "net__notes_private", False),
        ("/api/netixlan", "ixlan__ixf_ixp_member_list_url", False),
        ("/api/poc", "email", False),
        ("/api/poc", "phone__contains", False),
        ("/api/poc", "name", False),
        ("/api/poc", "name__contains", False),
        ("/api/poc", "net_id", True),
        ("/api/net", "name", True),
        ("/api/net", "limit_id", False),
        ("/api/net", "fields_id", False),
        ("/api/fac", "authorization", False),
        ("/api/fac", "key", False),
        ("/api/fac", "pwd", False),
        ("/api/fac", "token", False),
        ("/api/fac", "sessionid", False),
        ("/api/fac", "name__password", False),
        ("/api/org", "api_keys", False),
        ("/api/org", "api_keys__prefix", False),
        ("/api/org", "oauth_applications__client_secret", False),
    ],
)
def test_is_log_api_query_param(path, name, kept):
    assert is_log_api_query_param(name, resolve(path).func.cls) is kept


@pytest.mark.parametrize("middleware", [UwsgiLogVarsMiddleware, UwsgiLogUriMiddleware])
def test_middleware_not_used_without_uwsgi(middleware):
    with (
        patch("peeringdb_server.middleware.uwsgi", None),
        pytest.raises(MiddlewareNotUsed),
    ):
        middleware(lambda request: HttpResponse())


def test_log_auth_id_unevaluated_session_cookie():
    request = RequestFactory().get("/api/fac")
    request.COOKIES[settings.SESSION_COOKIE_NAME] = "some-session"
    assert get_log_auth_id(request) == "unverified"


def test_log_auth_id_rejected_session_cookie():
    request = RequestFactory().get("/api/fac")
    request.COOKIES[settings.SESSION_COOKIE_NAME] = "stale-session"
    request.user = AnonymousUser()
    assert get_log_auth_id(request) == "anon"


@pytest.mark.parametrize(
    "key,logged",
    [
        ("AbCd1234.secretsecretsecret", "apikey_AbCd1234"),
        ("AbCd1234.", "apikey_AbCd1234"),
        ("AbCd123.secret", "apikey_invalid"),
        ("AbCd12345.secret", "apikey_invalid"),
        ("AbCd-234.secret", "apikey_invalid"),
        ("nodotatall", "apikey_invalid"),
        ("", "apikey_invalid"),
    ],
)
def test_get_log_invalid_key_id(key, logged):
    assert get_log_invalid_key_id(key) == logged
