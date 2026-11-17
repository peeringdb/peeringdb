import datetime
import io
import json

import pytest
import requests
import reversion
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db.models.signals import post_save
from django.test import override_settings
from django.utils import timezone

from peeringdb_server import ixf
from peeringdb_server.models import (
    DeskProTicket,
    InternetExchange,
    IXFImportEmail,
    IXFMemberData,
    IXLanIXFMemberImportLog,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
    User,
)

from .util import setup_test_data


def cache_ixf_data(ixlan, url, data):
    cache.set(ixlan.ixf_cache_key, {"url": url, "data": data}, timeout=None)


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
    ixlans = entities_base["ixlan"]
    for ixlan in ixlans:
        ixlan.ixf_ixp_import_enabled = False
        ixlan.ixf_ixp_member_list_url = "http://www.localhost.com"
        importer.update(ixlan, data=None)
        ixlan.ix.request_ixf_import()
        cache_ixf_data(ixlan, "http://www.localhost.com", ixf_import_data)

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
    ixlans = entities_base["ixlan"]
    for ixlan in ixlans:
        ixlan.ixf_ixp_import_enabled = False
        ixlan.ixf_ixp_member_list_url = ""
        importer.update(ixlan, data=None)
        ixlan.ix.request_ixf_import()
        cache_ixf_data(ixlan, "http://www.localhost.com", ixf_import_data)

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
    ixlans = entities_base["ixlan"]
    for ixlan in ixlans:
        ixlan.ixf_ixp_import_enabled = True
        ixlan.ixf_ixp_member_list_url = "http://www.localhost.com"
        importer.update(ixlan, data=None)
        ixlan.ix.request_ixf_import()
        cache_ixf_data(ixlan, "http://www.localhost.com", ixf_import_data)

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


@pytest.mark.django_db
def test_notify_error_different_error_types(entities, capsys, mocker):
    """
    Test that different types of errors are properly handled by notify_error
    and that email notifications are sent appropriately.
    """
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_import_enabled = True
    ixlan.ixf_ixp_member_list_url = "http://www.localhost.com"
    ixlan.save()

    importer = ixf.Importer()
    importer.reset(ixlan=ixlan, save=True)

    email_mock = mocker.patch.object(importer, "_email")

    string_error = "Invalid JSON format"
    importer.notify_error(string_error)

    ixlan.refresh_from_db()
    assert ixlan.ixf_ixp_import_error == f"Error: {string_error}"
    assert ixlan.ixf_ixp_import_error_notified is not None

    assert email_mock.call_count == 1
    email_mock.reset_mock()

    importer.notify_error(string_error)

    assert email_mock.call_count == 0
    email_mock.reset_mock()

    throttle_hours = settings.IXF_PARSE_ERROR_NOTIFICATION_PERIOD + 1
    with reversion.create_revision():
        ixlan.ixf_ixp_import_error_notified = timezone.now() - timezone.timedelta(
            hours=throttle_hours
        )
        ixlan.save()

    read_timeout_error = requests.exceptions.ReadTimeout("Connection timed out")
    importer.notify_error(read_timeout_error)
    ixlan.refresh_from_db()

    error_text = ixlan.ixf_ixp_import_error
    assert "ReadTimeout" in error_text or "Connection timed out" in error_text

    assert email_mock.call_count == 1
    email_mock.reset_mock()

    connect_timeout_error = requests.exceptions.ConnectTimeout(
        "Failed to establish connection"
    )
    importer.notify_error(connect_timeout_error)
    ixlan.refresh_from_db()

    error_text = ixlan.ixf_ixp_import_error
    assert (
        "ConnectTimeout" in error_text or "Failed to establish connection" in error_text
    )

    assert email_mock.call_count == 1
    email_mock.reset_mock()

    ssl_error = requests.exceptions.SSLError("SSL Certificate verification failed")
    importer.notify_error(ssl_error)
    ixlan.refresh_from_db()

    error_text = ixlan.ixf_ixp_import_error
    assert (
        "SSLError" in error_text or "SSL Certificate verification failed" in error_text
    )

    assert email_mock.call_count == 1


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
        User.objects.create_user(
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
        User.objects.create_user(
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


@pytest.mark.django_db
def test_import_failure_recorded_on_ixlan(entities, mocker):
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_member_list_url = "https://ixf.example/feed.json"
    ixlan.ixf_ixp_import_enabled = True
    ixlan.save()

    mocker.patch.object(ixf.Importer, "update", side_effect=RuntimeError("boom"))

    with pytest.raises(SystemExit):
        call_command("pdb_ixf_ixp_member_import", commit=True, ixlan=[ixlan.id])

    ixlan.refresh_from_db()
    assert ixlan.ixf_ixp_import_error == (
        "Error: The import failed with an internal error"
    )


@pytest.mark.django_db
def test_import_failure_not_recorded_without_commit(entities, mocker):
    ixlan = entities["ixlan"]
    ixlan.ixf_ixp_member_list_url = "https://ixf.example/feed.json"
    ixlan.ixf_ixp_import_enabled = True
    ixlan.save()

    mocker.patch.object(ixf.Importer, "update", side_effect=RuntimeError("boom"))

    with pytest.raises(SystemExit):
        call_command("pdb_ixf_ixp_member_import", ixlan=[ixlan.id])

    ixlan.refresh_from_db()
    assert not ixlan.ixf_ixp_import_error


def ixf_feed(*members):
    """
    IX-F member export with one connection per (asn, ipv4, ipv6) member.
    """
    data = setup_test_data("ixf.member.0")
    template = data["member_list"][0]
    data["member_list"] = []
    for asn, ipaddr4, ipaddr6 in members:
        member = json.loads(json.dumps(template))
        member["asnum"] = asn
        vlan = member["connection_list"][0]["vlan_list"][0]
        vlan["ipv4"]["address"] = ipaddr4
        vlan["ipv6"]["address"] = ipaddr6
        data["member_list"].append(member)
    return data


def run_import(ixlan):
    out = io.StringIO()
    call_command(
        "pdb_ixf_ixp_member_import",
        commit=True,
        cache=True,
        ixlan=[ixlan.id],
        stdout=out,
    )
    return out.getvalue()


@pytest.fixture
def import_ixlan(entities_base):
    ixlan = entities_base["ixlan"][0]
    ixlan.ixf_ixp_member_list_url = "https://ixf.example/feed.json"
    ixlan.ixf_ixp_import_enabled = True
    ixlan.save()
    return ixlan


@pytest.mark.django_db
def test_import_error_after_saves_keeps_changes(entities_base, import_ixlan, mocker):
    """
    The netixlan changes commit on their own (#2071). An error in the work
    after them leaves them in place, marks the ixlan and fails the command,
    and the next run completes.
    """
    ixlan = import_ixlan
    net = entities_base["net"]["UPDATE_ENABLED"]
    cache_ixf_data(
        ixlan,
        ixlan.ixf_ixp_member_list_url,
        ixf_feed((net.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")),
    )

    cleanup = mocker.patch.object(
        ixf.Importer,
        "cleanup_ixf_member_data",
        side_effect=RuntimeError("cleanup failed"),
    )

    with pytest.raises(SystemExit) as exc:
        run_import(ixlan)
    assert exc.value.code == 1

    netixlan = NetworkIXLan.objects.get(ixlan=ixlan, asn=net.asn)
    assert netixlan.status == "ok"
    assert str(netixlan.ipaddr4) == "195.69.147.250"

    ixlan.refresh_from_db()
    assert ixlan.ixf_ixp_import_error == ixf.INTERNAL_ERROR

    mocker.stop(cleanup)
    out = run_import(ixlan)
    assert "Errors:" not in out

    ixlan.refresh_from_db()
    assert not ixlan.ixf_ixp_import_error
    assert NetworkIXLan.objects.filter(ixlan=ixlan, asn=net.asn).count() == 1


@pytest.mark.django_db
def test_import_error_after_saves_still_notifies(entities_base, import_ixlan, mocker):
    """
    A proposal saved before the error is not proposed again by the next run,
    so the failed run still sends its notification, and only once (#2071).
    """
    ixlan = import_ixlan
    net = entities_base["net"]["UPDATE_DISABLED"]
    cache_ixf_data(
        ixlan,
        ixlan.ixf_ixp_member_list_url,
        ixf_feed((net.asn, "195.69.147.251", "2001:7f8:1::a500:1001:1")),
    )

    cleanup = mocker.patch.object(
        ixf.Importer,
        "cleanup_ixf_member_data",
        side_effect=RuntimeError("cleanup failed"),
    )

    with pytest.raises(SystemExit):
        run_import(ixlan)

    assert IXFMemberData.objects.filter(ixlan=ixlan, asn=net.asn).count() == 1
    assert not NetworkIXLan.objects.filter(ixlan=ixlan, asn=net.asn).exists()
    assert IXFImportEmail.objects.filter(net=net).count() == 1

    mocker.stop(cleanup)
    run_import(ixlan)

    assert IXFMemberData.objects.filter(ixlan=ixlan, asn=net.asn).count() == 1
    assert IXFImportEmail.objects.filter(net=net).count() == 1


@pytest.mark.django_db
def test_import_error_during_saves_rolls_back(entities_base, import_ixlan, mocker):
    """
    An error while the netixlan changes are written rolls all of them back
    and drops their notifications. The next run proposes and notifies again.
    Notifications queued before the write block, like a protocol conflict
    found while parsing, are still sent, and only once.
    """
    ixlan = import_ixlan
    org = entities_base["org"][0]
    enabled = entities_base["net"]["UPDATE_ENABLED"]
    disabled = entities_base["net"]["UPDATE_DISABLED"]
    other_enabled = Network.objects.create(
        name="Second network w allow ixp update enabled",
        org=org,
        asn=1301,
        allow_ixp_update=True,
        status="ok",
        info_unicast=True,
        info_ipv6=True,
    )
    ipv6_only = Network.objects.create(
        name="Network w IPv6 only",
        org=org,
        asn=1401,
        allow_ixp_update=False,
        status="ok",
        info_unicast=False,
        info_ipv6=True,
    )
    cache_ixf_data(
        ixlan,
        ixlan.ixf_ixp_member_list_url,
        ixf_feed(
            (disabled.asn, "195.69.147.251", "2001:7f8:1::a500:1001:1"),
            (other_enabled.asn, "195.69.147.252", "2001:7f8:1::a500:1301:1"),
            (ipv6_only.asn, "195.69.147.253", "2001:7f8:1::a500:1401:1"),
            (enabled.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1"),
        ),
    )

    def protocol_conflict_emails():
        return IXFImportEmail.objects.filter(
            ix=ixlan.ix, message__contains="IPv4 support disabled"
        ).count()

    apply_add = ixf.Importer.apply_add
    at_failure = {}

    def fail_on_enabled(importer, ixf_member_data):
        if ixf_member_data.asn == enabled.asn:
            # the command catches anything raised here, so this is
            # checked after the run
            at_failure["queued"] = [
                n["ixf_member_data"].asn for n in importer.notifications
            ]
            at_failure["written"] = NetworkIXLan.objects.filter(
                ixlan=ixlan, asn=other_enabled.asn
            ).exists()
            raise RuntimeError("save failed")
        return apply_add(importer, ixf_member_data)

    failing = mocker.patch.object(
        ixf.Importer, "apply_add", autospec=True, side_effect=fail_on_enabled
    )

    with pytest.raises(SystemExit):
        run_import(ixlan)

    # the write block had queued a notification and written a netixlan
    # before it failed, both went with the rollback
    assert disabled.asn in at_failure["queued"]
    assert at_failure["written"]

    assert not IXFMemberData.objects.filter(ixlan=ixlan, asn=disabled.asn).exists()
    assert not NetworkIXLan.objects.filter(ixlan=ixlan).exists()
    assert not IXFImportEmail.objects.filter(net=disabled).exists()
    assert protocol_conflict_emails() == 1

    mocker.stop(failing)
    run_import(ixlan)

    assert IXFMemberData.objects.filter(ixlan=ixlan, asn=disabled.asn).count() == 1
    assert NetworkIXLan.objects.filter(ixlan=ixlan, asn=enabled.asn).count() == 1
    assert NetworkIXLan.objects.filter(ixlan=ixlan, asn=other_enabled.asn).count() == 1
    assert IXFImportEmail.objects.filter(net=disabled).count() == 1
    assert protocol_conflict_emails() == 1


@pytest.mark.django_db
def test_stale_cleanup_leaves_other_ixlans_alone(entities_base, import_ixlan):
    """
    Stale netixlan notices and removals only act on the delete proposals
    the import refreshed. Another ixlan's aged delete proposal, refreshed by
    an import of that ixlan running at the same time, is left to that
    import (#2071).
    """
    other_ixlan = entities_base["ixlan"][1]
    other_ixlan.ixf_ixp_member_list_url = "https://ixf.example/other.json"
    other_ixlan.ixf_ixp_import_enabled = True
    other_ixlan.save()
    net = entities_base["net"]["UPDATE_DISABLED"]
    enabled = entities_base["net"]["UPDATE_ENABLED"]

    aged = datetime.timedelta(
        days=max(
            settings.IXF_REMOVE_STALE_NETIXLAN_PERIOD,
            settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD,
        )
        + 1
    )
    # fetched after this import starts, as a concurrent import would
    refreshed = timezone.now() + datetime.timedelta(hours=1)

    proposals = {}
    for name, ipaddr4, ipaddr6, notified in (
        (
            "removal",
            "195.66.224.10",
            "2001:7f8:4::a500:1001:1",
            settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT,
        ),
        ("notice", "195.66.224.11", "2001:7f8:4::a500:1001:2", 0),
    ):
        netixlan = NetworkIXLan.objects.create(
            network=net,
            ixlan=other_ixlan,
            asn=net.asn,
            speed=10000,
            ipaddr4=ipaddr4,
            ipaddr6=ipaddr6,
            status="ok",
        )
        ixm = IXFMemberData.objects.create(
            asn=net.asn,
            ipaddr4=ipaddr4,
            ipaddr6=ipaddr6,
            ixlan=other_ixlan,
            speed=10000,
            operational=True,
            is_rs_peer=False,
            status="ok",
            data="{}",
            fetched=refreshed,
            extra_notifications_net_num=notified,
        )
        IXFMemberData.objects.filter(id=ixm.id).update(created=timezone.now() - aged)
        ixm.refresh_from_db()
        assert ixm.action == "delete"
        proposals[name] = (ixm, netixlan)

    cache_ixf_data(
        import_ixlan,
        import_ixlan.ixf_ixp_member_list_url,
        ixf_feed((enabled.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")),
    )
    run_import(import_ixlan)

    removal, netixlan = proposals["removal"]
    netixlan.refresh_from_db()
    assert netixlan.status == "ok"
    assert IXFMemberData.objects.filter(id=removal.id).exists()

    notice, _ = proposals["notice"]
    notice.refresh_from_db()
    assert notice.extra_notifications_net_num == 0
    assert not IXFImportEmail.objects.filter(net=net).exists()


@pytest.mark.django_db
def test_stale_cleanup_follows_moved_netixlan(entities_base, import_ixlan):
    """
    A delete proposal keeps the ixlan it was filed under when its netixlan
    moves to another exchange. The import of the exchange the netixlan is on
    now still sends its stale notices and removes it (#2071).
    """
    old_ixlan = entities_base["ixlan"][1]
    net = entities_base["net"]["UPDATE_DISABLED"]
    enabled = entities_base["net"]["UPDATE_ENABLED"]

    aged = datetime.timedelta(
        days=max(
            settings.IXF_REMOVE_STALE_NETIXLAN_PERIOD,
            settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD,
        )
        + 1
    )

    proposals = {}
    for name, ipaddr4, ipaddr6, notified in (
        (
            "removal",
            "195.69.146.10",
            "2001:7f8:1::a500:1001:10",
            settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT,
        ),
        ("notice", "195.69.146.11", "2001:7f8:1::a500:1001:11", 0),
    ):
        # the netixlan is on the importing exchange now, its proposal was
        # filed while it was on the other one
        netixlan = NetworkIXLan.objects.create(
            network=net,
            ixlan=import_ixlan,
            asn=net.asn,
            speed=10000,
            ipaddr4=ipaddr4,
            ipaddr6=ipaddr6,
            status="ok",
        )
        ixm = IXFMemberData.objects.create(
            asn=net.asn,
            ipaddr4=ipaddr4,
            ipaddr6=ipaddr6,
            ixlan=old_ixlan,
            speed=10000,
            operational=True,
            is_rs_peer=False,
            status="ok",
            data="{}",
            fetched=timezone.now() - aged,
            extra_notifications_net_num=notified,
        )
        IXFMemberData.objects.filter(id=ixm.id).update(created=timezone.now() - aged)
        proposals[name] = (ixm, netixlan)

    cache_ixf_data(
        import_ixlan,
        import_ixlan.ixf_ixp_member_list_url,
        ixf_feed((enabled.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")),
    )
    run_import(import_ixlan)

    removal, netixlan = proposals["removal"]
    netixlan.refresh_from_db()
    assert netixlan.status == "deleted"
    assert not IXFMemberData.objects.filter(id=removal.id).exists()

    notice, _ = proposals["notice"]
    notice.refresh_from_db()
    assert notice.extra_notifications_net_num == 1
    assert IXFImportEmail.objects.filter(net=net).count() == 1


@pytest.fixture
def netixlan_saves():
    """
    The `updated` value of each netixlan save made while the test runs,
    by netixlan id.
    """
    saves = {}

    def record(sender, instance, **kwargs):
        saves.setdefault(instance.id, []).append(instance.updated)

    post_save.connect(
        record, sender=NetworkIXLan, weak=False, dispatch_uid="test_netixlan_saves"
    )
    yield saves
    post_save.disconnect(sender=NetworkIXLan, dispatch_uid="test_netixlan_saves")


def restamp_fixture(entities_base, ixlan):
    """
    An update-enabled network with a netixlan the feed modifies and one it
    no longer lists, and a second one the feed adds.
    """
    enabled = entities_base["net"]["UPDATE_ENABLED"]
    added_net = Network.objects.create(
        name="Second network w allow ixp update enabled",
        org=entities_base["org"][0],
        asn=1301,
        allow_ixp_update=True,
        status="ok",
        info_unicast=True,
        info_ipv6=True,
    )
    with reversion.create_revision():
        modified = NetworkIXLan.objects.create(
            network=enabled,
            ixlan=ixlan,
            asn=enabled.asn,
            speed=1000,
            ipaddr4="195.69.147.250",
            ipaddr6="2001:7f8:1::a500:2906:1",
            is_rs_peer=True,
            status="ok",
        )
        deleted = NetworkIXLan.objects.create(
            network=enabled,
            ixlan=ixlan,
            asn=enabled.asn,
            speed=10000,
            ipaddr4="195.69.146.20",
            ipaddr6="2001:7f8:1::a500:2906:20",
            is_rs_peer=True,
            status="ok",
        )
    cache_ixf_data(
        ixlan,
        ixlan.ixf_ixp_member_list_url,
        ixf_feed(
            (enabled.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1"),
            (added_net.asn, "195.69.147.252", "2001:7f8:1::a500:1301:1"),
        ),
    )
    return modified, deleted, added_net


@pytest.mark.django_db
def test_import_restamps_netixlans_at_end_of_writes(
    entities_base, import_ixlan, netixlan_saves, mocker
):
    """
    Every netixlan the import adds, modifies or deletes carries one updated
    stamp, taken after the last of them was saved, so a `?since=` poll made
    while the writes are still open cannot miss them (#2071). The revisions
    keep the stamps of the saves, and the import log still rolls back.
    """
    ixlan = import_ixlan
    modified, deleted, added_net = restamp_fixture(entities_base, ixlan)
    netixlan_saves.clear()

    archive = ixf.Importer.archive
    in_memory = {}

    def record_archive(importer):
        # what archive() and the steps after it see on the instances
        for action in ("add", "modify", "delete"):
            for info in importer.actions_taken[action]:
                in_memory[info["netixlan"].id] = info["netixlan"].updated
        return archive(importer)

    mocker.patch.object(
        ixf.Importer, "archive", autospec=True, side_effect=record_archive
    )

    run_import(ixlan)

    added = NetworkIXLan.objects.get(ixlan=ixlan, asn=added_net.asn)
    touched = {modified.id, deleted.id, added.id}
    assert touched <= set(netixlan_saves)

    rows = NetworkIXLan.objects.filter(id__in=netixlan_saves)
    stamps = set(rows.values_list("updated", flat=True))
    assert len(stamps) == 1
    stamp = stamps.pop()
    assert stamp >= max(max(saved) for saved in netixlan_saves.values())
    assert in_memory == {pk: stamp for pk in touched}

    modified.refresh_from_db()
    deleted.refresh_from_db()
    assert modified.speed == 10000
    assert deleted.status == "deleted"

    version = reversion.models.Version.objects.get_for_object(modified).first()
    assert version.field_dict["speed"] == 10000
    assert version.field_dict["updated"] < stamp

    import_log = IXLanIXFMemberImportLog.objects.filter(ixlan=ixlan).latest("id")
    assert set(import_log.entries.values_list("netixlan_id", flat=True)) == touched
    import_log.rollback()

    modified.refresh_from_db()
    deleted.refresh_from_db()
    added.refresh_from_db()
    assert modified.speed == 1000
    assert deleted.status == "ok"
    assert added.status == "deleted"


@pytest.mark.django_db
def test_import_rollback_leaves_no_restamp(
    entities_base, import_ixlan, netixlan_saves, mocker
):
    """
    An error in the write block rolls back the saves made before it, and
    nothing re-stamps them: the netixlans keep the stamps they had (#2071).

    A guard: it passes on code without a re-stamp, and fails if the re-stamp
    also runs when the write block fails, e.g. from a finally.
    """
    ixlan = import_ixlan
    modified, deleted, added_net = restamp_fixture(entities_base, ixlan)
    before = {
        row.id: row.updated
        for row in NetworkIXLan.objects.filter(id__in=[modified.id, deleted.id])
    }
    netixlan_saves.clear()

    apply_add = ixf.Importer.apply_add

    def fail_on_add(importer, ixf_member_data):
        if ixf_member_data.asn == added_net.asn:
            raise RuntimeError("save failed")
        return apply_add(importer, ixf_member_data)

    mocker.patch.object(
        ixf.Importer, "apply_add", autospec=True, side_effect=fail_on_add
    )
    with pytest.raises(SystemExit):
        run_import(ixlan)

    # both were saved in the block before the error
    assert {modified.id, deleted.id} <= set(netixlan_saves)

    after = {
        row.id: row.updated
        for row in NetworkIXLan.objects.filter(id__in=[modified.id, deleted.id])
    }
    assert after == before
    modified.refresh_from_db()
    assert modified.speed == 1000
    assert not NetworkIXLan.objects.filter(asn=added_net.asn).exists()


@pytest.mark.django_db
def test_import_preview_restamps_nothing(entities_base, import_ixlan, netixlan_saves):
    """
    A run without commit saves no netixlan and changes no stamp (#2071).

    A guard: it passes on code without a re-stamp as well.
    """
    ixlan = import_ixlan
    modified, deleted, added_net = restamp_fixture(entities_base, ixlan)
    before = dict(NetworkIXLan.objects.filter(ixlan=ixlan).values_list("id", "updated"))
    netixlan_saves.clear()

    call_command(
        "pdb_ixf_ixp_member_import", cache=True, ixlan=[ixlan.id], stdout=io.StringIO()
    )

    assert not netixlan_saves
    after = dict(NetworkIXLan.objects.filter(ixlan=ixlan).values_list("id", "updated"))
    assert after == before


def stale_fixture(entities_base, ixlan):
    """
    Two netixlans of the update-disabled network that the import removes as
    stale, and a feed that adds a netixlan for the update-enabled network.
    """
    net = entities_base["net"]["UPDATE_DISABLED"]
    enabled = entities_base["net"]["UPDATE_ENABLED"]

    aged = datetime.timedelta(
        days=max(
            settings.IXF_REMOVE_STALE_NETIXLAN_PERIOD,
            settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD,
        )
        + 1
    )

    stale = []
    for ipaddr4, ipaddr6 in (
        ("195.69.146.30", "2001:7f8:1::a500:1001:30"),
        ("195.69.146.31", "2001:7f8:1::a500:1001:31"),
    ):
        netixlan = NetworkIXLan.objects.create(
            network=net,
            ixlan=ixlan,
            asn=net.asn,
            speed=10000,
            ipaddr4=ipaddr4,
            ipaddr6=ipaddr6,
            status="ok",
        )
        ixm = IXFMemberData.objects.create(
            asn=net.asn,
            ipaddr4=ipaddr4,
            ipaddr6=ipaddr6,
            ixlan=ixlan,
            speed=10000,
            operational=True,
            is_rs_peer=False,
            status="ok",
            data="{}",
            fetched=timezone.now() - aged,
            extra_notifications_net_num=settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT,
        )
        IXFMemberData.objects.filter(id=ixm.id).update(created=timezone.now() - aged)
        stale.append(netixlan.id)

    cache_ixf_data(
        ixlan,
        ixlan.ixf_ixp_member_list_url,
        ixf_feed((enabled.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")),
    )
    return net, enabled, stale


@pytest.mark.django_db
def test_stale_removal_restamps_removed_netixlans(
    entities_base, import_ixlan, netixlan_saves
):
    """
    The netixlans removed as stale in one import share one updated stamp,
    taken after the last of them was deleted, like the netixlans of the
    write block (#2071).
    """
    net, enabled, stale = stale_fixture(entities_base, import_ixlan)
    netixlan_saves.clear()

    run_import(import_ixlan)

    rows = NetworkIXLan.objects.filter(id__in=stale)
    assert set(rows.values_list("status", flat=True)) == {"deleted"}
    stamps = set(rows.values_list("updated", flat=True))
    assert len(stamps) == 1
    assert stamps.pop() >= max(max(netixlan_saves[pk]) for pk in stale)


@pytest.mark.django_db
def test_restamp_sets_network_netixlan_updated(entities_base, import_ixlan):
    """
    A network's netixlan_updated gets the same stamp as the netixlans the
    import wrote or removed as stale. Its updated, poc_updated and
    netfac_updated stay as they were (#2071).
    """
    net, enabled, stale = stale_fixture(entities_base, import_ixlan)
    fields = ("updated", "poc_updated", "netfac_updated")
    before = {
        row["id"]: row
        for row in Network.objects.filter(id__in=[net.id, enabled.id]).values(
            "id", *fields
        )
    }

    run_import(import_ixlan)

    added = NetworkIXLan.objects.get(ixlan=import_ixlan, asn=enabled.asn)
    removed = set(
        NetworkIXLan.objects.filter(id__in=stale).values_list("updated", flat=True)
    )
    assert len(removed) == 1

    enabled.refresh_from_db()
    net.refresh_from_db()
    assert enabled.netixlan_updated == added.updated
    assert net.netixlan_updated == removed.pop()

    after = {
        row["id"]: row
        for row in Network.objects.filter(id__in=[net.id, enabled.id]).values(
            "id", *fields
        )
    }
    assert after == before
