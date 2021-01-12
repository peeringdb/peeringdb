import json
import os
from pprint import pprint
import pytest
import reversion
import requests
import jsonschema
import time
import io
import datetime
import ipaddress

from django.test import override_settings
from django.conf import settings

from peeringdb_server.models import (
    Organization,
    Network,
    NetworkIXLan,
    NetworkContact,
    IXLan,
    IXLanPrefix,
    InternetExchange,
    IXFMemberData,
    IXLanIXFMemberImportLog,
    User,
    DeskProTicket,
    IXFImportEmail,
)
from peeringdb_server import ixf
from peeringdb_server.deskpro import FailingMockAPIClient


def test_vlan_sanitize(data_ixf_vlan):
    """
    test that various vlan_list setups are sanitized correctly
    """
    importer = ixf.Importer()
    sanitized = importer.sanitize_vlans(json.loads(data_ixf_vlan.input)["vlan_list"])
    assert sanitized == data_ixf_vlan.expected["vlan_list"]


def test_connections_match(data_ixf_connections_match):
    importer = ixf.Importer()
    cxn_match = importer.connections_match(
        *json.loads(data_ixf_connections_match.input)["connection_list"])
    assert cxn_match == data_ixf_connections_match.expected


def test_match_vlans_across_connections(data_ixf_connections):
    """
    test that various vlan_list setups are sanitized correctly
    """
    importer = ixf.Importer()
    sanitized = importer.match_vlans_across_connections(
        json.loads(data_ixf_connections.input)["connection_list"])
    pprint(sanitized)
    assert sanitized == data_ixf_connections.expected["connection_list"]
