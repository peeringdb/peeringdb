import pytest
import requests
from django.test import Client, TestCase

import peeringdb_server.models as models
import peeringdb_server.settings as settings
import peeringdb_server.views as views


@pytest.mark.django_db
def test_requests_ssl():
    r = requests.get("https://www.google.com")
    assert r.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "env,result",
    [
        ("beta", True),
        ("dev", False),
        ("prod", False),
    ],
)
def test_beta_banner(env, result):
    _release_env = views.BASE_ENV["RELEASE_ENV"]
    settings.RELEASE_ENV = views.BASE_ENV["RELEASE_ENV"] = env

    client = Client()
    response = client.get("/")

    if result:
        assert "This is a beta/testing instance" in response.content.decode()
    else:
        assert "This is a beta/testing instance" not in response.content.decode()

    settings.RELEASE_ENV = views.BASE_ENV["RELEASE_ENV"] = _release_env


@pytest.mark.django_db
@pytest.mark.parametrize(
    "env,result",
    [
        ("beta", True),
        ("dev", False),
        ("prod", False),
    ],
)
def test_beta_banner_show_prod_sync_warning(env, result):
    _release_env = views.BASE_ENV["RELEASE_ENV"]
    settings.RELEASE_ENV = views.BASE_ENV["RELEASE_ENV"] = env
    views.BASE_ENV["SHOW_AUTO_PROD_SYNC_WARNING"] = True

    client = Client()
    response = client.get("/")

    if result:
        assert (
            "all data will be refreshed from production at" in response.content.decode()
        )
    else:
        assert (
            "all data will be refreshed from production at"
            not in response.content.decode()
        )

    settings.RELEASE_ENV = views.BASE_ENV["RELEASE_ENV"] = _release_env
    views.BASE_ENV["SHOW_AUTO_PROD_SYNC_WARNING"] = False
