"""
Tests for the irr_as_set verification state on the network web record (#1973,
"verification state is stored on the server (like rir_status), shown on the website
record, and aggregated into PC reports").

The state fields are deliberately absent from NetworkSerializer, so the view has to
read them off the model. That is the thing most likely to break silently — a
`network_d.get(...)` would simply render empty forever — so it is what these tests
pin down.
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from peeringdb_server.models import Network, Organization
from peeringdb_server.views import (
    format_datetime_field,
    format_last_updated_time,
    irr_as_set_status_display,
)
from tests.util import ClientCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def net(db):
    org = Organization.objects.create(name="Org", status="ok")
    return Network.objects.create(
        name="Network 1", asn=63311, irr_as_set="RIPE::AS-FOO", status="ok", org=org
    )


def test_unswept_network_renders_nothing(net):
    """
    Until the cron has run every network is `unknown`. Rendering "Not yet verified"
    on every record would be noise, so the row stays empty.
    """
    assert irr_as_set_status_display(net) == ""


def test_verified_network_shows_the_status_label(net):
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status="ok", irr_as_set_verified=timezone.now()
    )
    net.refresh_from_db()
    assert irr_as_set_status_display(net) == "Verified present"


def test_flagged_network_carries_since_when_inline(net):
    """
    A flagged value needs both "what is wrong" and "since when". Inlining the second
    keeps it to one row on a record that already has many.
    """
    missing = timezone.now() - timedelta(days=30)
    Network.objects.filter(pk=net.pk).update(
        irr_as_set_status="gone", irr_as_set_missing_since=missing
    )
    net.refresh_from_db()

    rendered = irr_as_set_status_display(net)
    assert rendered.startswith("Gone from every registry (since ")
    assert missing.strftime("%Y-%m-%d") in rendered


def test_moved_status_uses_its_own_label(net):
    Network.objects.filter(pk=net.pk).update(irr_as_set_status="moved")
    net.refresh_from_db()
    assert irr_as_set_status_display(net) == "Moved to another registry"


def test_format_datetime_field_handles_a_real_datetime():
    """
    The bug this exists to prevent: format_last_updated_time only handles str and
    None, so handing it a live datetime falls off the end and returns None. These
    fields never pass through the serializer, so they are always datetimes.
    """
    now = timezone.now()
    assert format_last_updated_time(now) is None  # the trap, documented
    assert format_datetime_field(now).endswith("Z")
    assert format_datetime_field(now).startswith(now.strftime("%Y-%m-%dT%H:%M:%S"))


def test_format_datetime_field_handles_none():
    assert format_datetime_field(None) == ""


class TestNetworkRecordDisplay(ClientCase):
    """
    The rendered-request half, and the reason it exists: the value computation above
    is unit-tested, but only a real render proves the view reads `network` rather
    than `network_d`. A `network_d.get("irr_as_set_status")` would pass every unit
    test and render empty forever, because these fields are not in the serializer.

    ClientCase rather than the `client` fixture: view_network runs its output through
    APIPermissionsApplicator, which needs the grainy guest/user groups this base
    creates — without them the whole payload is dismissed and the view 500s on
    `network_d.get("org")`, unrelated to anything here.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org = Organization.objects.create(name="Display Org", status="ok")
        cls.net = Network.objects.create(
            name="Display Net",
            asn=63312,
            irr_as_set="RIPE::AS-FOO",
            status="ok",
            org=cls.org,
        )

    def test_flagged_state_reaches_the_rendered_record(self):
        missing = timezone.now() - timedelta(days=5)
        Network.objects.filter(pk=self.net.pk).update(
            irr_as_set_status="gone", irr_as_set_missing_since=missing
        )

        client = Client()
        client.login(username="guest", password="guest")
        response = client.get(f"/net/{self.net.id}")

        assert response.status_code == 200
        body = response.content.decode()
        assert "IRR AS-SET Status" in body
        assert "IRR AS-SET Verified" in body
        assert "Gone from every registry" in body

    def test_unswept_state_renders_the_rows_empty(self):
        """
        The rows are always present (like the rir_status pair) but say nothing until
        the cron has swept, so an unswept record must not claim a verdict.
        """
        client = Client()
        client.login(username="guest", password="guest")
        response = client.get(f"/net/{self.net.id}")

        body = response.content.decode()
        assert "IRR AS-SET Status" in body
        for verdict in (
            "Verified present",
            "Gone from every registry",
            "Moved to another registry",
            "Not yet verified",
        ):
            assert verdict not in body
