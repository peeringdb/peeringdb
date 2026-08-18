"""
Tests for the #1973 re-verification state on Network — the fields
pdb_irr_as_set_status writes.

The spec's requirement these guard is "no new API surface": the flag lives
server-side, and its public form arrives later as a registered `net` metadata key
under #1742. So the interesting assertions here are about what is *absent* from
the serializer, not just what is present on the model.
"""

import pytest
from django.core.management import call_command
from django.db import models as django_models

from peeringdb_server.models import (
    IRR_AS_SET_STATUS_GONE,
    IRR_AS_SET_STATUS_MOVED,
    IRR_AS_SET_STATUS_OK,
    IRR_AS_SET_STATUS_UNKNOWN,
    IRR_AS_SET_STATUSES,
    Network,
    Organization,
)
from peeringdb_server.serializers import NetworkSerializer

pytestmark = pytest.mark.django_db

VERIFY_STATE_FIELDS = [
    "irr_as_set_status",
    "irr_as_set_verified",
    "irr_as_set_missing_since",
    "irr_as_set_verify_notified",
]


@pytest.fixture
def net(db):
    org = Organization.objects.create(name="Org", status="ok")
    return Network.objects.create(
        name="Network 1", asn=63311, irr_as_set="RIPE::AS-FOO", status="ok", org=org
    )


def test_verify_state_fields_exist():
    """All four fields the spec's triad calls for are on the concrete model."""
    names = {f.name for f in Network._meta.get_fields()}
    for field in VERIFY_STATE_FIELDS:
        assert field in names


def test_verify_state_defaults_are_empty(net):
    """
    A network created without the checker having run is `unknown` with no
    timestamps — not `ok`. Defaulting to `ok` would let the first run's cursor
    logic treat never-checked rows as verified.
    """
    net.refresh_from_db()
    assert net.irr_as_set_status == IRR_AS_SET_STATUS_UNKNOWN
    assert net.irr_as_set_verified is None
    assert net.irr_as_set_missing_since is None
    assert net.irr_as_set_verify_notified is None


def test_verify_state_absent_from_network_serializer():
    """
    The other half of no-new-API-surface: verification state stays server-side. #1742's metadata key is the
    public form and the checker does not wait for it, so none of these may appear
    in the REST representation.
    """
    fields = NetworkSerializer.Meta.fields
    for field in VERIFY_STATE_FIELDS:
        assert field not in fields

    serializer_fields = NetworkSerializer().get_fields().keys()
    for field in VERIFY_STATE_FIELDS:
        assert field not in serializer_fields


def test_verify_state_fields_not_editable():
    """
    Only pdb_irr_as_set_status writes these. `editable=False` keeps them out of
    ModelForms, so the django admin cannot hand an operator a widget for state
    that is derived from a registry lookup.
    """
    for field in VERIFY_STATE_FIELDS:
        assert Network._meta.get_field(field).editable is False


def test_status_choices_cover_the_four_outcomes():
    """
    The classifier's four outcomes and the field's choices come from one place, so
    a new outcome cannot be introduced without widening the column.
    """
    assert [value for value, _label in IRR_AS_SET_STATUSES] == [
        IRR_AS_SET_STATUS_UNKNOWN,
        IRR_AS_SET_STATUS_OK,
        IRR_AS_SET_STATUS_MOVED,
        IRR_AS_SET_STATUS_GONE,
    ]

    max_length = Network._meta.get_field("irr_as_set_status").max_length
    for value, _label in IRR_AS_SET_STATUSES:
        assert len(value) <= max_length


def test_verify_notified_is_separate_from_the_campaign_cursor(net):
    """
    irr_as_set_notified is the cleanup campaign's cursor. Sharing it
    would make a campaign mail suppress a disappearance notice, so the two must be
    independently settable — the same reason irr_as_set_cap_notified was split out.
    """
    assert Network._meta.get_field(
        "irr_as_set_verify_notified"
    ) is not Network._meta.get_field("irr_as_set_notified")

    Network.objects.filter(pk=net.pk).update(irr_as_set_notified="2026-08-04 00:00:00Z")
    net.refresh_from_db()
    assert net.irr_as_set_notified is not None
    assert net.irr_as_set_verify_notified is None


def test_timestamp_fields_are_nullable_datetimes():
    """
    Nullable rather than defaulted: "never verified" and "not missing" must be
    distinguishable from a real timestamp, and `missing_since` being NULL is what
    the recovery path writes.
    """
    for field in VERIFY_STATE_FIELDS[1:]:
        model_field = Network._meta.get_field(field)
        assert isinstance(model_field, django_models.DateTimeField)
        assert model_field.null is True


def test_no_migration_pending():
    """The four fields ship with their migration."""
    call_command("makemigrations", "peeringdb_server", "--check", "--dry-run")
