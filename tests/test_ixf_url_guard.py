"""
IX-F member list URLs are checked where they are written, the IX-F preview
never fetches them, and a requested import on a LAN with import disabled
only refreshes the cached data.
"""

import json
import socket
from unittest import mock

import pytest
import reversion
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory
from rest_framework.test import APIClient

from peeringdb_server import ixf, ixf_fetch
from peeringdb_server.import_views import view_import_ixlan_ixf_preview
from peeringdb_server.models import (
    InternetExchange,
    IXLan,
    IXLanPrefix,
    NetworkIXLan,
    Organization,
    User,
)
from peeringdb_server.serializers import InternetExchangeSerializer, IXLanSerializer

pytestmark = pytest.mark.django_db

FEED = {
    "version": "1.0",
    "member_list": [
        {
            "asnum": 2906,
            "connection_list": [
                {
                    "state": "active",
                    "if_list": [{"if_speed": 10000}],
                    "vlan_list": [
                        {
                            "vlan_id": 0,
                            "ipv4": {"address": "195.69.147.250"},
                            "ipv6": {"address": "2001:7f8:1::a500:2906:1"},
                        }
                    ],
                }
            ],
        }
    ],
}

INTERNAL_URLS = [
    "http://127.0.0.1:6379/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[fd00:ec2::254]/latest/meta-data/",
    "http://10.0.0.1:9200/_cat/indices",
    "http://user:secret@ixf.example/feed.json",
    "ftp://ixf.example/feed.json",
]


@pytest.fixture
def public_dns(monkeypatch):
    """
    Names under ixf.example resolve to a public address; everything else
    resolves normally.
    """
    real = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if host.endswith("ixf.example"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.43.10", port))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(ixf_fetch.socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def entities():
    User.objects.get_or_create(
        username="ixf_importer", defaults={"email": "ixf_importer@localhost"}
    )
    with reversion.create_revision():
        org = Organization.objects.create(name="Guard Org", status="ok")
        ix = InternetExchange.objects.create(
            name="Guard Exchange", org=org, status="ok", tech_email="ix@guard.example"
        )
        ixlan = ix.ixlan
        ixlan.ixf_ixp_member_list_url = "https://ixf.example/feed.json"
        ixlan.save()
        IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="195.69.144.0/22", protocol="IPv4"
        )
        IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="2001:7f8:1::/64", protocol="IPv6"
        )
    admin = User.objects.create_user("guard-admin", "admin@guard.example", "pw")
    org.admin_usergroup.user_set.add(admin)
    return {"org": org, "ix": ix, "ixlan": ixlan, "admin": admin}


@pytest.mark.parametrize("url", INTERNAL_URLS)
def test_ixlan_serializer_refuses_new_internal_url(entities, public_dns, url):
    serializer = IXLanSerializer(instance=entities["ixlan"])
    with pytest.raises(Exception) as exc:
        serializer.validate_ixf_ixp_member_list_url(url)
    assert "IX-F member list URL" in str(exc.value)


def test_ixlan_serializer_accepts_public_url(entities, public_dns):
    serializer = IXLanSerializer(instance=entities["ixlan"])
    url = "https://feed.ixf.example/members.json"
    assert serializer.validate_ixf_ixp_member_list_url(url) == url


def test_ixlan_serializer_keeps_unchanged_url(entities):
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_member_list_url = "http://127.0.0.1/legacy.json"
    serializer = IXLanSerializer(instance=ixlan)
    # an unchanged value is not looked up again, the fetch checks it
    assert (
        serializer.validate_ixf_ixp_member_list_url("http://127.0.0.1/legacy.json")
        == "http://127.0.0.1/legacy.json"
    )


@pytest.mark.parametrize("url", INTERNAL_URLS)
def test_ix_create_refuses_internal_feed_url(public_dns, url):
    serializer = InternetExchangeSerializer()
    with pytest.raises(Exception) as exc:
        serializer.validate_ixf_ixp_member_list_url(url)
    assert "IX-F member list URL" in str(exc.value)


def test_api_put_ixlan_refuses_internal_url(entities, public_dns):
    client = APIClient()
    client.force_authenticate(entities["admin"])
    ixlan = entities["ixlan"]

    data = client.get(f"/api/ixlan/{ixlan.id}").json()["data"][0]
    data["ixf_ixp_member_list_url"] = "http://169.254.169.254/latest/meta-data/"
    response = client.put(f"/api/ixlan/{ixlan.id}", data, format="json")

    assert response.status_code == 400, response.content
    assert "public addresses" in response.json()["ixf_ixp_member_list_url"][0]
    ixlan.refresh_from_db()
    assert ixlan.ixf_ixp_member_list_url == "https://ixf.example/feed.json"


def preview(entities):
    request = RequestFactory().get(f"/import/ixlan/{entities['ixlan'].id}/ixf/preview")
    request.user = entities["admin"]
    response = view_import_ixlan_ixf_preview(request, entities["ixlan"].id)
    assert response.status_code == 200
    return json.loads(response.content)


@pytest.fixture
def no_fetch(monkeypatch):
    fetch_json = mock.Mock(side_effect=AssertionError("fetched"))
    monkeypatch.setattr(ixf.ixf_fetch, "fetch_json", fetch_json)
    return fetch_json


def test_preview_does_not_fetch(entities, no_fetch, settings):
    settings.RATELIMIT_ENABLE = False
    result = preview(entities)

    no_fetch.assert_not_called()
    assert result["errors"] == [
        "No IX-F data has been fetched for this LAN yet. Request an import to fetch it."
    ]
    assert result["fetched"] is None
    assert result["ix_id"] == entities["ix"].id


def test_preview_shows_cached_data_and_request_status(entities, no_fetch, settings):
    settings.RATELIMIT_ENABLE = False
    ixlan = entities["ixlan"]
    importer = ixf.Importer()
    importer.reset(ixlan=ixlan)
    importer.cache_store(ixlan, ixlan.ixf_ixp_member_list_url, FEED)
    entities["ix"].request_ixf_import(entities["admin"])

    result = preview(entities)

    no_fetch.assert_not_called()
    assert result["fetched"]
    assert result["request_status"] == "queued"
    assert result["errors"] == []


def test_requested_import_on_disabled_lan_only_refreshes(entities, monkeypatch):
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_import_enabled = False
    ixlan.save()
    monkeypatch.setattr(
        ixf.ixf_fetch, "fetch_json", lambda url, **kwargs: json.loads(json.dumps(FEED))
    )
    entities["ix"].request_ixf_import(entities["admin"])

    call_command("pdb_ixf_ixp_member_import", process_requested=0, commit=True)

    entities["ix"].refresh_from_db()
    assert entities["ix"].ixf_import_request_status == "finished"
    assert ixlan.ixf_cached_data["member_list"][0]["asnum"] == 2906
    assert not NetworkIXLan.objects.filter(ixlan=ixlan).exists()


def test_ixlan_clean_refuses_changed_internal_url(entities, public_dns):
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_member_list_url = "http://169.254.169.254/latest/meta-data/"
    with pytest.raises(ValidationError) as exc:
        ixlan.full_clean()
    assert "ixf_ixp_member_list_url" in exc.value.message_dict


def test_ixlan_clean_keeps_unchanged_url(entities):
    ixlan = entities["ixlan"]
    IXLan.objects.filter(id=ixlan.id).update(
        ixf_ixp_member_list_url="http://127.0.0.1/legacy.json"
    )
    ixlan.refresh_from_db()
    ixlan.full_clean()


def test_preview_shows_last_error_and_keeps_it(entities, no_fetch, settings):
    settings.RATELIMIT_ENABLE = False
    ixlan = entities["ixlan"]
    importer = ixf.Importer()
    importer.reset(ixlan=ixlan)
    importer.cache_store(ixlan, ixlan.ixf_ixp_member_list_url, FEED)
    IXLan.objects.filter(id=ixlan.id).update(
        ixf_ixp_import_error="Error: Could not connect to the IX-F member list URL"
    )

    result = preview(entities)

    assert result["errors"][0] == (
        "Last IX-F fetch or import failed: "
        "Error: Could not connect to the IX-F member list URL"
    )
    ixlan.refresh_from_db()
    assert ixlan.ixf_ixp_import_error


def test_refresh_clears_last_error(entities, monkeypatch):
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_import_enabled = False
    ixlan.ixf_ixp_import_error = "Error: Could not connect to the IX-F member list URL"
    ixlan.save()
    monkeypatch.setattr(
        ixf.ixf_fetch, "fetch_json", lambda url, **kwargs: json.loads(json.dumps(FEED))
    )
    entities["ix"].request_ixf_import(entities["admin"])

    call_command("pdb_ixf_ixp_member_import", process_requested=0, commit=True)

    ixlan.refresh_from_db()
    assert not ixlan.ixf_ixp_import_error
