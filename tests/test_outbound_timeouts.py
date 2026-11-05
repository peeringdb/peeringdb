"""
Outbound HTTP calls carry a connect and read timeout.
"""

from unittest import mock

import pytest
import requests
from django.core.management import call_command
from django.test import RequestFactory, override_settings

from peeringdb_server.forms import UserCreationForm
from peeringdb_server.models import User
from peeringdb_server.rest_client import RestClient

pytestmark = pytest.mark.django_db

TIMEOUT = (3, 10)


def _reply(data):
    reply = mock.Mock()
    reply.status_code = 200
    reply.json.return_value = data
    return reply


def test_recaptcha_verification_timeout():
    form = UserCreationForm(
        data={
            "username": "outbound-timeout",
            "email": "outbound-timeout@localhost",
            "first_name": "a",
            "last_name": "b",
            "password1": "Xo8!vhq-2Lp9",
            "password2": "Xo8!vhq-2Lp9",
            "recaptcha": "token",
        }
    )
    form.request = RequestFactory().post("/register")

    with mock.patch(
        "peeringdb_server.forms.requests.post", return_value=_reply({"success": True})
    ) as post:
        form.is_valid()

    assert post.call_count == 1
    assert post.call_args.kwargs["timeout"] == TIMEOUT


def test_translation_timeout(client):
    user = User.objects.create_user("outbound-translate", "t@localhost", "secret-pw-1")
    client.force_login(user)
    reply = _reply({"data": {"translations": [{"translatedText": "x"}]}})

    with mock.patch("peeringdb_server.views.requests.post", return_value=reply) as post:
        client.post("/net/translate", {"note": "x"})

    assert post.call_args.kwargs["timeout"] == TIMEOUT


def test_fetch_api_cache_timeout(tmp_path):
    with (
        override_settings(
            PEERINGDB_SYNC_CACHE_URL="https://cache.example", API_CACHE_ROOT=tmp_path
        ),
        mock.patch(
            "peeringdb_server.management.commands.pdb_fetch_api_cache.requests.get",
            return_value=_reply({"data": []}),
        ) as get,
    ):
        call_command("pdb_fetch_api_cache")

    assert get.call_count > 0
    assert all(call.kwargs["timeout"] == TIMEOUT for call in get.call_args_list)


def test_rest_client_timeout():
    client = RestClient("https://api.example")

    with mock.patch(
        "peeringdb_server.rest_client.requests.request", return_value=_reply({})
    ) as request:
        client._request("net")

    assert request.call_args.kwargs["timeout"] == TIMEOUT


def test_recaptcha_timeout_is_a_form_error():
    form = UserCreationForm(
        data={
            "username": "outbound-timeout",
            "email": "outbound-timeout@localhost",
            "first_name": "a",
            "last_name": "b",
            "password1": "Xo8!vhq-2Lp9",
            "password2": "Xo8!vhq-2Lp9",
            "recaptcha": "token",
        }
    )
    form.request = RequestFactory().post("/register")

    with mock.patch(
        "peeringdb_server.forms.requests.post",
        side_effect=requests.exceptions.ReadTimeout("slow"),
    ):
        assert not form.is_valid()

    assert "reCAPTCHA could not be verified" in str(form.errors)


def test_translation_timeout_is_an_error_reply(client):
    user = User.objects.create_user("outbound-translate", "t@localhost", "secret-pw-1")
    client.force_login(user)

    with mock.patch(
        "peeringdb_server.views.requests.post",
        side_effect=requests.exceptions.ConnectTimeout("slow"),
    ):
        response = client.post("/net/translate", {"note": "x"})

    assert response.status_code == 200
    assert response.json()["error"] == "Translation service unavailable"
