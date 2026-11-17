"""
Requests Django refuses for going over its upload limits are answered 400
without spending the admin error-mail budget (#546)
"""

import base64
from datetime import datetime

import pytest
from django.conf import settings
from django.core.cache import caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import path
from django.utils.timezone import make_aware

from mainsite import urls as site_urls

SERVER_ERROR_PATH = "/_test_server_error/"
FORM = "application/x-www-form-urlencoded"
REFUSED = b"<h1>Bad Request (400)</h1>"


def server_error(request):
    raise RuntimeError("unhandled error in a view")


urlpatterns = [path(SERVER_ERROR_PATH.strip("/") + "/", server_error)] + list(
    site_urls.urlpatterns
)
handler400 = site_urls.handler400
handler403 = site_urls.handler403
handler404 = site_urls.handler404

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("upload_limit_settings"),
]


@pytest.fixture
def upload_limit_settings():
    with override_settings(
        ROOT_URLCONF=__name__,
        ADMINS=[("Ops", "ops@localhost")],
    ):
        caches["error_emails"].clear()
        yield


def query_string(fields):
    return "&".join(f"f{i}=1" for i in range(fields))


def form_body(size):
    return "f=" + "x" * (size - 2)


def files(count):
    return {
        "file": [SimpleUploadedFile(f"f{i}.txt", b"") for i in range(count)],
    }


def get_fields(client, fields):
    return client.get(f"/api/fac?{query_string(fields)}")


def post_fields(client, fields):
    return client.post("/account/login/", query_string(fields), content_type=FORM)


def post_body(client, url, size):
    return client.post(url, form_body(size), content_type=FORM)


def post_files(client, count):
    return client.post("/account/login/", files(count))


def over_limit_requests():
    fields = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
    size = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
    count = settings.DATA_UPLOAD_MAX_NUMBER_FILES
    return {
        "query fields": lambda c: get_fields(c, fields + 1),
        "form fields": lambda c: post_fields(c, fields + 1),
        "login body": lambda c: post_body(c, "/account/login/", size + 1),
        "register body": lambda c: post_body(c, "/register", size + 1),
        "api body": lambda c: post_body(c, "/api/fac", size + 1),
        "files": lambda c: post_files(c, count + 1),
    }


@pytest.mark.parametrize("shape", list(over_limit_requests()))
def test_over_limit_request_answers_400_without_mail(shape, mailoutbox):
    client = Client(raise_request_exception=False)
    res = over_limit_requests()[shape](client)
    assert res.status_code == 400
    assert REFUSED in res.content
    assert mailoutbox == []


def test_server_error_after_over_limit_requests_is_mailed(mailoutbox):
    client = Client(raise_request_exception=False)
    for request in over_limit_requests().values():
        assert request(client).status_code == 400

    res = client.get(SERVER_ERROR_PATH)
    assert res.status_code == 500
    assert len(mailoutbox) == 1
    assert SERVER_ERROR_PATH in mailoutbox[0].subject


@pytest.mark.parametrize(
    "shape,status",
    [
        ("query fields", 200),
        ("form fields", 200),
        ("login body", 200),
        # form validation errors, not the refusal
        ("register body", 400),
        ("api body", 400),
        ("files", 200),
    ],
)
def test_requests_at_the_limit_answer_as_before(shape, status, mailoutbox):
    fields = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
    size = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
    count = settings.DATA_UPLOAD_MAX_NUMBER_FILES
    requests = {
        "query fields": lambda c: get_fields(c, fields),
        "form fields": lambda c: post_fields(c, fields),
        "login body": lambda c: post_body(c, "/account/login/", size),
        "register body": lambda c: post_body(c, "/register", size),
        "api body": lambda c: post_body(c, "/api/fac", size),
        "files": lambda c: post_files(c, count),
    }
    client = Client(raise_request_exception=False)
    res = requests[shape](client)
    assert res.status_code == status
    assert REFUSED not in res.content
    assert mailoutbox == []


@override_settings(MFA_FORCE_HARD_START=make_aware(datetime(2000, 1, 1)))
def test_refused_response_over_query_limit_sends_no_mail(mailoutbox):
    """
    A 401/403 answered before anything parsed the query string still reaches
    the negative cache's response handling, which reads it
    """
    auth = base64.b64encode(b"user:password").decode()
    client = Client(raise_request_exception=False)
    res = client.get(
        f"/api/fac?{query_string(settings.DATA_UPLOAD_MAX_NUMBER_FIELDS + 1)}",
        HTTP_AUTHORIZATION=f"Basic {auth}",
    )
    assert res.status_code == 403
    assert mailoutbox == []
