"""
RDAP bootstrap data is read from the local cache file while it is fresh.
"""

import json
import os
import time
from unittest import mock

import pytest
from django.test import override_settings

from peeringdb_server.inet import RdapLookup

pytestmark = pytest.mark.django_db

BOOTSTRAP = {
    "version": "1.0",
    "services": [[["3356"], ["https://rdap.example/"]]],
}
FETCHED = {
    "version": "1.0",
    "services": [[["3356"], ["https://rdap.fetched.example/"]]],
}


@pytest.fixture
def bootstrap_dir(tmp_path):
    with (
        override_settings(RDAP_BOOTSTRAP_CACHE_TTL=25),
        mock.patch("peeringdb_server.settings.RDAP_BOOTSTRAP_DIR", str(tmp_path)),
        mock.patch("peeringdb_server.settings.RDAP_SELF_BOOTSTRAP", True),
    ):
        yield tmp_path


def write_cache(path, data, age_hours=0):
    data_file = path / "asn.json"
    data_file.write_text(json.dumps(data))
    mtime = time.time() - age_hours * 3600
    os.utime(data_file, (mtime, mtime))
    return data_file


def lookup_service(fetch):
    with mock.patch.object(RdapLookup, "fetch_bootstrap_data", fetch):
        return RdapLookup().asn_url(3356)


def test_fresh_cache_is_used(bootstrap_dir):
    write_cache(bootstrap_dir, BOOTSTRAP)
    fetch = mock.Mock(return_value=FETCHED)

    assert lookup_service(fetch) == "https://rdap.example"
    assert lookup_service(fetch) == "https://rdap.example"
    fetch.assert_not_called()


def test_stale_cache_is_refetched_and_replaced(bootstrap_dir):
    data_file = write_cache(bootstrap_dir, BOOTSTRAP, age_hours=26)
    fetch = mock.Mock(return_value=FETCHED)

    assert lookup_service(fetch) == "https://rdap.fetched.example"
    fetch.assert_called_once_with("asn")
    assert json.loads(data_file.read_text()) == FETCHED
    # the replacement is written beside the file and renamed over it
    assert sorted(os.listdir(bootstrap_dir)) == ["asn.json"]
    assert data_file.stat().st_mode & 0o777 == 0o644


def test_unreadable_cache_is_refetched(bootstrap_dir):
    (bootstrap_dir / "asn.json").write_text('{"version": "1.0", "serv')
    fetch = mock.Mock(return_value=FETCHED)

    assert lookup_service(fetch) == "https://rdap.fetched.example"
    fetch.assert_called_once_with("asn")


def test_missing_cache_dir_is_created(bootstrap_dir):
    fetch = mock.Mock(return_value=FETCHED)
    with mock.patch(
        "peeringdb_server.settings.RDAP_BOOTSTRAP_DIR", str(bootstrap_dir / "sub")
    ):
        assert lookup_service(fetch) == "https://rdap.fetched.example"

    assert json.loads((bootstrap_dir / "sub" / "asn.json").read_text()) == FETCHED


def test_failed_write_leaves_cache_intact(bootstrap_dir):
    data_file = write_cache(bootstrap_dir, BOOTSTRAP, age_hours=26)

    with (
        mock.patch.object(RdapLookup, "fetch_bootstrap_data", return_value=FETCHED),
        mock.patch("peeringdb_server.inet.json.dump", side_effect=OSError("full")),
    ):
        assert RdapLookup().asn_url(3356) == "https://rdap.fetched.example"

    assert json.loads(data_file.read_text()) == BOOTSTRAP
    assert sorted(os.listdir(bootstrap_dir)) == ["asn.json"]
