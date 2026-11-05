import sys
import time
from unittest import mock

import pytest
from django.core.cache import caches
from django.core.files.uploadedfile import TemporaryUploadedFile
from django.http import QueryDict
from django.template import Context, Engine
from django.test import Client, RequestFactory, override_settings
from django_otp.plugins.otp_totp.models import TOTPDevice

from peeringdb_server.log import ExceptionReporter
from peeringdb_server.models import User

pytestmark = pytest.mark.django_db

SENSITIVE = {
    "password": "plain-password-1",
    "password_c": "plain-password-2",
    "password1": "plain-password-3",
    "client_secret": "plain-secret-4",
    "refresh_token": "plain-token-5",
    "token-otp_token": "plain-otp-6",
    "code": "plain-code-7",
    "code_verifier": "plain-verifier-8",
    "credential": "plain-credential-9",
}

# kept away from the frames: the HTML report also shows their source lines
LOCALS = {
    "password_c": "local-password-1",
    "client_secret": "local-secret-2",
    "refresh_token": "local-token-3",
    "code": "local-code-4",
    "http_auth": "local-basic-5",
    "req_key": "local-api-key-6",
    "credentials": "local-credentials-7",
    "auth": "local-api-key-9",
    "http_cookie": "local-session-10",
    "b32key": "local-seed-11",
    "nested": "local-nested-12",
    "listed": "local-listed-13",
    "cookie": "local-cookie-14",
    "rawkey": "local-seed-15",
}

DEEP = {
    "password": "deep-password-16",
    "token": "deep-token-17",
    "upload": "upload-token-18",
}

RESET_TOKEN = "reset-token-8"

PUBLIC = {
    "username": "visible-username",
    "email": "visible@example.net",
    "country_code": "visible-country",
    "api_key_name": "visible-key-name",
}


class BrokenPasswordReset:
    class objects:
        @staticmethod
        def filter(**kwargs):
            raise RuntimeError("down")


def report_for(request, fail=None):
    try:
        if fail:
            fail()
        raise RuntimeError("report")
    except RuntimeError:
        return ExceptionReporter(request, *sys.exc_info()).get_traceback_html()


@override_settings(DEBUG=False)
def test_error_report_masks_credential_post_parameters():
    request = RequestFactory().post("/any", {**SENSITIVE, **PUBLIC})
    report = report_for(request)
    for value in SENSITIVE.values():
        assert value not in report
    for value in PUBLIC.values():
        assert value in report


@override_settings(DEBUG=False)
def test_error_report_masks_credential_variables():
    def fail():
        password_c = LOCALS["password_c"]
        options = {"client_secret": LOCALS["client_secret"], "name": "visible-name"}
        query = QueryDict(mutable=True)
        query.update(
            {"refresh_token": LOCALS["refresh_token"], "scope": "visible-scope"}
        )
        code = LOCALS["code"]
        http_auth = LOCALS["http_auth"]
        req_key = LOCALS["req_key"]
        credentials = LOCALS["credentials"]
        headers = {
            "Authorization": LOCALS["http_auth"],
            "HTTP_COOKIE": LOCALS["http_cookie"],
            "Accept": "visible-accept",
        }
        auth = ["Api-Key", LOCALS["auth"]]
        b32key = LOCALS["b32key"]
        data = {
            "form": {"password": LOCALS["nested"]},
            "page": "visible-page",
            "rows": [{"client_secret": LOCALS["listed"], "row": "visible-row"}],
        }
        cookie = LOCALS["cookie"]
        rawkey = LOCALS["rawkey"]
        username = "visible-username"
        assert password_c and options and query and code and username
        assert http_auth and req_key and credentials and headers
        assert auth and b32key and data and cookie and rawkey
        raise RuntimeError("fail")

    report = report_for(RequestFactory().get("/any"), fail)
    for value in LOCALS.values():
        assert value not in report
    for value in (
        "visible-name",
        "visible-scope",
        "visible-username",
        "visible-accept",
        "visible-page",
        "visible-row",
    ):
        assert value in report


@override_settings(DEBUG=False, ADMINS=[("ops", "ops@example.net")])
def test_password_change_error_mail_hides_passwords(mailoutbox):
    user = User.objects.create_user(
        "error-report", email="error-report@example.net", password="current-pw-478"
    )
    # MFA enforcement would redirect a user without a second factor
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    caches["error_emails"].clear()
    client = Client(raise_request_exception=False)
    client.force_login(user)
    # fail after the view has read the passwords into its locals; a Mock
    # would keep the call arguments in frames that production never has
    with mock.patch("peeringdb_server.views.UserPasswordReset", BrokenPasswordReset):
        response = client.post(
            "/change-password",
            {
                "password_c": "current-pw-478",
                "password": "new-password-478",
                "password_v": "new-password-478",
            },
        )
    assert response.status_code == 500
    assert len(mailoutbox) == 1
    report = mailoutbox[0].body + "".join(
        content for content, _ in mailoutbox[0].alternatives
    )
    assert "Internal Server Error: /change-password" in mailoutbox[0].subject
    assert "current-pw-478" not in report
    assert "new-password-478" not in report


@override_settings(DEBUG=False)
def test_error_report_masks_credentials_in_the_query_string():
    request = RequestFactory().get(
        "/reset-password",
        {"token": RESET_TOKEN, "target": "visible-target"},
        REQUEST_URI=f"/reset-password?token={RESET_TOKEN}&target=visible-target",
    )
    try:
        raise RuntimeError("report")
    except RuntimeError:
        reporter = ExceptionReporter(request, *sys.exc_info())
        reports = (reporter.get_traceback_html(), reporter.get_traceback_text())
    for report in reports:
        assert RESET_TOKEN not in report
        assert "visible-target" in report


@override_settings(DEBUG=False, ADMINS=[("ops", "ops@example.net")])
def test_password_reset_link_error_mail_hides_the_token(mailoutbox):
    caches["error_emails"].clear()
    client = Client(raise_request_exception=False)
    with mock.patch("peeringdb_server.views.UserPasswordReset", BrokenPasswordReset):
        response = client.get("/reset-password", {"token": RESET_TOKEN, "target": "1"})
    assert response.status_code == 500
    assert len(mailoutbox) == 1
    report = mailoutbox[0].body + "".join(
        content for content, _ in mailoutbox[0].alternatives
    )
    assert "Internal Server Error: /reset-password" in mailoutbox[0].subject
    assert RESET_TOKEN not in report


@override_settings(DEBUG=True)
def test_error_report_is_unfiltered_in_debug():
    request = RequestFactory().post("/any", {"password": SENSITIVE["password"]})
    assert SENSITIVE["password"] in report_for(request)


@override_settings(DEBUG=False)
def test_error_report_masks_credentials_in_the_referer():
    request = RequestFactory().post(
        "/reset-password",
        {"target": "visible-target"},
        HTTP_REFERER=(
            "https://www.peeringdb.example/reset-password"
            f"?token={RESET_TOKEN}&target=visible-target"
        ),
    )
    try:
        raise RuntimeError("report")
    except RuntimeError:
        reporter = ExceptionReporter(request, *sys.exc_info())
        reports = (reporter.get_traceback_html(), reporter.get_traceback_text())
    for report in reports:
        assert RESET_TOKEN not in report
        assert "https://www.peeringdb.example/reset-password" in report


class BrokenValue:
    def __str__(self):
        raise RuntimeError("render")


@override_settings(DEBUG=False)
def test_error_report_masks_credentials_in_template_contexts():
    def fail():
        Engine().from_string("{{ broken }}").render(
            Context(
                {
                    "token": RESET_TOKEN,
                    "broken": BrokenValue(),
                    "page": "visible-context-page",
                }
            )
        )

    report = report_for(RequestFactory().get("/reset-password"), fail)
    assert RESET_TOKEN not in report
    assert "BrokenValue" in report
    assert "visible-context-page" in report


@override_settings(DEBUG=False)
def test_error_report_masks_keys_beyond_the_depth_limit():
    def fail():
        nested = {"a": {"b": {"c": {"d": {"password": DEEP["password"]}}}}}
        context = Context({"form": {"user": {"info": {"token": DEEP["token"]}}}})
        assert nested and context
        raise RuntimeError("fail")

    report = report_for(RequestFactory().get("/any"), fail)
    assert DEEP["password"] not in report
    assert DEEP["token"] not in report


@override_settings(DEBUG=False)
def test_error_report_with_a_self_referencing_local():
    def fail():
        payload = []
        payload.extend([payload] * 48)
        assert payload
        raise RuntimeError("fail")

    started = time.monotonic()
    report = report_for(RequestFactory().get("/any"), fail)
    assert time.monotonic() - started < 1
    assert "payload" in report


@override_settings(DEBUG=False)
def test_error_report_with_a_temporary_upload_in_a_query_dict():
    def fail():
        data = QueryDict(mutable=True)
        data["token"] = DEEP["upload"]
        data["upload"] = TemporaryUploadedFile("upload.bin", "text/plain", 0, None)
        data["name"] = "visible-upload-name"
        assert data
        raise RuntimeError("fail")

    report = report_for(RequestFactory().get("/any"), fail)
    assert DEEP["upload"] not in report
    assert "visible-upload-name" in report
