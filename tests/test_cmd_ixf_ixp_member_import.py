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
from django.test import override_settings

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
import pytest


@pytest.mark.django_db
def test_reset_hints(entities, data_cmd_ixf_hints):
    ixf_import_data = json.loads(data_cmd_ixf_hints.json)
    importer = ixf.Importer()
    ixlan = entities["ixlan"]
    # Create IXFMemberData
    importer.update(ixlan, data=ixf_import_data)

    call_command("pdb_ixf_ixp_member_import", reset_hints=True, commit=True)

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

    call_command("pdb_ixf_ixp_member_import", reset_dismisses=True, commit=True)

    assert IXFMemberData.objects.filter(dismissed=False).count() == 4
    assert DeskProTicket.objects.filter(body__contains="reset_dismisses").count() == 1


@pytest.mark.django_db
def test_reset_email(entities, data_cmd_ixf_email):
    ixf_import_data = json.loads(data_cmd_ixf_email.json)
    importer = ixf.Importer()
    ixlan = entities["ixlan"]
    # Create IXFMemberData
    importer.update(ixlan, data=ixf_import_data)
    importer.notify_proposals()
    assert IXFImportEmail.objects.count() == 1

    call_command("pdb_ixf_ixp_member_import", reset_email=True, commit=True)

    assert IXFImportEmail.objects.count() == 0
    assert DeskProTicket.objects.filter(body__contains="reset_email").count() == 1


@pytest.mark.django_db
def test_reset_tickets(deskprotickets):
    assert DeskProTicket.objects.count() == 5

    call_command("pdb_ixf_ixp_member_import", reset_tickets=True, commit=True)

    assert DeskProTicket.objects.count() == 2
    assert DeskProTicket.objects.filter(body__contains="reset_tickets").count() == 1


@pytest.mark.django_db
def test_reset_all(entities, deskprotickets, data_cmd_ixf_reset):
    ixf_import_data = json.loads(data_cmd_ixf_reset.json)
    importer = ixf.Importer()
    ixlan = entities["ixlan"]
    # Create IXFMemberData
    importer.update(ixlan, data=ixf_import_data)
    importer.notify_proposals()

    assert DeskProTicket.objects.count() == 5
    assert IXFMemberData.objects.count() == 4
    assert IXFImportEmail.objects.count() == 1

    call_command("pdb_ixf_ixp_member_import", reset=True, commit=True)

    assert DeskProTicket.objects.count() == 2
    assert DeskProTicket.objects.filter(body__contains="reset").count() == 1
    assert IXFMemberData.objects.count() == 0
    assert IXFImportEmail.objects.count() == 0


@pytest.mark.django_db
@override_settings(MAIL_DEBUG=False)
@override_settings(IXF_NOTIFY_NET_ON_CONFLICT=True)
@override_settings(IXF_NOTIFY_IX_ON_CONFLICT=True)
def test_resend_emails(unsent_emails):
    importer = ixf.Importer()
    unsent_email_count = len(unsent_emails)

    assert IXFImportEmail.objects.count() == unsent_email_count
    assert IXFImportEmail.objects.filter(sent__isnull=False).count() == 0

    importer.resend_emails()
    assert (
        IXFImportEmail.objects.filter(sent__isnull=False).count() == unsent_email_count
    )

@pytest.mark.django_db
@override_settings(MAIL_DEBUG=False)
@override_settings(IXF_NOTIFY_NET_ON_CONFLICT=True)
@override_settings(IXF_NOTIFY_IX_ON_CONFLICT=True)
def test_cmd_resend_emails(unsent_emails):
    unsent_email_count = len(unsent_emails)

    assert IXFImportEmail.objects.count() == unsent_email_count
    assert IXFImportEmail.objects.filter(sent__isnull=False).count() == 0

    call_command("pdb_ixf_ixp_member_import", commit=True)

    assert (
        IXFImportEmail.objects.filter(sent__isnull=False).count() == unsent_email_count
    )


@pytest.fixture
def entities():
    entities = {}
    with reversion.create_revision():
        entities["org"] = Organization.objects.create(name="Netflix", status="ok")
        entities["ix"] = InternetExchange.objects.create(
            name="Test Exchange One",
            org=entities["org"],
            status="ok",
            tech_email="ix1@localhost",
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
            ),
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
            info_unicast=True,
            info_ipv6=True,
        )

        entities["netcontact"] = NetworkContact.objects.create(
            email="network1@localhost",
            network=entities["net"],
            status="ok",
            role="Policy",
        )

        admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        ixf_importer_user = User.objects.create_user(
            "ixf_importer", "ixf_importer@localhost", "ixf_importer"
        )
        entities["org"].admin_usergroup.user_set.add(admin_user)
    return entities


@pytest.fixture
def deskprotickets():
    """
    Creates several deskprotickets. 4 begin with [IX-F], 1 doesn't.
    """
    user, _ = User.objects.get_or_create(username="ixf_importer")
    message = "test"

    subjects = [
        "[IX-F] Suggested:Add Test Exchange One AS1001 195.69.147.250 2001:7f8:1::a500:2906:1",
        "[IX-F] Suggested:Add Test Exchange One AS1001 195.69.148.250 2001:7f8:1::a500:2907:2",
        "[IX-F] Suggested:Add Test Exchange One AS1001 195.69.146.250 2001:7f8:1::a500:2908:2",
        "[IX-F] Suggested:Add Test Exchange One AS1001 195.69.149.250 2001:7f8:1::a500:2909:2",
        "Unrelated Issue: Urgent!!!",
    ]
    for subject in subjects:
        DeskProTicket.objects.create(subject=subject, body=message, user=user)
    return DeskProTicket.objects.all()


@pytest.fixture
def unsent_emails(entities):
    """
    Creates several unsent emails.
    """
    user, _ = User.objects.get_or_create(username="ixf_importer")
    message = "test"
    # This will actually try to send so do not put a real email here.
    recipients = entities["netcontact"].email
    subjects = [
        "[IX-F] Suggested:Add Test Exchange One AS1001 195.69.147.250 2001:7f8:1::a500:2906:1",
        "[IX-F] Suggested:Add Test Exchange One AS1001 195.69.148.250 2001:7f8:1::a500:2907:2",
        "[IX-F] Suggested:Add Test Exchange One AS1001 195.69.146.250 2001:7f8:1::a500:2908:2",
        "[IX-F] Suggested:Add Test Exchange One AS1001 195.69.149.250 2001:7f8:1::a500:2909:2",
    ]

    ix = entities["ix"]
    net = entities["net"]

    emails = []
    for subject in subjects:
        net_email = IXFImportEmail.objects.create(
            subject=subject, message=message, recipients=recipients, sent=None, ix=ix
        )

        ix_email = IXFImportEmail.objects.create(
            subject=subject, message=message, recipients=recipients, sent=None, net=net
        )

        emails.append(ix_email)
        emails.append(net_email)

    return emails
