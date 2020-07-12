import json
import os
from pprint import pprint
import reversion
import requests
import jsonschema
import time
import io
import datetime

from django.db import transaction
from django.core.cache import cache
from django.test import Client, TestCase, RequestFactory
from django.core.management import call_command

from peeringdb_server.models import (
    Organization,
    Network,
    NetworkIXLan,
    IXLan,
    IXLanPrefix,
    InternetExchange,
    IXFMemberData,
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    User,
    DeskProTicket
)
from peeringdb_server import ixf

import pytest


def test_reset_ixf_proposals()
    assert True

def test_dismiss_ixf_proposals()
    assert True

def test_reset_ixf_proposals_no_perm()
    assert True

def test_dismiss_ixf_proposals_no_perm()
    assert True


def admin_user():
    admin_user = models.User.objects.create_user(
        "admin", "admin@localhost", first_name="admin", last_name="admin"
    )
    admin_user.is_superuser = True
    admin_user.is_staff = True
    admin_user.save()
    admin_user.set_password("admin")
    admin_user.save()
    return admin_user

def regular_user():
    user = models.User.objects.create_user(
        "user", "user@localhost", first_name="user", last_name="user"
    )
    user.set_password("user")
    user.save()
    return user

def setup_client(user):
    client = Client()
    client.force_login(user)
    return client

def setup_users():
    pass