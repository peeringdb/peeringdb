import json
import os
from pprint import pprint
import reversion
import requests
import jsonschema
import time
import io
import datetime

from django.core.management import call_command

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
    IXFImportEmail
)
from peeringdb_server import ixf
import pytest



@pytest.mark.django_db
def test_reset_hints(entities, data_cmd_ixf_hints):
    ixf_import_data = json.loads(data_cmd_ixf_hints.json)
    importer = ixf.Importer()
    ixlan = entities["ixlan"]
    # Create IXFMemberData
    importer.update(ixlan, data=ixf_import_data)

    call_command("pdb_ixf_ixp_member_import", reset_hints=True)

    assert IXFMemberData.objects.count() == 0
    assert DeskProTicket.objects.filter(body__contains="reset_hints").count() == 1

@pytest.mark.django_db
def test_reset_dismissals(entities, data_cmd_ixf_dismissals):
    ixf_import_data = json.loads(data_cmd_ixf_dismissals.json)
    importer = ixf.Importer()
    ixlan = entities["ixlan"]
    # Create IXFMemberData
    importer.update(ixlan, data=ixf_import_data)

    # Dismiss all IXFMemberData
    for ixfm in IXFMemberData.objects.all():
        ixfm.dismissed = True
        ixfm.save()

    call_command("pdb_ixf_ixp_member_import", reset_dismisses=True)

    assert IXFMemberData.objects.filter(dismissed=False).count() == 4
    assert DeskProTicket.objects.filter(body__contains="reset_dismisses").count() == 1

@pytest.mark.django_db
def test_reset_email(entities, data_cmd_ixf_email):
    ixf_import_data = json.loads(data_cmd_ixf_email.json)
    importer = ixf.Importer()
    ixlan = entities["ixlan"]
    # Create IXFMemberData
    importer.update(ixlan, data=ixf_import_data)

    assert IXFImportEmail.objects.count() == 5
    call_command("pdb_ixf_ixp_member_import", reset_email=True)

    assert IXFImportEmail.objects.count() == 0
    assert DeskProTicket.objects.filter(body__contains="reset_hints").count() == 1

# @pytest.mark.django_db
# def test_reset_tickets(entities, data_cmd_ixf_emails):
#     ixf_import_data = json.loads(data_cmd_ixf_hints.json)
#     importer = ixf.Importer()
#     ixlan = entities["ixlan"]
#     # Create IXFMemberData
#     importer.update(ixlan, data=ixf_import_data)

#     call_command("pdb_ixf_ixp_member_import", reset_hints=True)

#     assert IXFMemberData.objects.count() == 0
#     assert DeskProTicket.objects.filter(body__contains="reset_hints").count() == 1




@pytest.fixture
def entities():
    entities = {}
    with reversion.create_revision():
        entities["org"] = Organization.objects.create(name="Netflix", status="ok")
        entities["ix"] = InternetExchange.objects.create(
                name="Test Exchange One", org=entities["org"], status="ok"
        )
        entities["ixlan"] = entities["ix"].ixlan

        # create ixlan prefix(s)
        entities["ixpfx"] = [
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"],
                status="ok",
                prefix="195.69.144.0/22",
                protocol="IPv4",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"],
                status="ok",
                prefix="2001:7f8:1::/64",
                protocol="IPv6",
            )
        ]
        entities["net"] = Network.objects.create(
                name="Network w allow ixp update disabled",
                org=entities["org"],
                asn=1001,
                allow_ixp_update=False,
                status="ok",
                info_prefixes4=42,
                info_prefixes6=42,
                website="http://netflix.com/",
                policy_general="Open",
                policy_url="https://www.netflix.com/openconnect/",
        )

        entities["netcontact"] = NetworkContact.objects.create(
                email="network1@localhost", network=entities["net"]
            )
        
        admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        ixf_importer_user = User.objects.create_user(
            "ixf_importer", "ixf_importer@localhost", "ixf_importer"
        )
        entities["org"].admin_usergroup.user_set.add(admin_user)
    return entities
