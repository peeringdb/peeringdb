import pytest
import requests
import peeringdb_server.models as models
from django.test import TestCase


def test_requests_ssl():
    r = requests.get("https://www.google.com")
    assert r.status_code == 200
