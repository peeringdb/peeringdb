import datetime
import io
import json
import time
from pprint import pprint

import jsonschema
import pytest
import requests
import reversion
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings

from peeringdb_server import ixf
from peeringdb_server.models import (
    DeskProTicket,
    InternetExchange,
    IXFImportEmail,
    IXFMemberData,
    IXLan,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
    User,
)

from .util import setup_test_data


@pytest.mark.django_db
def test_import_error_status(entities):
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_member_list_url = "localhost"
    ixlan.ixf_ixp_import_enabled = True
    ixlan.save()

    ixlan.ix.request_ixf_import()

    call_command("pdb_ixf_ixp_member_import", process_requested=0, commit=True)

    ixlan.ix.refresh_from_db()
    # Import will fail. Check if import status is == error
    assert ixlan.ix.ixf_import_request_status == "error"
    assert ixlan.ix.ixf_import_request


@pytest.mark.django_db
def test_import_processed_count(entities_base):
    ixf_import_data = setup_test_data("ixf.member.0")

    importer = ixf.Importer()
    cache.set(
        importer.cache_key("http://www.localhost.com"), ixf_import_data, timeout=None
    )
    ixlans = entities_base["ixlan"]
    for ixlan in ixlans:
        ixlan.ixf_ixp_import_enabled = False
        ixlan.ixf_ixp_member_list_url = "http://www.localhost.com"
        importer.update(ixlan, data=None)
        ixlan.ix.request_ixf_import()

    call_command(
        "pdb_ixf_ixp_member_import", process_requested=1, commit=True, cache=True
    )

    for email in IXFImportEmail.objects.filter(ix=ixlan.ix):
        assert f"Exchange: {ixlan.ix.view_url}" in email.message

    assert (
        InternetExchange.objects.filter(ixf_import_request_status="finished").count()
        == 1
    )


@pytest.mark.django_db
def test_import_not_processed_import_url_empty(entities_base):
    ixf_import_data = setup_test_data("ixf.member.0")

    importer = ixf.Importer()
    cache.set(
        importer.cache_key("http://www.localhost.com"), ixf_import_data, timeout=None
    )
    ixlans = entities_base["ixlan"]
    for ixlan in ixlans:
        ixlan.ixf_ixp_import_enabled = False
        ixlan.ixf_ixp_member_list_url = ""
        importer.update(ixlan, data=None)
        ixlan.ix.request_ixf_import()

    call_command(
        "pdb_ixf_ixp_member_import", process_requested=1, commit=True, cache=True
    )

    assert (
        InternetExchange.objects.filter(ixf_import_request_status="finished").count()
        == 0
    )


@pytest.mark.django_db
def test_ignore_import_enabled(entities_base):
    ixf_import_data = setup_test_data("ixf.member.0")

    importer = ixf.Importer()
    cache.set(
        importer.cache_key("http://www.localhost.com"), ixf_import_data, timeout=None
    )
    ixlans = entities_base["ixlan"]
    for ixlan in ixlans:
        ixlan.ixf_ixp_import_enabled = True
        ixlan.ixf_ixp_member_list_url = "http://www.localhost.com"
        importer.update(ixlan, data=None)
        ixlan.ix.request_ixf_import()

    call_command(
        "pdb_ixf_ixp_member_import", process_requested=0, commit=None, cache=True
    )

    assert (
        InternetExchange.objects.filter(ixf_import_request_status="finished").count()
        == 2
    )


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
def test_runtime_errors(entities, capsys, mocker):
    """
    Test that runtime errors are captured, output
    to stderr, and that the commandline tool exits with
    a status of 1
    """
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_import_enabled = True
    ixlan.ixf_ixp_member_list_url = "http://www.localhost.com"
    ixlan.save()
    asn = entities["net"].asn

    """
    When importer.update() is called within the commandline
    tool, we want to throw an unexpected error.
    """
    mocker.patch(
        "peeringdb_server.management.commands.pdb_ixf_ixp_member_import.ixf.Importer.update",
        side_effect=RuntimeError("Unexpected error"),
    )

    out = io.StringIO()

    with pytest.raises(SystemExit) as pytest_wrapped_exit:
        call_command(
            "pdb_ixf_ixp_member_import",
            skip_import=True,
            commit=True,
            ixlan=[ixlan.id],
            asn=asn,
            stdout=out,
        )

    # Assert we are outputting the exception and traceback to the stderr
    captured = out.getvalue()
    assert "Unexpected error" in captured
    assert str(ixlan.id) in captured
    assert str(ixlan.ix.name) in captured
    assert str(ixlan.ixf_ixp_member_list_url) in captured

    # Assert we are exiting with status code 1
    assert pytest_wrapped_exit.value.code == 1


# Want to test that other uncaught errors also exit with
# exit code 1
@pytest.mark.django_db
def test_runtime_errors_uncaught(entities, capsys, mocker):
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_import_enabled = True
    ixlan.ixf_ixp_member_list_url = "http://www.localhost.com"
    ixlan.save()
    asn = entities["net"].asn

    """
    When importer.notify_proposals() is called within the commandline
    tool, we want to throw an unexpected error. This happens outside
    the error logging.
    """
    mocker.patch(
        "peeringdb_server.management.commands.pdb_ixf_ixp_member_import.ixf.Importer.notify_proposals",
        side_effect=ImportError("Uncaught bug"),
    )

    """
    Here we have to just assert that the commandline tool will raise that error
    itself, as opposed to being wrapped in a system exit
    """
    with pytest.raises(ImportError) as pytest_uncaught_error:
        call_command(
            "pdb_ixf_ixp_member_import",
            skip_import=True,
            commit=True,
            ixlan=[ixlan.id],
            asn=asn,
        )

    # Assert we are outputting the exception and traceback to the stderr
    assert "Uncaught bug" in str(pytest_uncaught_error.value)


# This is the normal test case for resending emails
@pytest.mark.django_db
@override_settings(
    MAIL_DEBUG=False,
    IXF_RESEND_FAILED_EMAILS=True,
    IXF_NOTIFY_NET_ON_CONFLICT=True,
    IXF_NOTIFY_IX_ON_CONFLICT=True,
)
def test_resend_emails(unsent_emails):
    importer = ixf.Importer()
    unsent_email_count = len(unsent_emails)

    assert IXFImportEmail.objects.count() == unsent_email_count
    assert IXFImportEmail.objects.filter(sent__isnull=False).count() == 0

    importer.resend_emails()
    assert (
        IXFImportEmail.objects.filter(sent__isnull=False).count() == unsent_email_count
    )


# MAIL DEBUG must be FALSE to send emails - here they don't send
@pytest.mark.django_db
@override_settings(
    MAIL_DEBUG=True,
    IXF_RESEND_FAILED_EMAILS=True,
    IXF_NOTIFY_NET_ON_CONFLICT=True,
    IXF_NOTIFY_IX_ON_CONFLICT=True,
)
def test_resend_emails_mail_debug(unsent_emails):
    importer = ixf.Importer()
    unsent_email_count = len(unsent_emails)

    assert IXFImportEmail.objects.count() == unsent_email_count
    importer.resend_emails()
    assert IXFImportEmail.objects.filter(sent__isnull=False).count() == 0


# IXF_RESEND_FAILED_EMAILS must be TRUE to send emails - here they don't send
@pytest.mark.django_db
@override_settings(
    IXF_RESEND_FAILED_EMAILS=False,
    MAIL_DEBUG=False,
    IXF_NOTIFY_NET_ON_CONFLICT=True,
    IXF_NOTIFY_IX_ON_CONFLICT=True,
)
def test_resend_emails_resend_mode_off(unsent_emails):
    importer = ixf.Importer()
    unsent_email_count = len(unsent_emails)

    assert IXFImportEmail.objects.count() == unsent_email_count
    importer.resend_emails()
    assert IXFImportEmail.objects.filter(sent__isnull=False).count() == 0


# Here we check that the "stale info" is only ever appended once
@pytest.mark.django_db
@override_settings(
    MAIL_DEBUG=False,
    IXF_RESEND_FAILED_EMAILS=True,
    IXF_NOTIFY_NET_ON_CONFLICT=True,
    IXF_NOTIFY_IX_ON_CONFLICT=True,
)
def test_resend_emails_messages(unsent_emails):
    importer = ixf.Importer()
    unsent_email_count = len(unsent_emails)

    assert IXFImportEmail.objects.count() == unsent_email_count
    assert IXFImportEmail.objects.filter(sent__isnull=False).count() == 0

    importer.resend_emails()
    assert (
        IXFImportEmail.objects.filter(sent__isnull=False).count() == unsent_email_count
    )

    # Check that "stale info" message has been appended
    for email in IXFImportEmail.objects.filter(sent__isnull=False).all():
        assert email.message.startswith(
            "This email could not be delivered initially and may contain stale information"
        )

    # Make it appear if re-send failed
    for email in IXFImportEmail.objects.filter(sent__isnull=False).all():
        email.sent = None
        email.save()

    importer.resend_emails()

    # Check that "stale info" message is not re-appended
    for email in IXFImportEmail.objects.filter(sent__isnull=False).all():
        assert (
            email.message.count(
                "This email could not be delivered initially and may contain stale information"
            )
            == 1
        )


# Now we call the email resending from the commandline
@pytest.mark.django_db
@override_settings(
    MAIL_DEBUG=False,
    IXF_RESEND_FAILED_EMAILS=True,
    IXF_NOTIFY_NET_ON_CONFLICT=True,
    IXF_NOTIFY_IX_ON_CONFLICT=True,
)
def test_cmd_resend_emails(unsent_emails):
    unsent_email_count = len(unsent_emails)

    assert IXFImportEmail.objects.count() == unsent_email_count
    assert IXFImportEmail.objects.filter(sent__isnull=False).count() == 0

    call_command("pdb_ixf_ixp_member_import", commit=True)

    assert (
        IXFImportEmail.objects.filter(sent__isnull=False).count() == unsent_email_count
    )


# Commit mode extends to email resending as well
@pytest.mark.django_db
@override_settings(
    MAIL_DEBUG=False,
    IXF_RESEND_FAILED_EMAILS=True,
    IXF_NOTIFY_NET_ON_CONFLICT=True,
    IXF_NOTIFY_IX_ON_CONFLICT=True,
)
def test_cmd_resend_emails_non_commit(unsent_emails):
    unsent_email_count = len(unsent_emails)

    assert IXFImportEmail.objects.count() == unsent_email_count
    call_command("pdb_ixf_ixp_member_import", commit=False)
    assert IXFImportEmail.objects.filter(sent__isnull=False).count() == 0


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
        entities["netixlan"] = []
        admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        ixf_importer_user = User.objects.create_user(
            "ixf_importer", "ixf_importer@localhost", "ixf_importer"
        )
        entities["org"].admin_usergroup.user_set.add(admin_user)
    return entities


@pytest.fixture
def entities_base():
    entities = {}
    with reversion.create_revision():
        entities["org"] = [Organization.objects.create(name="Netflix", status="ok")]

        # create exchange(s)
        entities["ix"] = [
            InternetExchange.objects.create(
                name="Test Exchange One",
                org=entities["org"][0],
                status="ok",
                tech_email="ix1@localhost",
            ),
            InternetExchange.objects.create(
                name="Test Exchange Two",
                org=entities["org"][0],
                status="ok",
                tech_email="ix2@localhost",
            ),
        ]

        # create ixlan(s)
        entities["ixlan"] = [ix.ixlan for ix in entities["ix"]]

        # create ixlan prefix(s)
        entities["ixpfx"] = [
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][0],
                status="ok",
                prefix="195.69.144.0/22",
                protocol="IPv4",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][0],
                status="ok",
                prefix="2001:7f8:1::/64",
                protocol="IPv6",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][1],
                status="ok",
                prefix="195.66.224.0/22",
                protocol="IPv4",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][1],
                status="ok",
                prefix="2001:7f8:4::/64",
                protocol="IPv6",
            ),
        ]

        # create network(s)
        entities["net"] = {
            "UPDATE_ENABLED": Network.objects.create(
                name="Network w allow ixp update enabled",
                org=entities["org"][0],
                asn=2906,
                info_prefixes4=42,
                info_prefixes6=42,
                website="http://netflix.com/",
                policy_general="Open",
                policy_url="https://www.netflix.com/openconnect/",
                allow_ixp_update=True,
                status="ok",
                irr_as_set="AS-NFLX",
                info_unicast=True,
                info_ipv6=True,
            ),
            "UPDATE_DISABLED": Network.objects.create(
                name="Network w allow ixp update disabled",
                org=entities["org"][0],
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
            ),
            "UPDATE_DISABLED_2": Network.objects.create(
                name="Network w allow ixp update disabled (2)",
                org=entities["org"][0],
                asn=1101,
                allow_ixp_update=False,
                status="ok",
                info_prefixes4=42,
                info_prefixes6=42,
                website="http://netflix.com/",
                policy_general="Open",
                policy_url="https://www.netflix.com/openconnect/",
                info_unicast=True,
                info_ipv6=True,
            ),
        }

        entities["netcontact"] = [
            NetworkContact.objects.create(
                email="network1@localhost",
                network=entities["net"]["UPDATE_ENABLED"],
                status="ok",
                role="Policy",
            ),
            NetworkContact.objects.create(
                email="network2@localhost",
                network=entities["net"]["UPDATE_DISABLED"],
                status="ok",
                role="Policy",
            ),
        ]
        entities["netixlan"] = []
        admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        ixf_importer_user = User.objects.create_user(
            "ixf_importer", "ixf_importer@localhost", "ixf_importer"
        )
        entities["org"][0].admin_usergroup.user_set.add(admin_user)
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
