from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone
from rdap.assignment import RIRAssignmentLookup

from peeringdb_server.models import Network, Organization

now = timezone.now()


@pytest.mark.parametrize(
    "network, rdap_rir_status,new_rir_status, new_network_status",
    [
        (
            {
                "name": "test network",
                "rir_status": "ok",
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=100),
            },
            None,
            "missing",
            "ok",
        ),
        (
            {
                "name": "test network",
                "rir_status": "pending",
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=100),
            },
            "assigned",
            "assigned",
            "ok",
        ),
        (
            {
                "name": "test network",
                "rir_status": "reserved",
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=100),
            },
            "reserved",
            "reserved",
            "deleted",
        ),
        (
            {
                "name": "test network",
                "rir_status": None,
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=100),
            },
            "assigned",
            "assigned",
            "ok",
        ),
    ],
)
@pytest.mark.django_db
def test_pdb_rir_status_asn(
    network, rdap_rir_status, new_rir_status, new_network_status
):
    with patch.object(
        RIRAssignmentLookup,
        "load_data",
        side_effect=lambda data_path, cache_days: None,
    ):
        org = Organization.objects.create(name="test org")
        Network.objects.bulk_create(
            [Network(org=org, **network, updated=now, status="ok")]
        )
        net = Network.objects.first()
        with patch.object(
            RIRAssignmentLookup,
            "get_status",
            side_effect=lambda asn: rdap_rir_status,
        ):
            # without commit
            call_command("pdb_rir_status", asn=net.asn)
            assert net.rir_status == network.get("rir_status")
            call_command("pdb_rir_status", asn=net.asn, commit=True)
            net.refresh_from_db()
            if new_network_status == "deleted":
                assert net.status == "deleted"
            else:
                assert net.rir_status == new_rir_status
                assert net.rir_status_updated >= network.get("rir_status_updated")


@pytest.mark.django_db
def test_pdb_rir_status():
    with patch.object(
        RIRAssignmentLookup,
        "load_data",
        side_effect=lambda data_path, cache_days: None,
    ):
        org = Organization.objects.create(name="test org")
        network_list = [
            {
                "rir_status": "reserved",
                "asn": 1231,
                "rir_status_updated": now - timezone.timedelta(days=92),
            },
            {
                "rir_status": "reserved",
                "asn": 1232,
                "rir_status_updated": now - timezone.timedelta(days=91),
            },
            {
                "rir_status": "reserved",
                "asn": 1233,
                "rir_status_updated": now - timezone.timedelta(days=89),
            },
            {
                "rir_status": "reserved",
                "asn": 1234,
                "rir_status_updated": now - timezone.timedelta(days=90),
            },
            {
                "rir_status": "ok",
                "asn": 1235,
                "rir_status_updated": now - timezone.timedelta(days=10),
            },
            {
                "rir_status": None,
                "asn": 1236,
                "rir_status_updated": now - timezone.timedelta(days=100),
            },
            {
                "rir_status": "ok",
                "asn": 1237,
                "rir_status_updated": now - timezone.timedelta(days=120),
            },
        ]

        rdap_rir_list = {
            "1231": "ok",
            "1232": "reserved",
            "1233": "available",
            "1234": "available",
            "1235": "reserved",
            "1236": "assigned",
        }
        with patch.object(
            RIRAssignmentLookup,
            "get_status",
            side_effect=lambda asn: rdap_rir_list.get(str(asn)),
        ):
            Network.objects.bulk_create(
                [
                    Network(
                        org=org, name=f"net-{i}", **network, updated=now, status="ok"
                    )
                    for i, network in enumerate(network_list)
                ]
            )

            # without commit
            call_command("pdb_rir_status")
            assert Network.objects.filter(status="ok").count() == len(network_list)
            assert Network.objects.filter(status="deleted").count() == 0

            call_command("pdb_rir_status", commit=True)
            assert Network.objects.filter(status="deleted").count() == 2
            assert (
                Network.objects.filter(status="ok", rir_status="missing").count() == 1
            )
            assert Network.objects.filter(status="ok").count() == 5
