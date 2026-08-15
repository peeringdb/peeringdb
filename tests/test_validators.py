import ipaddress
from datetime import datetime
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.forms import modelform_factory
from django.test import RequestFactory, override_settings
from rest_framework.exceptions import ValidationError as RestValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

import peeringdb_server.geo as geo
from peeringdb_server import irr as irr_module
from peeringdb_server.admin import NetworkAdminForm
from peeringdb_server.context import current_request
from peeringdb_server.inet import IRR_SOURCE
from peeringdb_server.irr_bulk import DUMP_SOURCES
from peeringdb_server.models import (
    Facility,
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
)
from peeringdb_server.serializers import (
    FacilitySerializer,
    InternetExchangeSerializer,
    NetworkIXLanSerializer,
    NetworkSerializer,
)
from peeringdb_server.validators import (
    irr_as_set_pinned_source,
    split_irr_as_set_token,
    tokenize_irr_as_set,
    validate_account_name,
    validate_address_space,
    validate_asn_prefix,
    validate_distance_geocode,
    validate_django_ratelimit_rate,
    validate_info_prefixes4,
    validate_info_prefixes6,
    validate_irr_as_set,
    validate_latitude,
    validate_longitude,
    validate_name,
    validate_phonenumber,
    validate_prefix_overlap,
    validate_social_media,
    validate_status,
    validate_website_override,
)
from tests.test_ixf_member_import_protocol import setup_test_data

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _irr_lookup_exists():
    """
    By default every looked-up object "exists", so the #1973 strict format tests
    are not gated on the live existence check. Tests that exercise the live check
    itself override peeringdb_server.irr.exists_in inline.
    """
    with (
        patch("peeringdb_server.irr.exists_in", return_value=True),
        patch(
            "peeringdb_server.irr.sources_for",
            return_value=irr_module.LookupResult(frozenset(), True),
        ),
    ):
        yield


INVALID_ADDRESS_SPACES = [
    "0.0.0.0/1",
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    # FIXME: this fails still
    # '172.0.0.0/11',
    "172.16.0.0/12",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    # FIXME: this fails still
    # '224.0.0.0/3',
    "224.0.0.0/4",
    "240.0.0.0/4",
    "100.64.0.0/10",
    "0000::/8",
    "0064:ff9b::/96",
    "0100::/8",
    "0200::/7",
    "0400::/6",
    "0800::/5",
    "1000::/4",
    "2001::/33",
    "2001:0:8000::/33",
    "2001:0002::/48",
    "2001:0003::/32",
    "2001:10::/28",
    "2001:20::/28",
    "2001:db8::/32",
    "2002::/16",
    "3ffe::/16",
    "4000::/2",
    "4000::/3",
    "5f00::/8",
    "6000::/3",
    "8000::/3",
    "a000::/3",
    "c000::/3",
    "e000::/4",
    "f000::/5",
    "f800::/6",
    "fc00::/7",
    "fe80::/10",
    "fec0::/10",
    "ff00::/8",
]


@pytest.fixture(params=INVALID_ADDRESS_SPACES)
def prefix(request):
    return request.param


# @pytest.mark.django_db
def test_validate_address_space(prefix):
    """
    Tests peeringdb_server.validators.validate_address_space
    """
    with pytest.raises(ValidationError):
        validate_address_space(ipaddress.ip_network(str(prefix)))


def test_validate_account_name_allows_expected_characters():
    # Basic Latin names
    assert validate_account_name("Alice") == "Alice"
    assert validate_account_name("Jean-Luc") == "Jean-Luc"
    assert validate_account_name("Mary Ann") == "Mary Ann"
    assert validate_account_name("O'Connor") == "O'Connor"
    assert validate_account_name("") == ""
    assert validate_account_name("X") == "X"
    assert validate_account_name(" John") == "John"
    assert validate_account_name("John ") == "John"
    assert validate_account_name("  Mary Ann  ") == "Mary Ann"

    # Native character sets - now allowed
    assert validate_account_name("田中") == "田中"  # Japanese
    assert validate_account_name("김철수") == "김철수"  # Korean
    assert validate_account_name("Müller") == "Müller"  # German
    assert validate_account_name("José") == "José"  # Spanish
    assert validate_account_name("Александр") == "Александр"  # Russian
    assert validate_account_name("محمد") == "محمد"  # Arabic
    assert validate_account_name("王伟") == "王伟"  # Chinese

    # Names with underscores and double spaces are now allowed
    assert validate_account_name("foo_bar") == "foo_bar"
    assert validate_account_name("John  Doe") == "John  Doe"
    assert validate_account_name("- -") == "- -"
    assert validate_account_name("' '") == "' '"


# #1984 - entity name consecutive-whitespace rejection
@pytest.mark.parametrize(
    "value",
    [
        "Foo Bar",
        "Foo-Bar",
        "Foo Bar Baz",
        "Foo\tBar",
        "Foo Bar ",
        " Foo Bar",
        "Foo  ",
        "  Foo",
        "",
        None,
    ],
)
def test_validate_name_allows(value):
    assert validate_name(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "Foo  Bar",
        "Foo   Bar",
        "Foo \t Bar",
        "Foo\t\tBar",
        "Webair Internet  Development",
        "Foo  Bar ",
    ],
)
def test_validate_name_rejects_consecutive_whitespace(value):
    with pytest.raises(ValidationError):
        validate_name(value)


def test_network_serializer_inherits_name_validation():
    assert NetworkSerializer().validate_name("Acme Corp") == "Acme Corp"
    with pytest.raises(ValidationError):
        NetworkSerializer().validate_name("Acme  Corp")


@pytest.mark.parametrize(
    "value",
    [
        "https://www.bing.com/",  # URL
        "Name123",  # digits
        "<script>alert(1)</script>",  # XSS attempt
        "test@example.com",  # email-like
        "path/to/file",  # path
        "hello;world",  # semicolon
        "test|pipe",  # pipe
        "$(command)",  # command injection
        "`backtick`",  # backtick
        'name"quote',  # double quote
        "name{brace}",  # braces
        "name[bracket]",  # brackets
        "hello\\world",  # backslash
        "100%",  # percent
        "a=b",  # equals
        "foo?bar",  # question mark
        "test#hash",  # hash
        "a&b",  # ampersand
        "hello!",  # exclamation
        "a^b",  # caret
        "a~b",  # tilde
        "http://example.com",  # URL with protocol
    ],
)
def test_validate_account_name_rejects_invalid_characters(value):
    with pytest.raises(ValidationError):
        validate_account_name(value)


@override_settings(DATA_QUALITY_MAX_PREFIX_V4_LIMIT=500000)
def test_validate_info_prefixes4():
    """
    Tests peeringdb_server.validators.validate_info_prefixes4
    """
    with pytest.raises(ValidationError):
        validate_info_prefixes4(500001)
    with pytest.raises(ValidationError):
        validate_info_prefixes4(-1)
    validate_info_prefixes4(500000)
    assert validate_info_prefixes4(None) is None
    assert validate_info_prefixes4("") is None


@override_settings(DATA_QUALITY_MAX_PREFIX_V6_LIMIT=500000)
def test_validate_info_prefixes6():
    """
    Tests peeringdb_server.validators.validate_info_prefixes6
    """
    with pytest.raises(ValidationError):
        validate_info_prefixes6(500001)
    with pytest.raises(ValidationError):
        validate_info_prefixes6(-1)
    validate_info_prefixes6(500000)
    assert validate_info_prefixes6(None) is None
    assert validate_info_prefixes6("") is None


@override_settings(
    DATA_QUALITY_MIN_PREFIXLEN_V4=24,
    DATA_QUALITY_MAX_PREFIXLEN_V4=24,
    DATA_QUALITY_MIN_PREFIXLEN_V6=48,
    DATA_QUALITY_MAX_PREFIXLEN_V6=48,
)
def test_validate_prefixlen():
    """
    Tests prefix length limits
    """
    with pytest.raises(ValidationError):
        validate_address_space("37.77.32.0/20")
    with pytest.raises(ValidationError):
        validate_address_space("131.72.77.240/28")
    with pytest.raises(ValidationError):
        validate_address_space("2403:c240::/32")
    with pytest.raises(ValidationError):
        validate_address_space("2001:504:0:2::/64")


@pytest.mark.django_db
def test_validate_prefix_overlap_all_netixlans_covered():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test exchange", status="ok", org=org)
    ixlan = ix.ixlan

    # Existing prefix in ixlan
    IXLanPrefix.objects.create(
        ixlan=ixlan,
        protocol="IPv4",
        prefix=ipaddress.ip_network("1.1.1.0/24"),
        status="ok",
    )

    # No netixlan yet, should allow renumbering
    instance = IXLanPrefix(ixlan=ixlan, protocol="IPv4", prefix="1.1.1.0/24")
    # Should not raise
    validate_prefix_overlap("1.1.1.0/25", instance)

    # Add netixlan with IP in new prefix
    net = Network.objects.create(org=org, name="net", asn=12345, status="ok")
    ixlan.netixlan_set.create(
        network=net,
        asn=net.asn,
        speed=1000,
        ipaddr4="1.1.1.10",
        status="ok",
    )
    # Still covered by new prefix
    validate_prefix_overlap("1.1.1.0/25", instance)


@pytest.mark.django_db
def test_validate_prefix_overlap_not_all_netixlans_covered():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test exchange", status="ok", org=org)
    ixlan = ix.ixlan

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        protocol="IPv4",
        prefix=ipaddress.ip_network("1.1.1.0/24"),
        status="ok",
    )

    instance = IXLanPrefix(ixlan=ixlan, protocol="IPv4", prefix="1.1.1.0/24")
    net = Network.objects.create(org=org, name="net", asn=12345, status="ok")
    ixlan.netixlan_set.create(
        network=net,
        asn=net.asn,
        speed=1000,
        ipaddr4="1.1.1.200",
        status="ok",
    )
    # netixlan IP not covered by new prefix
    with pytest.raises(ValidationError) as excinfo:
        validate_prefix_overlap("1.1.1.0/25", instance)
    assert (
        "Cannot change prefix because at least one peer still uses an IP address in the original block."
        in str(excinfo.value)
    )


@pytest.mark.django_db
def test_validate_prefix_overlap_non_overlapping():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test exchange", status="ok", org=org)
    ixlan = ix.ixlan

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        protocol="IPv4",
        prefix=ipaddress.ip_network("1.1.1.0/24"),
        status="ok",
    )
    instance = IXLanPrefix(ixlan=ixlan, protocol="IPv4", prefix="1.1.1.0/24")
    # Should not raise for non-overlapping prefix
    validate_prefix_overlap("1.1.2.0/24", instance)


@pytest.mark.django_db
def test_validate_prefix_overlap_error():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test exchange", status="ok", org=org)
    ix2 = InternetExchange.objects.create(name="Test exchange2", status="ok", org=org)
    ixlan = ix.ixlan
    ixlan2 = ix2.ixlan

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        protocol="IPv4",
        prefix=ipaddress.ip_network("1.1.1.0/24"),
        status="ok",
    )
    IXLanPrefix.objects.create(
        ixlan=ixlan2,
        protocol="IPv4",
        prefix=ipaddress.ip_network("1.1.2.0/24"),
        status="ok",
    )

    instance = IXLanPrefix(ixlan=ixlan, protocol="IPv4", prefix="1.1.1.0/24")
    # Should raise for overlapping prefix (not subnet case)
    with pytest.raises(ValidationError) as excinfo:
        validate_prefix_overlap("1.1.2.0/25", instance)
    assert "Prefix overlaps with prefix" in str(excinfo.value)


@pytest.mark.parametrize(
    "value,validated",
    [
        # success validation
        ("RIPE::AS-FOO", "RIPE::AS-FOO"),
        ("ripe::as-foo", "RIPE::AS-FOO"),
        (
            "RIPE::AS12345:AS-FOO RIPE::AS12345:AS-FOO:AS9876",
            "RIPE::AS12345:AS-FOO RIPE::AS12345:AS-FOO:AS9876",
        ),
        ("ripe::as-foo:as123:as345", "RIPE::AS-FOO:AS123:AS345"),
        ("RIPE::AS12345", "RIPE::AS12345"),
        ("RIPE::AS123456:RS-FOO", "RIPE::AS123456:RS-FOO"),
        ("as-foo", "AS-FOO"),
        ("rs-foo", "RS-FOO"),
        ("as-foo as-bar", "AS-FOO AS-BAR"),
        ("rs-foo as-bar", "RS-FOO AS-BAR"),
        ("rs-foo rs-bar", "RS-FOO RS-BAR"),
        ("AS15562", "AS15562"),
        ("AS-15562", "AS-15562"),
        ("AS15562 AS33333", "AS15562 AS33333"),
        ("ARIN::AS-RESOUND", "ARIN::AS-RESOUND"),
        # hyphenated source validation
        # we currently do not have valid hyphentated sources in the IRR_SOURCE
        # so this test is commented out
        # ("ARIN-NONAUTH::AS-20C", "ARIN-NONAUTH::AS-20C"),
        # fail validation
        ("AS-Resound Networks,LLC", False),
        # #1973: the unknown-source rule is change-gated, so a legacy value
        # naming a retired (or mistyped) registry still validates non-strict --
        # otherwise retiring a registry would make those networks unsaveable.
        # The prefix is preserved, not silently stripped.
        ("UNKNOWN::AS-FOO", "UNKNOWN::AS-FOO"),
        # postfix @SOURCE notation is no longer supported #1894
        ("AS-FOO@RIPE", False),
        ("AS-FOO-BAR@RIPE", False),
        ("AS12345@RIPE", False),
        ("AS-RESOUND@ARIN", False),
        ("AS-FOO@UNKNOWN", False),
        ("ASFOO@UNKNOWN", False),
        ("UNKNOWN::ASFOO", False),
        ("RIPE:AS-FOO", False),
        ("RIPE::RS15562:RS-FOO", False),
        ("RIPE::AS123456:RS-FOO:AS-FOO", False),
        ('!"*([])?.=+/\\', False),
        ('RIPE::!"*([])?.=+/\\', False),
        ('!"*([])?.=+/\\@RIPE', False),
        # > DATA_QUALITY_MAX_IRR_DEPTH
        ("ripe::as-foo:as123:as345:as678", False),
    ],
)
def test_validate_irr_as_set(value, validated):
    if not validated:
        with pytest.raises(ValidationError):
            validate_irr_as_set(value)
    else:
        assert validate_irr_as_set(value) == validated


@pytest.mark.parametrize(
    "value,validated",
    [
        # every token carries a known SOURCE:: prefix -> accepted
        ("RIPE::AS-FOO", "RIPE::AS-FOO"),
        ("ripe::as-foo", "RIPE::AS-FOO"),
        ("RIPE::AS12345", "RIPE::AS12345"),
        ("RIPE::AS12345:AS-FOO", "RIPE::AS12345:AS-FOO"),
        # missing source prefix -> rejected (#1973)
        ("AS-FOO", False),
        ("as-foo", False),
        # bare ASN token also needs a source (#1973)
        ("AS15562", False),
        # one prefixed + one bare -> rejected (the bare token fails)
        ("RIPE::AS-FOO AS-BAR", False),
        # route-set names rejected on strict updates (#1973)
        ("RIPE::RS-FOO", False),
        ("RIPE::AS123456:RS-FOO", False),
        # IRR_AS_SET_MAX_SETS defaults to 0 (uncapped) -- the single-set cap is #1974
        # and ships disabled -- so several properly prefixed sets are accepted (the
        # cap is exercised in the count-cap tests below)
        ("RIPE::AS-FOO RADB::AS-BAR", "RIPE::AS-FOO RADB::AS-BAR"),
        # unknown source rejected on a CHANGED value -- typing a bad registry name
        # is a change, so this is where a typo or a retired source gets caught
        ("UNKNOWN::AS-FOO", False),
    ],
)
def test_validate_irr_as_set_strict(value, validated):
    """The #1973 strict rules: source required, no route-sets, count capped."""
    if not validated:
        with pytest.raises(ValidationError):
            validate_irr_as_set(value, strict=True)
    else:
        assert validate_irr_as_set(value, strict=True) == validated


@override_settings(IRR_AS_SET_MAX_SETS=2)
def test_validate_irr_as_set_strict_count_cap_configurable():
    # cap raised to 2 -> two prefixed sets now accepted
    assert (
        validate_irr_as_set("RIPE::AS-FOO RADB::AS-BAR", strict=True)
        == "RIPE::AS-FOO RADB::AS-BAR"
    )
    # three still over the cap
    with pytest.raises(ValidationError):
        validate_irr_as_set("RIPE::AS-FOO RADB::AS-BAR ARIN::AS-BAZ", strict=True)


@override_settings(IRR_AS_SET_MAX_SETS=0)
def test_validate_irr_as_set_strict_count_cap_disabled():
    # 0 disables the cap (wire-but-don't-enforce, #1973) -- the shipped default; the
    # cap is #1974 and gets a dated soft/hard rollout later
    assert (
        validate_irr_as_set("RIPE::AS-FOO RADB::AS-BAR", strict=True)
        == "RIPE::AS-FOO RADB::AS-BAR"
    )


@override_settings(
    IRR_AS_SET_MAX_SETS=1, IRR_AS_SET_CAP_HARD_START=datetime(2999, 1, 1)
)
def test_validate_irr_as_set_cap_not_enforced_before_hard_start():
    # #1974 dated rollout: cap configured but the hard-start date is in the
    # future -> multiple prefixed sets are still accepted (soft window)
    assert (
        validate_irr_as_set("RIPE::AS-FOO RADB::AS-BAR", strict=True)
        == "RIPE::AS-FOO RADB::AS-BAR"
    )


@override_settings(
    IRR_AS_SET_MAX_SETS=1, IRR_AS_SET_CAP_HARD_START=datetime(2000, 1, 1)
)
def test_validate_irr_as_set_cap_enforced_after_hard_start():
    # once the hard-start date has passed the cap rejects over-cap values
    with pytest.raises(ValidationError):
        validate_irr_as_set("RIPE::AS-FOO RADB::AS-BAR", strict=True)


@override_settings(
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=datetime(2000, 1, 1),
    IRR_AS_SET_CAP_HARD_START=None,
)
def test_validate_irr_as_set_cap_soft_window_warn_only():
    # a soft-start with no hard date is warn-only -> the save is still accepted
    # (the pdb_irr_as_set_notify nudge does the warning)
    assert (
        validate_irr_as_set("RIPE::AS-FOO RADB::AS-BAR", strict=True)
        == "RIPE::AS-FOO RADB::AS-BAR"
    )


@override_settings(IRR_AS_SET_REQUIRE_SOURCE=False, IRR_AS_SET_MAX_SETS=1)
def test_validate_irr_as_set_strict_source_kill_switch():
    # the source/route-set rules can be turned off at runtime; the count cap
    # (a separate knob -- explicitly set here since it defaults to 0/uncapped)
    # still applies
    assert validate_irr_as_set("AS-FOO", strict=True) == "AS-FOO"
    assert validate_irr_as_set("RIPE::RS-FOO", strict=True) == "RIPE::RS-FOO"
    with pytest.raises(ValidationError):
        validate_irr_as_set("AS-FOO AS-BAR", strict=True)


def test_validate_irr_as_set_default_is_not_strict():
    # default (strict=False) keeps the historical format-only behavior
    assert validate_irr_as_set("AS-FOO") == "AS-FOO"
    assert validate_irr_as_set("RS-FOO") == "RS-FOO"
    assert validate_irr_as_set("AS-FOO AS-BAR") == "AS-FOO AS-BAR"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("AS-FOO", ["AS-FOO"]),
        ("as-foo", ["AS-FOO"]),
        ("AS-FOO AS-BAR", ["AS-FOO", "AS-BAR"]),
        ("AS-FOO,AS-BAR", ["AS-FOO", "AS-BAR"]),
        ("AS-FOO, AS-BAR", ["AS-FOO", "AS-BAR"]),
        ("RIPE::AS-FOO, RADB::AS-BAR", ["RIPE::AS-FOO", "RADB::AS-BAR"]),
        ("", []),
        ("AS-FOO,", ["AS-FOO"]),
    ],
)
@pytest.mark.django_db
def test_tokenize_irr_as_set(value, expected):
    # the one home for this field's separator handling: the cap counts these
    # tokens, and the batch jobs (cleanup, cap nudge) must count identically or
    # the warning and the enforcement drift apart
    assert tokenize_irr_as_set(value) == expected


@pytest.mark.django_db
def test_tokenize_irr_as_set_keep_empty_for_the_validator():
    # the validator wants the empty tokens a stray separator produces so its
    # per-token format check still rejects them
    assert tokenize_irr_as_set("AS-FOO,", keep_empty=True) == ["AS-FOO", ""]
    with pytest.raises(ValidationError):
        validate_irr_as_set("AS-FOO,")
    with pytest.raises(ValidationError):
        validate_irr_as_set("")


@pytest.mark.parametrize(
    "token,expected",
    [
        ("RIPE::AS-FOO", ("RIPE", "AS-FOO")),
        ("RADB::AS64496", ("RADB", "AS64496")),
        # a nested name keeps its colons; only the first :: separates
        ("RIPE::AS-FOO:AS-BAR", ("RIPE", "AS-FOO:AS-BAR")),
        ("AS-FOO", (None, "AS-FOO")),
        # shape only: an unknown registry is still reported as a source, because
        # validate_irr_as_set has to name it in "Unknown IRR source: X"
        ("NOTAREGISTRY::AS-FOO", ("NOTAREGISTRY", "AS-FOO")),
        # not the SOURCE::NAME shape at all -> the whole token is the name
        ("RIPE::", (None, "RIPE::")),
        ("", (None, "")),
    ],
)
@pytest.mark.django_db
def test_split_irr_as_set_token(token, expected):
    assert split_irr_as_set_token(token) == expected


@pytest.mark.parametrize(
    "token,expected",
    [
        ("RIPE::AS-FOO", ("RIPE", "AS-FOO")),
        ("AS-FOO", (None, "AS-FOO")),
        # the difference from split_irr_as_set_token: a prefix naming a registry
        # PeeringDB does not know is not a pin anything can be verified against,
        # so the batch jobs read the whole token as the name
        ("NOTAREGISTRY::AS-FOO", (None, "NOTAREGISTRY::AS-FOO")),
    ],
)
@pytest.mark.django_db
def test_irr_as_set_pinned_source(token, expected):
    assert irr_as_set_pinned_source(token) == expected


@pytest.mark.django_db
def test_split_helpers_agree_with_the_validator_on_the_prefix_shape():
    """
    The regex behind these helpers is the same one validate_irr_as_set applies, so
    a token the helpers see as prefixed with a known source must also be one the
    validator accepts without a source-prefix complaint. The batch jobs decide
    what to re-verify off the helpers; if the two drifted, they would either skip
    values enforcement accepts or act on values it rejects.
    """
    for token in ("RIPE::AS-FOO", "RADB::AS64496", "RIPE::AS-FOO:AS-BAR"):
        source, _name = irr_as_set_pinned_source(token)
        assert source is not None
        validate_irr_as_set(token, strict=True)


@pytest.mark.django_db
def test_network_serializer_irr_as_set_change_gated():
    """
    #1973: the serializer enforces the unambiguous-name rules only when the
    value actually changes, so legacy values keep working (change-gate).
    """
    org = Organization.objects.create(name="IRR Org", status="ok")
    # legacy row with a bare (ambiguous) value; save() bypasses validation
    net = Network.objects.create(
        name="IRR Net", asn=64500, irr_as_set="AS-FOO", status="ok", org=org
    )

    # --- create path (no instance): any non-empty value is strict-checked ---
    with pytest.raises(ValidationError):
        NetworkSerializer().validate_irr_as_set("AS-NEW")  # bare -> rejected
    assert NetworkSerializer().validate_irr_as_set("RIPE::AS-NEW") == "RIPE::AS-NEW"
    # empty is always allowed
    assert NetworkSerializer().validate_irr_as_set("") == ""

    ser = NetworkSerializer(instance=net)
    # unchanged legacy value passes even though it is bare
    assert ser.validate_irr_as_set("AS-FOO") == "AS-FOO"
    # a no-op re-submit differing only in case/separators is not a change
    assert ser.validate_irr_as_set("as-foo") == "AS-FOO"
    # changing to another bare value is rejected
    with pytest.raises(ValidationError):
        ser.validate_irr_as_set("AS-BAR")
    # changing to a properly prefixed value is accepted
    assert ser.validate_irr_as_set("RIPE::AS-FOO") == "RIPE::AS-FOO"


@pytest.mark.django_db
def test_network_admin_form_irr_as_set_change_gated():
    """
    #1973: the admin form (NetworkAdminForm.clean_irr_as_set) is change-gated
    exactly like the serializer -- the strict unambiguous-name rules bite only on
    a genuine edit, so legacy values keep working, and superusers bypass them
    (#741). Mirrors test_network_serializer_irr_as_set_change_gated for the admin
    path, including the superuser bypass in an admin request context.
    """
    # NetworkAdminForm gets its model from the ModelAdmin at runtime; bind one
    # here so the form can be instantiated standalone in the test.
    form_class = modelform_factory(
        Network, form=NetworkAdminForm, fields=["irr_as_set"]
    )

    org = Organization.objects.create(name="IRR Admin Org", status="ok")
    # legacy row with a bare (ambiguous) value; save() bypasses validation
    net = Network.objects.create(
        name="IRR Admin Net", asn=64600, irr_as_set="AS-FOO", status="ok", org=org
    )

    def clean(instance, value):
        # exercise clean_irr_as_set directly (as the serializer test does),
        # setting cleaned_data so no full form validation is required
        form = form_class(instance=instance)
        form.cleaned_data = {"irr_as_set": value}
        return form.clean_irr_as_set()

    # --- create path (blank instance, no pk): any non-empty value is strict ---
    with pytest.raises(ValidationError):
        clean(None, "AS-NEW")  # bare -> rejected
    assert clean(None, "RIPE::AS-NEW") == "RIPE::AS-NEW"
    # empty is always allowed
    assert clean(net, "") == ""

    # --- update path ---
    # unchanged legacy value passes even though it is bare
    assert clean(net, "AS-FOO") == "AS-FOO"
    # a no-op re-submit differing only in case/separators is not a change
    assert clean(net, "as-foo") == "AS-FOO"
    # changing to another bare value is rejected
    with pytest.raises(ValidationError):
        clean(net, "AS-BAR")
    # changing to a properly prefixed value is accepted
    assert clean(net, "RIPE::AS-FOO") == "RIPE::AS-FOO"

    # --- superuser bypass (#741): strict rules skipped in a superuser request ---
    User = get_user_model()
    superuser = User.objects.create_user(
        username="irr_admin_su",
        password="x",
        email="irr_su@localhost",
        is_superuser=True,
    )
    request = RequestFactory().get("/cp/")
    request.user = superuser
    with current_request(request):
        # a changed bare value would normally be rejected; the superuser bypasses
        assert clean(net, "AS-BRAND-NEW") == "AS-BRAND-NEW"


@override_settings(IRR_AS_SET_VERIFY_EXISTENCE=True)
def test_validate_irr_as_set_strict_rejects_absent_object():
    # strict + object provably absent in its pinned registry -> rejected
    with (
        patch("peeringdb_server.irr.exists_in", return_value=False),
        patch(
            "peeringdb_server.irr.sources_for",
            return_value=irr_module.LookupResult(frozenset({"ARIN"}), True),
        ),
    ):
        with pytest.raises(ValidationError) as exc:
            validate_irr_as_set("RIPE::AS-GHOST", strict=True)
        # the error points the user at where the object *does* live
        assert "ARIN" in str(exc.value)


@override_settings(IRR_AS_SET_VERIFY_EXISTENCE=True)
def test_validate_irr_as_set_strict_fail_open_on_unknown():
    # lookup infrastructure can't answer (None) -> accepted, left for the checker
    with patch("peeringdb_server.irr.exists_in", return_value=None):
        assert validate_irr_as_set("RIPE::AS-GHOST", strict=True) == "RIPE::AS-GHOST"


@override_settings(IRR_AS_SET_VERIFY_EXISTENCE=True, IRR_AS_SET_MAX_SETS=2)
def test_validate_irr_as_set_strict_multi_token_one_absent():
    # cap raised to 2 so both tokens pass syntactically; the live check then
    # rejects because one token's object is absent. sources_for returns ok=False,
    # so the error carries the plain token (the "found in: ..." hint is omitted).
    def exists(source, name, object_class=None):
        return name != "AS-BAR"  # AS-FOO exists, AS-BAR absent

    with (
        patch("peeringdb_server.irr.exists_in", side_effect=exists),
        patch(
            "peeringdb_server.irr.sources_for",
            return_value=irr_module.LookupResult(frozenset(), False),
        ),
    ):
        with pytest.raises(ValidationError) as exc:
            validate_irr_as_set("RIPE::AS-FOO RADB::AS-BAR", strict=True)
    msg = str(exc.value)
    assert "AS-BAR" in msg
    assert "found in" not in msg


def test_validate_irr_as_set_no_live_check_when_not_strict():
    # format-only (strict=False) must never trigger a live lookup
    with patch("peeringdb_server.irr.exists_in") as m_exists:
        assert validate_irr_as_set("RIPE::AS-FOO") == "RIPE::AS-FOO"
        m_exists.assert_not_called()


@pytest.mark.django_db
@override_settings(IRR_AS_SET_VERIFY_EXISTENCE=True)
def test_network_serializer_irr_as_set_live_check_rejects_absent():
    # the serializer change-gate + live check reject a *changed* value whose
    # object does not exist in the pinned registry
    org = Organization.objects.create(name="IRR Org Live", status="ok")
    net = Network.objects.create(
        name="IRR Net Live", asn=64501, irr_as_set="RIPE::AS-OLD", status="ok", org=org
    )
    ser = NetworkSerializer(instance=net)
    with (
        patch("peeringdb_server.irr.exists_in", return_value=False),
        patch(
            "peeringdb_server.irr.sources_for",
            return_value=irr_module.LookupResult(frozenset(), True),
        ),
    ):
        with pytest.raises(ValidationError):
            ser.validate_irr_as_set("RIPE::AS-CHANGED")


@pytest.mark.django_db
def test_validate_phonenumber():
    # test standalone validator

    validate_phonenumber("+1 206 555 0199")
    validate_phonenumber("012065550199", "US")

    with pytest.raises(ValidationError):
        validate_phonenumber("invalid number")

    with pytest.raises(ValidationError):
        validate_phonenumber("012065550199")

    # test model field validation

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(
        name="Text exchange",
        status="ok",
        org=org,
        country="US",
        city="Some city",
        region_continent="North America",
        media="Ethernet",
    )
    net = Network.objects.create(name="Text network", asn=12345, status="ok", org=org)
    poc = NetworkContact.objects.create(network=net, status="ok", role="Abuse")

    # test poc phone validation

    with pytest.raises(ValidationError):
        poc.phone = "invalid"
        poc.full_clean()

    poc.phone = "+1 206 555 0199"
    poc.full_clean()

    # test ix phone validation

    with pytest.raises(ValidationError):
        ix.tech_phone = "invalid"
        ix.full_clean()

    ix.tech_phone = "+1 206 555 0199"
    ix.full_clean()

    with pytest.raises(ValidationError):
        ix.policy_phone = "invalid"
        ix.full_clean()

    ix.policy_phone = "+1 206 555 0199"
    ix.full_clean()


@pytest.mark.django_db
def test_validate_ixpfx_ixlan_status_match():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(
        name="Text exchange", status="pending", org=org
    )
    ixlan = ix.ixlan

    pfx = IXLanPrefix.objects.create(
        ixlan=ixlan,
        protocol="IPv4",
        prefix=ipaddress.ip_network("198.32.125.0/24"),
        status="ok",
    )

    with pytest.raises(ValidationError) as exc1:
        pfx.clean()

    assert (
        exc1.value.args[0]
        == "IXLanPrefix with status 'ok' cannot be linked to a IXLan with status 'pending'."
    )

    ixlan.status = "deleted"
    ixlan.save()
    pfx.status = "pending"
    pfx.save()

    with pytest.raises(ValidationError) as exc2:
        pfx.clean()

    assert (
        exc2.value.args[0]
        == "IXLanPrefix with status 'pending' cannot be linked to a IXLan with status 'deleted'."
    )


@pytest.mark.django_db
@override_settings(
    DATA_QUALITY_MAX_PREFIX_V4_LIMIT=500000,
    DATA_QUALITY_MAX_PREFIX_V6_LIMIT=500000,
    DATA_QUALITY_MIN_PREFIXLEN_V4=24,
    DATA_QUALITY_MAX_PREFIXLEN_V4=24,
    DATA_QUALITY_MIN_PREFIXLEN_V6=48,
    DATA_QUALITY_MAX_PREFIXLEN_V6=48,
    DATA_QUALITY_MAX_IRR_DEPTH=3,
    DATA_QUALITY_MIN_SPEED=10,
    DATA_QUALITY_MAX_SPEED=100,
)
def test_bypass_validation():
    User = get_user_model()

    superuser = User.objects.create_user(
        username="superuser",
        password="superuser",
        email="su@localhost",
        is_superuser=True,
    )
    user = User.objects.create_user(
        username="user", password="user", email="user@localhost"
    )

    factory = RequestFactory()

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(
        name="Text exchange",
        status="ok",
        org=org,
        country="US",
        city="Some city",
        region_continent="North America",
        media="Ethernet",
    )
    net = Network.objects.create(name="Text network", asn=12345, status="ok", org=org)

    # super user should bypass validation

    request = factory.get("/")
    request.user = superuser
    with current_request(request):
        validate_address_space("37.77.32.0/20")
        validate_address_space("131.72.77.240/28")
        validate_address_space("2403:c240::/32")
        validate_address_space("2001:504:0:2::/64")
        validate_info_prefixes4(500001)
        validate_info_prefixes6(500001)
        NetworkIXLan(speed=1, network=net, ixlan=ix.ixlan, status="ok").clean()
        NetworkIXLan(speed=1000, network=net, ixlan=ix.ixlan, status="ok").clean()
        validate_irr_as_set("ripe::as-foo:as123:as345:as678")
        # #1973 strict rules are also bypassed by superusers (#741)
        validate_irr_as_set("as-foo", strict=True)
        validate_irr_as_set("ripe::rs-foo", strict=True)

    # user should NOT bypass validation

    request = factory.get("/")
    request.user = user
    with current_request(request):
        with pytest.raises(ValidationError):
            validate_address_space("37.77.32.0/20")
        with pytest.raises(ValidationError):
            validate_address_space("131.72.77.240/28")
        with pytest.raises(ValidationError):
            validate_address_space("2403:c240::/32")
        with pytest.raises(ValidationError):
            validate_address_space("2001:504:0:2::/64")
        with pytest.raises(ValidationError):
            validate_info_prefixes4(500001)
        with pytest.raises(ValidationError):
            validate_info_prefixes6(500001)
        with pytest.raises(ValidationError):
            NetworkIXLan(speed=1, network=net, ixlan=ix.ixlan).clean()
        with pytest.raises(ValidationError):
            NetworkIXLan(speed=1000, network=net, ixlan=ix.ixlan).clean()
        with pytest.raises(ValidationError):
            validate_irr_as_set("ripe::as-foo:as123:as345:as678")
        # #1973 strict rules are enforced for non-superusers
        with pytest.raises(ValidationError):
            validate_irr_as_set("as-foo", strict=True)
        with pytest.raises(ValidationError):
            validate_irr_as_set("ripe::rs-foo", strict=True)


@pytest.mark.django_db
@override_settings(DATA_QUALITY_MIN_SPEED=50, DATA_QUALITY_MAX_SPEED=5000000)
def test_netixlan_speed_bounds():
    """
    Tests min (50M) and max (5T) speed bounds and their error messages (#1888).
    """
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(
        name="Test exchange",
        status="ok",
        org=org,
        country="US",
        city="Some city",
        region_continent="North America",
        media="Ethernet",
    )
    net = Network.objects.create(asn=1234, name="Test net", status="ok", org=org)

    # Below minimum (49M) should raise with "Minimum speed: 50M"
    with pytest.raises(ValidationError) as exc_info:
        NetworkIXLan(speed=49, network=net, ixlan=ix.ixlan, status="ok").clean()
    assert "Minimum speed: 50M" in str(exc_info.value)

    # Exactly at minimum (50M) should pass
    NetworkIXLan(speed=50, network=net, ixlan=ix.ixlan, status="ok").clean()

    # Old minimum (100M) should also pass
    NetworkIXLan(speed=100, network=net, ixlan=ix.ixlan, status="ok").clean()

    # Exactly at maximum (5000000M = 5T) should pass
    NetworkIXLan(speed=5000000, network=net, ixlan=ix.ixlan, status="ok").clean()

    # Above maximum should raise with "Maximum speed: 5T"
    with pytest.raises(ValidationError) as exc_info:
        NetworkIXLan(speed=5000001, network=net, ixlan=ix.ixlan, status="ok").clean()
    assert "Maximum speed: 5T" in str(exc_info.value)


@pytest.mark.django_db
def test_ghost_peer_vs_real_peer_one_netixlan():
    """
    Tests that a real peer can claim the ip addresses of a gohst peer. #983

    In this test both ipv4 and ipv6 exist on the same netixlan.
    """

    # set up entities

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="ok", org=org)
    network_other = Network.objects.create(
        asn=1010, name="AS1010", status="ok", org=org
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
    ixlan.save()

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="195.69.144.0/22",
        protocol="IPv4",
    )

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="2001:7f8:1::/64",
        protocol="IPv6",
    )

    IP4 = "195.69.147.250"
    IP6 = "2001:7f8:1::a500:2906:1"

    ghost_peer = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=IP4,
        ipaddr6=IP6,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    # setup IX-F cache

    data = setup_test_data("ixf.member.1")
    cache.set(f"IXF-CACHE-{ix.ixlan.ixf_ixp_member_list_url}", data)

    ix = ixlan.ix

    # real peer should exist in IX-F data

    real4, real6 = ix.peer_exists_in_ixf_data(1001, IP4, IP6)
    assert real4
    assert real6

    # ghost peer should NOT exist in IX-F data

    ghost4, ghost6 = ix.peer_exists_in_ixf_data(1010, IP4, IP6)
    assert not ghost4
    assert not ghost6

    # create and save a real peer that has the same ip addresses
    # as the ghost peer

    real_peer = NetworkIXLan(
        network=network,
        status="ok",
        ipaddr4=IP4,
        ipaddr6=IP6,
        ixlan=ixlan,
        speed=1000,
        asn=network.asn,
    )

    # run full validation (this will run `validate_real_vs_ghost_peer`)

    real_peer.full_clean()
    real_peer.save()

    # real peer has been saved and since it claimed both ip4 and ip6, the ghost
    # peer is now deleted

    ghost_peer.refresh_from_db()

    assert ghost_peer.status == "deleted"


@pytest.mark.django_db
def test_ghost_peer_vs_real_peer_two_netixlan():
    """
    Tests that a real peer can claim the ip addresses of a gohst peer. #983

    In this test both ipv4 and ipv6 exist on separate netixlans.

    In this test both conflicting netixlans will have neither ipv4 nor ipv6 set in the end
    and will be deleted
    """

    # set up entities

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="ok", org=org)
    network_other = Network.objects.create(
        asn=1010, name="AS1010", status="ok", org=org
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
    ixlan.save()

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="195.69.144.0/22",
        protocol="IPv4",
    )

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="2001:7f8:1::/64",
        protocol="IPv6",
    )

    IP4 = "195.69.147.250"
    IP6 = "2001:7f8:1::a500:2906:1"

    ghost_peer_a = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=IP4,
        ipaddr6=None,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    ghost_peer_b = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=None,
        ipaddr6=IP6,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    # setup IX-F data

    data = setup_test_data("ixf.member.1")
    cache.set(f"IXF-CACHE-{ix.ixlan.ixf_ixp_member_list_url}", data)

    ix = ixlan.ix

    # real peer should exist in IX-F data

    real4, real6 = ix.peer_exists_in_ixf_data(1001, IP4, IP6)
    assert real4
    assert real6

    # ghost peer should NOT exist in IX-F data

    ghost4, ghost6 = ix.peer_exists_in_ixf_data(1010, IP4, IP6)
    assert not ghost4
    assert not ghost6

    # create and save a real peer that has the same ip addresses
    # as the ghost peer

    real_peer = NetworkIXLan(
        network=network,
        status="ok",
        ipaddr4=IP4,
        ipaddr6=IP6,
        ixlan=ixlan,
        speed=1000,
        asn=network.asn,
    )

    # run full validation (this will run `validate_real_vs_ghost_peer`)

    real_peer.full_clean()
    real_peer.save()

    # real peer has been saved and since it claimed both ip4 and ip6, the ghost
    # peer is now deleted

    ghost_peer_a.refresh_from_db()
    ghost_peer_b.refresh_from_db()

    assert ghost_peer_a.status == "deleted"
    assert ghost_peer_b.status == "deleted"


@pytest.mark.django_db
def test_ghost_peer_vs_real_peer_two_netixlan_partial():
    """
    Tests that a real peer can claim the ip addresses of a gohst peer. #983

    In this test both ipv4 and ipv6 exist on separate netixlans.

    In this test the conflicting netixlans will have the other ip address still set and will not be deleted.
    """

    # set up entities

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="ok", org=org)
    network_other = Network.objects.create(
        asn=1010, name="AS1010", status="ok", org=org
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
    ixlan.save()

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="195.69.144.0/22",
        protocol="IPv4",
    )

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="2001:7f8:1::/64",
        protocol="IPv6",
    )

    IP4 = "195.69.147.250"
    IP6 = "2001:7f8:1::a500:2906:1"

    ghost_peer_a = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=IP4,
        ipaddr6="2001:7f8:1::a500:2906:2",
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    ghost_peer_b = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4="195.69.147.251",
        ipaddr6=IP6,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    # setup IX-F data

    data = setup_test_data("ixf.member.1")
    cache.set(f"IXF-CACHE-{ix.ixlan.ixf_ixp_member_list_url}", data)

    ix = ixlan.ix

    # real peer should exist in IX-F data

    real4, real6 = ix.peer_exists_in_ixf_data(1001, IP4, IP6)
    assert real4
    assert real6

    # ghost peer should NOT exist in IX-F data

    ghost4, ghost6 = ix.peer_exists_in_ixf_data(1010, IP4, IP6)
    assert not ghost4
    assert not ghost6

    # create and save a real peer that has the same ip addresses
    # as the ghost peer

    real_peer = NetworkIXLan(
        network=network,
        status="ok",
        ipaddr4=IP4,
        ipaddr6=IP6,
        ixlan=ixlan,
        speed=1000,
        asn=network.asn,
    )

    # run full validation (this will run `validate_real_vs_ghost_peer`)

    real_peer.full_clean()
    real_peer.save()

    # real peer has been saved and since it only claimed one ip address
    # from either ghost peer, both ghost peers remain

    ghost_peer_a.refresh_from_db()
    ghost_peer_b.refresh_from_db()

    assert ghost_peer_a.status == "ok"
    assert ghost_peer_a.ipaddr4 is None
    assert ghost_peer_a.ipaddr6 is not None

    assert ghost_peer_b.status == "ok"
    assert ghost_peer_b.ipaddr4 is not None
    assert ghost_peer_b.ipaddr6 is None


@pytest.mark.django_db
def test_ghost_peer_vs_real_peer_invalid_ixf_data():
    """
    Tests that a real peer can claim the ip addresses of a gohst peer. #983

    Test the handling of invalid IX-F data, in which case the ghost peer vs real peer
    logic should be skipped.
    """

    # set up entities

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="ok", org=org)
    network_other = Network.objects.create(
        asn=1010, name="AS1010", status="ok", org=org
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
    ixlan.save()

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="195.69.144.0/22",
        protocol="IPv4",
    )

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="2001:7f8:1::/64",
        protocol="IPv6",
    )

    IP4 = "195.69.147.250"
    IP6 = "2001:7f8:1::a500:2906:1"

    NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=IP4,
        ipaddr6=IP6,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )
    # setup IX-F data

    cache.set(f"IXF-CACHE-{ix.ixlan.ixf_ixp_member_list_url}", {"invalid": "data"})

    ix = ixlan.ix

    real_peer = NetworkIXLan(
        network=network,
        status="ok",
        ipaddr4=IP4,
        ipaddr6=IP6,
        ixlan=ixlan,
        speed=1000,
        asn=network.asn,
    )

    # run full validation (this will run `validate_real_vs_ghost_peer`)

    with pytest.raises(Exception) as excinfo:
        real_peer.full_clean()
    assert "IP already exists" in str(excinfo.value)


@pytest.mark.parametrize(
    "value,validated",
    [
        # success validation
        (
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"service": "x", "identifier": "user_123"},
            ],
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"service": "x", "identifier": "user_123"},
            ],
        ),
        (
            [
                {"service": "instagram", "identifier": "john_doe.123"},
                {"service": "tiktok", "identifier": "unknown_12"},
            ],
            [
                {"service": "instagram", "identifier": "john_doe.123"},
                {"service": "tiktok", "identifier": "unknown_12"},
            ],
        ),
        (
            [
                {"service": "instagram", "identifier": "john__doe_"},
                {"service": "tiktok", "identifier": "Unknown_12"},
            ],
            [
                {"service": "instagram", "identifier": "john__doe_"},
                {"service": "tiktok", "identifier": "Unknown_12"},
            ],
        ),
        (
            [
                {"service": "linkedin", "identifier": "jane-doe-pro"},
                {"service": "bluesky", "identifier": "myblueskyhandle"},
            ],
            [
                {"service": "linkedin", "identifier": "jane-doe-pro"},
                {"service": "bluesky", "identifier": "myblueskyhandle"},
            ],
        ),
        (
            [
                {"service": "reddit", "identifier": "reddit_user_1"},
                {"service": "snapchat", "identifier": "snap-user-2"},
            ],
            [
                {"service": "reddit", "identifier": "reddit_user_1"},
                {"service": "snapchat", "identifier": "snap-user-2"},
            ],
        ),
        (
            [
                {"service": "youtube", "identifier": "My.YT.Channel"},
                {"service": "telegram", "identifier": "Telegram_User_ID"},
            ],
            [
                {"service": "youtube", "identifier": "My.YT.Channel"},
                {"service": "telegram", "identifier": "Telegram_User_ID"},
            ],
        ),
        (
            [
                {"service": "threads", "identifier": "threads.user_name"},
                {"service": "pinterest", "identifier": "my-pin_board"},
            ],
            [
                {"service": "threads", "identifier": "threads.user_name"},
                {"service": "pinterest", "identifier": "my-pin_board"},
            ],
        ),
        (
            [
                {"service": "douyin", "identifier": "douyin_user_123"},
                {"service": "weibo", "identifier": "weibo-user.456"},
            ],
            [
                {"service": "douyin", "identifier": "douyin_user_123"},
                {"service": "weibo", "identifier": "weibo-user.456"},
            ],
        ),
        (
            [
                {"service": "qq", "identifier": "https://im.qq.com/user123"},
                {"service": "mastodon", "identifier": "https://mastodon.social/@user"},
                {"service": "whatsapp", "identifier": "+628123456789"},
            ],
            [
                {"service": "qq", "identifier": "https://im.qq.com/user123"},
                {"service": "mastodon", "identifier": "https://mastodon.social/@user"},
                {"service": "whatsapp", "identifier": "+628123456789"},
            ],
        ),
        # --- Service Rule Failures ---
        ([{"service": "x", "identifier": "aaa"}], False),  # too short
        ([{"service": "x", "identifier": "a" * 16}], False),  # too long
        ([{"service": "x", "identifier": "$bla/"}], False),  # invalid characters
        ([{"service": "instagram", "identifier": "john__doe_*"}], False),
        ([{"service": "instagram", "identifier": ".starts.with.dot"}], False),
        ([{"service": "instagram", "identifier": "ends.with.dot."}], False),
        ([{"service": "instagram", "identifier": "consecutive..dots"}], False),
        ([{"service": "facebook", "identifier": "user_name"}], False),
        ([{"service": "facebook", "identifier": "bad"}], False),
        ([{"service": "youtube", "identifier": ".mychannel"}], False),
        ([{"service": "bluesky", "identifier": "-bad-handle"}], False),
        ([{"service": "bluesky", "identifier": "bad--handle"}], False),
        ([{"service": "reddit", "identifier": "user-name"}], False),
        ([{"service": "snapchat", "identifier": "user_name"}], False),
        ([{"service": "telegram", "identifier": "user-name"}], False),
        ([{"service": "x", "identifier": None}], False),
        ([{"service": "x", "identifier": ""}], False),
        ([{"service": "qq", "identifier": "http://??.com"}], False),
        ([{"service": "mastodon", "identifier": "test_fail.com"}], False),
        ([{"service": "whatsapp", "identifier": "abc123"}], False),
        ([{"service": "whatsapp", "identifier": "08123456789"}], False),
        (
            {"service": "website", "identifier": "https://www.example.com"},
            False,
        ),  # not a list
        ([{"service": None, "identifier": "username"}], False),
        ([{"service": "", "identifier": "username"}], False),
    ],
)
@pytest.mark.django_db
def test_validate_social_media(value, validated):
    if not validated:
        with pytest.raises(ValidationError):
            validate_social_media(value)
    else:
        assert validate_social_media(value) == validated


@pytest.mark.parametrize(
    "website,org_website,validated",
    [
        # success validation website not null
        (
            "https://www.example.com",
            "https://www.example1.com",
            "https://www.example.com",
        ),
        # success validation website null and overrided by organization website
        (None, "https://www.example1.com", "https://www.example1.com"),
        # fail validation
        (
            None,
            None,
            False,
        ),
    ],
)
@pytest.mark.django_db
def test_validate_website_override(website, org_website, validated):
    if not validated:
        with pytest.raises(ValidationError):
            validate_website_override(website, org_website)
    else:
        assert validate_website_override(website, org_website) == validated


@pytest.mark.django_db
def test_org_create_with_none_social_media():
    org = Organization.objects.create(name="Test org", status="ok", social_media=None)
    assert org.social_media == {}


@pytest.mark.parametrize(
    "value,is_valid,validated",
    [
        # success validation
        ("63311", True, "63311"),
        ("as63311", True, "63311"),
        ("asn63311", True, "63311"),
        ("AS63311", True, "63311"),
        ("ASN63311", True, "63311"),
        # fail validation
        ("AN63311", False, None),
        ("6as3311", False, None),
        ("63311asn", False, None),
    ],
)
@pytest.mark.django_db
def test_validate_asn_prefix(value, is_valid, validated):
    print(is_valid)
    if not is_valid:
        with pytest.raises(RestValidationError):
            validate_asn_prefix(value)
    else:
        assert validate_asn_prefix(value) == validated


@pytest.mark.parametrize(
    "value,is_valid,validated",
    [
        # success validation
        (37.7749, True, 37.7749),
        (-23.5505, True, -23.5505),
        (51.5074, True, 51.5074),
        (40.7128, True, 40.7128),
        ("-33.8688", True, -33.8688),
        # fail validation
        (95.1234, False, None),
        (-120.5678, False, None),
        ("-122.5678", False, None),
        ("abcdef", False, None),
    ],
)
@pytest.mark.django_db
def test_validate_latitude(value, is_valid, validated):
    if not is_valid:
        with pytest.raises(ValidationError):
            validate_latitude(value)
    else:
        assert validate_latitude(value) == validated


@pytest.mark.parametrize(
    "value,is_valid,validated",
    [
        # success validation
        (-122.4194, True, -122.4194),
        (-46.6333, True, -46.6333),
        (-0.1270, True, -0.1270),
        (-74.0060, True, -74.0060),
        ("151.2093", True, 151.2093),
        # fail validation
        (190.1234, False, None),
        (-250.5678, False, None),
        ("360.9876", False, None),
        ("abcdef", False, None),
    ],
)
@pytest.mark.django_db
def test_validate_longitude(value, is_valid, validated):
    if not is_valid:
        with pytest.raises(ValidationError):
            validate_longitude(value)
    else:
        assert validate_longitude(value) == validated


def geo_mock_init(self, key, timeout):
    pass


def geo_gmaps_mock_geocode_freeform(location):
    return {"lat": 40.712776, "lng": -74.005974}


@pytest.mark.parametrize(
    "current_geocode,new_geocode,current_city,new_city,is_valid,validated",
    [
        # test success with exists geocode (max 1km from previous geocode)
        (
            (50.951533, 1.852570),
            (50.951533, 1.851440),
            "london",
            "london",
            True,
            (50.951533, 1.851440),
        ),
        (
            (40.712776, -74.005974),
            (40.712790, -74.003974),
            "new york",
            "new york",
            True,
            (40.712790, -74.003974),
        ),
        # # test fail with exists geocode (max 1km from previous geocode)
        (
            (40.712776, -74.005974),
            (40.712790, -73.003974),
            "new york",
            "new york",
            False,
            None,
        ),
        ((50.951533, 1.852570), (51.951533, 0.851440), "london", "london", False, None),
        # test success with not exists geocode (max 50km from city)
        (
            (None, None),
            (40.712771, -74.005970),
            "new york",
            "new york",
            True,
            (40.712771, -74.005970),
        ),
        (
            (None, None),
            (40.716822, -73.991032),
            "new york",
            "new york",
            True,
            (40.716822, -73.991032),
        ),
        # test fail with not exists geocode (max 50km from city)
        ((None, None), (36.169941, -115.139832), "new york", "new york", False, None),
        ((None, None), (36.201902, -115.328808), "new york", "new york", False, None),
    ],
)
@patch.object(geo.GoogleMaps, "__init__", geo_mock_init)
@patch.object(geo.Melissa, "__init__", geo_mock_init)
@pytest.mark.django_db
def test_validate_distance_geocode(
    current_geocode, new_geocode, current_city, new_city, is_valid, validated, settings
):
    settings.MELISSA_KEY = ""
    settings.GOOGLE_GEOLOC_API_KEY = ""
    with patch.object(
        geo.GoogleMaps, "geocode_freeform", side_effect=geo_gmaps_mock_geocode_freeform
    ):
        if not is_valid:
            with pytest.raises(ValidationError):
                validate_distance_geocode(
                    current_geocode, new_geocode, current_city, new_city
                )
        else:
            assert (
                validate_distance_geocode(
                    current_geocode, new_geocode, current_city, new_city
                )
                == validated
            )


def test_validate_status_change():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test exchange", status="ok", org=org)
    ix.status = "pending"
    with pytest.raises(ValidationError):
        ix.clean()
        ix.save()

    fac = Facility.objects.create(name="Test facility", status="ok", org=org)
    fac.status = "pending"
    with pytest.raises(ValidationError):
        fac.clean()
        fac.save()

    net = Network.objects.create(name="Test network", status="ok", org=org, asn=101)
    net.status = "pending"
    with pytest.raises(ValidationError):
        net.clean()
        net.save()


@pytest.mark.django_db
def test_validate_status_value_model():
    """
    Ensure invalid `status` values are rejected by model-level validation.

    This verifies that `ParentStatusCheckMixin.validate_status_value`
    correctly enforces allowed status values via the validators in `validators.py`.
    """

    # Setup base objects
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test exchange", status="ok", org=org)
    net = Network.objects.create(name="Test network", status="ok", org=org, asn=101)
    ixlan = ix.ixlan

    # Ensure IP validation passes
    IXLanPrefix.objects.create(
        ixlan=ixlan, protocol="IPv4", prefix="192.0.2.0/24", status="ok"
    )

    # Helper to assert ValidationError with specific message
    def assert_invalid_status(instance, expected_msg="Invalid status value"):
        with pytest.raises(ValidationError) as excinfo:
            instance.full_clean()
        assert expected_msg in str(excinfo.value)

    # --- Invalid status tests ---
    invalid_cases = [
        NetworkIXLan(
            network=net,
            ixlan=ixlan,
            asn=net.asn,
            speed=1000,
            ipaddr4="192.0.2.1",
            status="Testing",  # Invalid
        ),
        Network(
            name="Test network 2",
            org=org,
            asn=102,
            status="active",  # Invalid
        ),
        InternetExchange(
            name="Test IX 2",
            org=org,
            city="Test City",
            country="US",
            region_continent="North America",
            status="approved",  # Invalid
        ),
    ]

    for instance in invalid_cases:
        assert_invalid_status(instance)

    # --- Valid status test ---
    valid_netixlan = NetworkIXLan(
        network=net,
        ixlan=ixlan,
        asn=net.asn,
        speed=1000,
        ipaddr4="192.0.2.10",
        status="ok",  # Valid
    )
    # Should not raise
    valid_netixlan.full_clean()


def test_validate_status():
    """
    Test the validate_status validator function directly.

    This validates that only 'ok', 'pending', 'deleted' status values are accepted.
    This validator is used at the model level (ParentStatusCheckMixin.validate_status_value).
    """
    # Test valid status values
    assert validate_status("ok") == "ok"
    assert validate_status("pending") == "pending"
    assert validate_status("deleted") == "deleted"

    # Test invalid status values
    with pytest.raises(RestValidationError) as exc:
        validate_status("Testing")
    assert "Invalid status value" in str(exc.value)
    assert "ok, pending, deleted" in str(exc.value)

    with pytest.raises(RestValidationError) as exc:
        validate_status("active")
    assert "Invalid status value" in str(exc.value)

    with pytest.raises(RestValidationError) as exc:
        validate_status("approved")
    assert "Invalid status value" in str(exc.value)

    with pytest.raises(RestValidationError) as exc:
        validate_status("verified")
    assert "Invalid status value" in str(exc.value)


@pytest.mark.django_db
def test_validate_status_field_serializer():
    """
    Ensure the `status` field is read-only in serializers and cannot be set via API.

    This prevents the API from accepting arbitrary status values (see issue #1562).
    The status field is declared as ReadOnlyField, so any status value provided
    in the input data should be ignored.
    """

    # --- Setup ---
    factory = APIRequestFactory()
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(
        name="Test exchange",
        org=org,
        status="ok",
        city="Test City",
        country="US",
        region_continent="North America",
    )
    net = Network.objects.create(name="Test network", status="ok", org=org, asn=101)
    ixlan = ix.ixlan

    # Add IP prefix so NetworkIXLan can be created
    IXLanPrefix.objects.create(
        ixlan=ixlan, protocol="IPv4", prefix="192.0.2.0/24", status="ok"
    )

    # --- Test that status field is ignored in input data ---
    # Even if we try to set status to an invalid value, it should be ignored
    # and the object should be created with the default status
    django_request = factory.post("/api/netixlan")
    request = Request(django_request)

    test_cases = [
        {
            "name": "NetworkIXLan with invalid status",
            "serializer_class": NetworkIXLanSerializer,
            "data": {
                "net_id": net.id,
                "ixlan_id": ixlan.id,
                "asn": net.asn,
                "speed": 1000,
                "ipaddr4": "192.0.2.1",
                "status": "Testing",  # This should be ignored
            },
        },
    ]

    for test_case in test_cases:
        serializer = test_case["serializer_class"](
            data=test_case["data"], context={"request": request}
        )

        # The serializer should be valid because status is read-only and ignored
        # (though it may fail validation for other reasons like permissions)
        # The key assertion is that status should NOT be in the errors
        if not serializer.is_valid():
            assert "status" not in serializer.errors, (
                f"{test_case['name']}: status field should be read-only and ignored, "
                f"but got error: {serializer.errors.get('status')}"
            )

    # --- Verify status field is marked as read-only ---
    serializer = NetworkIXLanSerializer()
    assert serializer.fields["status"].read_only, (
        "status field should be marked as read_only"
    )


@pytest.mark.parametrize(
    "value",
    [
        "30/m",
        "120/m",
        "10/s",
        "1000/h",
        "800/d",
        "100/5m",
        "",
    ],
)
def test_validate_django_ratelimit_rate_valid(value):
    assert validate_django_ratelimit_rate(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "120/minute",
        "10/second",
        "100/hour",
        "abc",
        "/m",
        "100/",
        "100/x",
    ],
)
def test_validate_django_ratelimit_rate_invalid(value):
    with pytest.raises(ValidationError):
        validate_django_ratelimit_rate(value)


@pytest.mark.django_db
def test_pruned_irr_sources_are_no_longer_accepted():
    """
    the #1973 prune: NESTEGG and PANIX were removed from IRR_SOURCE on evidence
    their registries hold nothing (RADB dumps of 484 B and 812 B, header only), so a
    value naming them can never pass an existence check and must be rejected as an
    unknown source rather than silently pinned to a dead registry.
    """
    for pruned in ("NESTEGG", "PANIX"):
        assert pruned not in IRR_SOURCE
        # rejected the moment anyone edits the value...
        with pytest.raises(ValidationError):
            validate_irr_as_set(f"{pruned}::AS-FOO", strict=True)
        # ...but a stored legacy value still validates, so retiring the registry
        # does not make the network unsaveable (the point of change-gating it)
        assert validate_irr_as_set(f"{pruned}::AS-FOO") == f"{pruned}::AS-FOO"
        # and it is not a pin the batch jobs will try to verify
        assert irr_as_set_pinned_source(f"{pruned}::AS-FOO") == (
            None,
            f"{pruned}::AS-FOO",
        )


@pytest.mark.django_db
def test_zero_usage_sources_were_deliberately_kept():
    """
    Guards the reasoning, not just the list. BELL / CANARIE / REACH also have no
    PeeringDB usage, but zero usage is not evidence a registry is gone and their
    dumps were never measured — so they stay until someone measures them. Without
    this test the next reader sees an arbitrary-looking prune and "tidies up".
    """
    for kept in ("BELL", "CANARIE", "REACH"):
        assert kept in IRR_SOURCE
        validate_irr_as_set(f"{kept}::AS-FOO")


@pytest.mark.django_db
def test_bulk_dump_sources_track_irr_source():
    """
    The two lists must be pruned together: build_index filters to set(IRR_SOURCE),
    so a dump source left behind costs a download and contributes nothing — and
    dump_health would still demand it, which blocks pdb_irr_as_set_cleanup --commit.
    """
    for spec in DUMP_SOURCES:
        assert spec["name"] in IRR_SOURCE, (
            f"{spec['name']} has a dump but is not in IRR_SOURCE, so its dump is "
            "downloaded and then discarded by build_index"
        )


@pytest.mark.django_db
def test_retired_source_does_not_block_an_unrelated_edit():
    """
    The failure mode change-gating exists to prevent (#1973): Network.clean()
    validates irr_as_set on every save, so an unconditional unknown-source check
    would mean a network holding a retired registry's prefix could not update its
    phone number until it fixed the as-set.
    """
    org = Organization.objects.create(name="Retired Source Org", status="ok")
    net = Network.objects.create(
        name="Legacy Net",
        asn=64497,
        irr_as_set="NESTEGG::AS-LEGACY",
        status="ok",
        org=org,
    )

    net.website = "https://example.com"
    net.full_clean()  # must not raise
    net.save()

    net.refresh_from_db()
    # the legacy prefix survives untouched -- clean() assigns the validator's
    # return value back to the field, so a rewrite here would be silent data loss
    assert net.irr_as_set == "NESTEGG::AS-LEGACY"
