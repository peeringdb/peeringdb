"""
Tests for the CSRF failure view (#2032).

With `CSRF_USE_SESSIONS` enabled there is no CSRF cookie, so django's raw
failure reason ("CSRF cookie not set.") sends users chasing a cookie that
was never supposed to exist. The failure view must instead return actionable
copy while keeping the `non_field_errors` wire shape the frontend reads.
"""

import json

import pytest
from django.test import Client, RequestFactory

from peeringdb_server.views import view_http_error_csrf

pytestmark = pytest.mark.django_db

EXPECTED_COPY = "session expired or cookies are blocked"


def test_csrf_failure_returns_actionable_copy():
    # anonymous POST without a token trips the csrf check on /register
    client = Client(enforce_csrf_checks=True)
    response = client.post("/register", {"username": "csrf-test"})

    assert response.status_code == 403
    body = json.loads(response.content)
    assert "non_field_errors" in body
    assert EXPECTED_COPY in body["non_field_errors"][0]


def test_csrf_failure_view_rewords_no_cookie_reason():
    # the misleading no-cookie reason is replaced with actionable copy
    request = RequestFactory().post("/register")
    response = view_http_error_csrf(request, reason="CSRF cookie not set.")

    assert response.status_code == 403
    body = json.loads(response.content)
    assert body["non_field_errors"] == [
        "Your session expired or cookies are blocked; reload and retry."
    ]


def test_csrf_failure_view_keeps_accurate_reasons():
    # other rejection classes (bad origin, referer, token mismatch) are
    # accurate and must pass through untouched — only the misleading
    # no-cookie reason is rewritten
    reason = "Origin checking failed - https://evil.example does not match any trusted origins."
    request = RequestFactory().post("/register")
    response = view_http_error_csrf(request, reason=reason)

    assert response.status_code == 403
    body = json.loads(response.content)
    assert body["non_field_errors"] == [reason]
