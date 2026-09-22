"""
Flat write-only metadata fields and the fold into the `meta` document (#1751).

The dashboard edits flat fields, not JSON documents, so each UI-exposed
metadata key has a flat write-only serializer field. Folding starts from the
object's current document, which is also what makes a partial request safe.
"""

import datetime

import pytest
from rest_framework.exceptions import ValidationError as RestValidationError

from peeringdb_server.models import (
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
)
from peeringdb_server.serializers import NetworkIXLanSerializer, NetworkSerializer

pytestmark = pytest.mark.django_db


def tomorrow():
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


@pytest.fixture
def entities(db):
    org = Organization.objects.create(name="Flat Org", status="ok")
    net = Network.objects.create(name="Flat Net", asn=64511, org=org, status="ok")
    NetworkContact.objects.create(
        network=net,
        role="Technical",
        visible="Public",
        email="flat@localhost",
        status="ok",
    )
    ix = InternetExchange.objects.create(name="Flat IX", org=org, status="ok")
    IXLanPrefix.objects.create(
        ixlan=ix.ixlan, protocol="IPv4", prefix="195.69.148.0/22", status="ok"
    )
    netixlan = NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="ok",
        ipaddr4="195.69.148.10",
    )
    return org, net, ix, netixlan


def netixlan_payload(net, ix, netixlan, **extra):
    return dict(
        {
            "net_id": net.id,
            "ixlan_id": ix.ixlan.id,
            "asn": net.asn,
            "speed": 1000,
            "ipaddr4": str(netixlan.ipaddr4),
            "ipaddr6": "",
        },
        **extra,
    )


# --- net keys ---------------------------------------------------------------
#
# These call validate() directly, as the existing net-serializer tests do:
# is_valid() would drag in AsnRdapValidator, which needs a live request in
# context and an RDAP lookup, and the fold under test happens in validate().


def net_base(net):
    # the shared validate() also enforces website presence
    return {"org": net.org, "website": "https://flat.example.com"}


def test_net_flat_fields_fold_into_meta(entities):
    org, net, ix, netixlan = entities
    data = NetworkSerializer(instance=net).validate(
        dict(net_base(net), rtbh_community="65000:666", preferred_ip_mtu=9000)
    )
    assert data["meta"] == {"rtbh_community": "65000:666", "preferred_ip_mtu": 9000}
    # the flat fields are write-only mirrors -- they must not survive as
    # model attributes
    assert "rtbh_community" not in data
    assert "preferred_ip_mtu" not in data


def test_net_flat_field_is_canonicalized_by_the_registry(entities):
    org, net, ix, netixlan = entities
    data = NetworkSerializer(instance=net).validate(
        dict(net_base(net), rtbh_community=" 065000:0666 ")
    )
    assert data["meta"]["rtbh_community"] == "65000:666"


def test_net_flat_field_write_preserves_the_other_keys(entities):
    # the review finding: a payload naming one key must not clear the rest
    org, net, ix, netixlan = entities
    net.meta = {"preferred_ip_mtu": 9000}
    net.save()

    data = NetworkSerializer(instance=net).validate(
        dict(net_base(net), rtbh_community="65000:666")
    )
    assert data["meta"] == {"preferred_ip_mtu": 9000, "rtbh_community": "65000:666"}


def test_net_flat_field_blank_clears_only_its_own_key(entities):
    org, net, ix, netixlan = entities
    net.meta = {"rtbh_community": "65000:666", "preferred_ip_mtu": 9000}
    net.save()

    data = NetworkSerializer(instance=net).validate(
        dict(net_base(net), rtbh_community="")
    )
    assert data["meta"] == {"preferred_ip_mtu": 9000}


def test_net_flat_field_null_clears_the_integer_key(entities):
    org, net, ix, netixlan = entities
    net.meta = {"rtbh_community": "65000:666", "preferred_ip_mtu": 9000}
    net.save()

    data = NetworkSerializer(instance=net).validate(
        dict(net_base(net), preferred_ip_mtu=None)
    )
    assert data["meta"] == {"rtbh_community": "65000:666"}


def test_net_flat_field_blank_string_clears_the_integer_key(entities):
    """
    The dashboard posts JSON, so an emptied number input arrives as "" --
    the field must read that as "clear", not as an invalid integer, or an
    optional key presents as mandatory in the UI.
    """
    org, net, ix, netixlan = entities
    field = NetworkSerializer(instance=net).fields["preferred_ip_mtu"]
    assert field.run_validation("") is None
    assert field.run_validation(None) is None
    assert field.run_validation("9000") == 9000
    with pytest.raises(RestValidationError):
        field.run_validation("abc")


def test_net_flat_field_invalid_value_is_rejected(entities):
    org, net, ix, netixlan = entities
    with pytest.raises(RestValidationError) as excinfo:
        NetworkSerializer(instance=net).validate(
            dict(net_base(net), rtbh_community="rt:65000:666")
        )
    assert "meta" in excinfo.value.detail


def test_explicit_meta_in_the_same_payload_is_the_fold_base(entities):
    # an explicit document in the payload wins over the instance's, and the
    # flat field is applied on top of it
    org, net, ix, netixlan = entities
    net.meta = {"preferred_ip_mtu": 1500}
    net.save()

    data = NetworkSerializer(instance=net).validate(
        dict(net_base(net), meta={"preferred_ip_mtu": 9000}, rtbh_community="65000:666")
    )
    assert data["meta"] == {"preferred_ip_mtu": 9000, "rtbh_community": "65000:666"}


def test_net_meta_untouched_when_no_flat_field_is_submitted(entities):
    org, net, ix, netixlan = entities
    net.meta = {"rtbh_community": "65000:666"}
    net.save()

    data = NetworkSerializer(instance=net).validate(net_base(net))
    assert "meta" not in data


# --- netixlan keys, including the multi-part one ---------------------------


def test_netixlan_multipart_key_folds_from_two_flat_fields(entities):
    org, net, ix, netixlan = entities
    date = tomorrow()
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=netixlan_payload(
            net,
            ix,
            netixlan,
            planned_status_change_status="deleted",
            planned_status_change_date=date,
        ),
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"] == {
        "planned_status_change": {"status": "deleted", "date": date}
    }


def test_netixlan_multipart_key_merges_with_the_existing_half(entities):
    org, net, ix, netixlan = entities
    date = tomorrow()
    netixlan.meta = {"planned_status_change": {"status": "ok", "date": date}}
    netixlan.save()

    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=netixlan_payload(
            net, ix, netixlan, planned_status_change_status="deleted"
        ),
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"]["planned_status_change"] == {
        "status": "deleted",
        "date": date,
    }


def test_netixlan_multipart_key_cleared_removes_the_whole_object(entities):
    org, net, ix, netixlan = entities
    netixlan.meta = {
        "planned_status_change": {"status": "deleted", "date": tomorrow()},
        "rfc8950": True,
    }
    netixlan.save()

    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=netixlan_payload(
            net,
            ix,
            netixlan,
            planned_status_change_status="",
            planned_status_change_date="",
        ),
    )
    assert serializer.is_valid(), serializer.errors
    # the enclosing object goes with its last part, and the unrelated key stays
    assert serializer.validated_data["meta"] == {"rfc8950": True}


def test_netixlan_boolean_flat_field_can_be_set_false(entities):
    # False is a meaningful value, not an absence -- it must land in the
    # document rather than clearing the key
    org, net, ix, netixlan = entities
    netixlan.meta = {"rfc8950": True}
    netixlan.save()

    serializer = NetworkIXLanSerializer(
        instance=netixlan, data=netixlan_payload(net, ix, netixlan, rfc8950=False)
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"] == {"rfc8950": False}


def test_netixlan_boolean_flat_field_is_tri_state(entities):
    """
    `rfc8950` has to be clearable, and its clear value has to be what an
    untouched widget submits.

    The dashboard exports every field in a netixlan row as soon as any one
    of them changes, so a flat boolean that could only submit true/false
    would stamp an explicit `false` onto a connection whose owner never made
    an RFC8950 statement -- destroying the false-vs-unset distinction the
    generated column exists to preserve, and falsifying the documented
    `?meta__rfc8950=false` query. Hence null clears, and the widget is a
    tri-state select rather than a checkbox.
    """
    org, net, ix, netixlan = entities
    netixlan.meta = {"rfc8950": True}
    netixlan.save()

    # null removes the key
    serializer = NetworkIXLanSerializer(
        instance=netixlan, data=netixlan_payload(net, ix, netixlan, rfc8950=None)
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"] == {}

    # blank -- what the select's "Not Disclosed" option submits -- does too
    serializer = NetworkIXLanSerializer(
        instance=netixlan, data=netixlan_payload(net, ix, netixlan, rfc8950="")
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"] == {}

    # and an unrelated edit of the row does not invent a value
    netixlan.meta = {}
    netixlan.save()
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=netixlan_payload(net, ix, netixlan, speed=10000, rfc8950=""),
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["meta"] == {}


def test_netixlan_partial_multipart_write_is_rejected(entities):
    # writing only one half leaves an incomplete plan -- reported against
    # the flat field that is missing, not against `meta`, so the dashboard
    # can highlight the input
    org, net, ix, netixlan = entities
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=netixlan_payload(
            net, ix, netixlan, planned_status_change_status="deleted"
        ),
    )
    assert not serializer.is_valid()
    assert "meta" not in serializer.errors
    assert "planned_status_change_date" in serializer.errors
    assert "needs a date" in str(serializer.errors["planned_status_change_date"])


def test_netixlan_date_without_a_change_type_is_rejected_on_the_type(entities):
    org, net, ix, netixlan = entities
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=netixlan_payload(net, ix, netixlan, planned_status_change_date=tomorrow()),
    )
    assert not serializer.is_valid()
    # all incomplete-plan errors land on the date input, the part the
    # user fills in or clears
    assert list(serializer.errors) == ["planned_status_change_date"]
    assert "also set a status" in str(serializer.errors["planned_status_change_date"])


def test_netixlan_clearing_the_type_but_keeping_a_date_points_at_the_date(
    entities,
):
    """
    The dashboard case (#1742): change type set back to None, date left
    behind. The error must land on the date input, with a message that says
    what to do, instead of a registry error on `meta`.
    """
    org, net, ix, netixlan = entities
    date = tomorrow()
    netixlan.meta = {"planned_status_change": {"status": "deleted", "date": date}}
    netixlan.save()

    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=netixlan_payload(
            net,
            ix,
            netixlan,
            planned_status_change_status="",
            planned_status_change_date=date,
        ),
    )
    assert not serializer.is_valid()
    assert list(serializer.errors) == ["planned_status_change_date"]
    assert "Clear this, or also set a status" in str(
        serializer.errors["planned_status_change_date"]
    )


def test_netixlan_type_kept_but_date_cleared_is_rejected_not_dropped(entities):
    """
    Choosing a change type and submitting an empty date must not silently
    drop the plan (the fold used to pop the key when the date cleared,
    after the type had been written).
    """
    org, net, ix, netixlan = entities
    serializer = NetworkIXLanSerializer(
        instance=netixlan,
        data=netixlan_payload(
            net,
            ix,
            netixlan,
            planned_status_change_status="deleted",
            planned_status_change_date="",
        ),
    )
    assert not serializer.is_valid()
    assert list(serializer.errors) == ["planned_status_change_date"]
    assert "needs a date" in str(serializer.errors["planned_status_change_date"])
