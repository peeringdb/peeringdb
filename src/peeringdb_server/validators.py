"""
peeringdb model / field validators
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

import phonenumbers
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from geopy.distance import geodesic
from rest_framework.exceptions import ValidationError as RestValidationError
from schema import Schema

import peeringdb_server.geo as geo
import peeringdb_server.models
from peeringdb_server.inet import IRR_SOURCE, network_is_pdb_valid
from peeringdb_server.request import bypass_validation
from peeringdb_server.settings_util import get_setting_time
from peeringdb_server.verified_update import const

# Characters that could be used for URL building or injection attacks
# This blocklist approach allows native character sets while blocking dangerous characters
DANGEROUS_NAME_CHARS = re.compile(
    r'[<>{}[\]\\;|$`"~^@#%&=?!/:\d]'  # injection/URL chars and digits
    r"|"
    r"[\x00-\x1f\x7f]"  # control characters
)

# two or more consecutive whitespace characters (spaces, tabs, or mixed) - #1984
CONSECUTIVE_WHITESPACE = re.compile(r"\s{2,}")

# a token in SOURCE::NAME form. Lives here with tokenize_irr_as_set for the same
# reason: the validator and the batch jobs must agree on what a source prefix is,
# and they cannot if each carries its own copy of this.
_SOURCE_PREFIX_RE = re.compile(r"^([A-Z0-9-]+)::([A-Z0-9_:-]+)$")


def validate_email_domains(text: str | None) -> str:
    if not text:
        return ""

    lines_in = text.split("\n")
    lines_out = []
    for line in lines_in:
        if not line:
            continue

        line = line.strip()

        try:
            validate_email(f"name@{line}")
        except ValidationError:
            raise ValidationError(_("Invalid format"))

        lines_out.append(line.lower())

    return "\n".join(lines_out)


def validate_poc_visible(visible: str) -> str:
    # we no longer allow "Private" network contacts
    # however until all private network contacts have
    # been either changed or deleted we cannot remove
    # the value from the choices set for the field
    #
    # for now we handle validation here (see #944)

    if visible == "Private":
        raise ValidationError(_("Private contacts are no longer supported."))
    return visible


def validate_phonenumber(phonenumber: str, country: str | None = None) -> str:
    """
    Validate a phonenumber to E.164

    Arguments:
        - phonenumber (str)

    Raises:
        - ValidationError if phone number isn't valid E.164 and cannot
        be made E.164 valid

    Returns:
        - str: validated phonenumber
    """

    if not phonenumber:
        return ""

    try:
        parsed_number = phonenumbers.parse(phonenumber, country)
        validated_number = phonenumbers.format_number(
            parsed_number, phonenumbers.PhoneNumberFormat.E164
        )
        return f"{validated_number}"
    except phonenumbers.phonenumberutil.NumberParseException:
        raise ValidationError(_("Not a valid phone number (E.164)"))


def validate_zipcode(zipcode: str | None, country: str) -> str:
    """
    Validate a zipcode for a country. If a country has zipcodes, a zipcode
    is required. If a country does not have zipcodes, it's not required.


    Arguments:
        - zipcode (can be Str or None at this point)
        - country (two-letter country-code provided in data)
    Raises:
        - ValidationError if Zipcode is missing from a country WITH
        zipcodes
    Returns:
        - str: zipcode
    """
    if country in settings.NON_ZIPCODE_COUNTRIES:
        return ""
    else:
        if (zipcode is None) or (zipcode == ""):
            raise ValidationError(_("Input required"))
        else:
            return zipcode


def validate_account_name(value: str | None) -> str:
    """
    Validate account name (first name or last name).

    Allows native character sets while blocking characters that could be
    used for URL building or injection attacks.
    """
    if value is None:
        return ""

    value = value.strip()

    if not value:
        return ""

    if DANGEROUS_NAME_CHARS.search(value):
        raise ValidationError(
            _(
                'Names cannot contain special characters such as < > { } [ ] \\ ; | $ ` " ~ ^ @ # % & = ? ! / : or numbers.'
            )
        )

    return value


def validate_name(value: str | None) -> str | None:
    """
    Reject `name` values with 2+ consecutive whitespace (#1984). Leading/trailing
    whitespace is left to StripFieldMixin, so we check the stripped value.
    """
    if not value:
        return value

    if CONSECUTIVE_WHITESPACE.search(value.strip()):
        raise ValidationError(
            _("Name cannot contain consecutive whitespace characters.")
        )

    return value


def normalize_name(value: str | None) -> str | None:
    """
    Collapse runs of 2+ whitespace to a single space and strip the ends - the
    collapse counterpart to validate_name (which rejects). Used by the
    pdb_normalize_name_whitespace backfill to fix rows that predate the
    validator.
    """
    if not value:
        return value
    return CONSECUTIVE_WHITESPACE.sub(" ", value).strip()


def clean_ixp_update_exclude(value: object) -> tuple[list[str], str | None]:
    """
    Normalize and validate a list of IX-F field names that a network has
    opted to exclude from automatic import updates (#1943).

    Returns a `(cleaned_list, error_message)` tuple. `error_message` is None
    when the value is valid; otherwise `cleaned_list` is empty. Callers raise
    the ValidationError flavor appropriate to their layer (django vs DRF) so
    this helper stays framework-agnostic - it is shared by `Network.clean()`
    and `NetworkSerializer.validate_ixp_update_exclude()`.
    """
    valid_choices = peeringdb_server.models.IXP_UPDATE_EXCLUDE_FIELDS
    if value is None:
        return [], None
    if not isinstance(value, list):
        return [], _("Must be a list.")
    valid = {field for field, label in valid_choices}
    invalid = set(value) - valid
    if invalid:
        return [], _("Invalid field(s): %(fields)s. Valid values: %(valid)s") % {
            "fields": ", ".join(sorted(invalid)),
            "valid": ", ".join(sorted(valid)),
        }
    # de-duplicate while preserving order
    return list(dict.fromkeys(value)), None


def validate_prefix(
    prefix: str | ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """
    Validate ip prefix.

    Arguments:
        - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network

    Raises:
        - ValidationError on failed validation

    Returns:
        - ipaddress.ip_network instance
    """

    if isinstance(prefix, str):
        try:
            prefix = ipaddress.ip_network(prefix)
        except ValueError:
            raise ValidationError(_("Invalid prefix: {}").format(prefix))
    return prefix


def validate_address_space(
    prefix: str | ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> None:
    """
    Validate an ip prefix according to peeringdb specs.

    Arguments:
        - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network

    Raises:
        - ValidationError on failed validation
    """

    prefix = validate_prefix(prefix)

    if not network_is_pdb_valid(prefix):
        raise ValidationError(_("Address space invalid: {}").format(prefix))

    # bypass validation according to #741
    if bypass_validation():
        return

    prefixlen_min = getattr(settings, f"DATA_QUALITY_MIN_PREFIXLEN_V{prefix.version}")
    prefixlen_max = getattr(settings, f"DATA_QUALITY_MAX_PREFIXLEN_V{prefix.version}")

    if prefix.prefixlen < prefixlen_min:
        raise ValidationError(
            _("Maximum allowed prefix length is {}").format(prefixlen_min)
        )
    elif prefix.prefixlen > prefixlen_max:
        raise ValidationError(
            _("Minimum allowed prefix length is {}").format(prefixlen_max)
        )


def validate_info_prefixes4(value: int | None) -> int | None:
    if value is None or value == "":
        return None

    if value < 0:
        raise ValidationError(_("Negative value not allowed"))

    # bypass validation according to #741
    if bypass_validation():
        return value

    if value > settings.DATA_QUALITY_MAX_PREFIX_V4_LIMIT:
        raise ValidationError(
            _("Maximum value allowed {}").format(
                settings.DATA_QUALITY_MAX_PREFIX_V4_LIMIT
            )
        )

    return value


def validate_info_prefixes6(value: int | None) -> int | None:
    if value is None or value == "":
        return None

    if value < 0:
        raise ValidationError(_("Negative value not allowed"))

    # bypass validation according to #741
    if bypass_validation():
        return value

    if value > settings.DATA_QUALITY_MAX_PREFIX_V6_LIMIT:
        raise ValidationError(
            _("Maximum value allowed {}").format(
                settings.DATA_QUALITY_MAX_PREFIX_V6_LIMIT
            )
        )

    return value


def validate_prefix_overlap(
    prefix: str | ipaddress.IPv4Network | ipaddress.IPv6Network,
    instance: peeringdb_server.models.IXLanPrefix | None = None,
) -> None:
    """
    Validate that a prefix does not overlap with another prefix on an already existing ixlan.

    This function performs two types of validation:

    1. Cross-IXLan overlap check: Ensures the prefix doesn't overlap with any prefix
       on a different IXLan (raises ValidationError if it does).

    2. Same-IXLan renumbering: When updating an existing prefix on the same IXLan,
       allows two specific cases:
       - Shrinking: new prefix is a subnet of the old one AND all existing peer IPs
         are still covered by the new prefix
       - Growing: new prefix is a supernet of the old one

       In both cases, sets instance._being_renumbered = True for downstream handling.

    Arguments:
        - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network
        - instance (optional): IXLanPrefix instance being validated (for self-overlap skip)

    Raises:
        - ValidationError on failed validation
    """

    prefix = validate_prefix(prefix)
    protocol = f"IPv{prefix.version}"

    qs = peeringdb_server.models.IXLanPrefix.objects.filter(
        protocol=protocol, status="ok"
    ).exclude(prefix=prefix)

    being_renumbered: bool = False
    overlap_found = None

    for ixpfx in qs:
        # Skip overlap validation if same ixlan and handle special subnet case
        if instance and ixpfx.ixlan == instance.ixlan:
            # `Any`: ipaddress.ip_network() returns a IPv4Network | IPv6Network
            # union, and typeshed does not let `.subnet_of()` be called across
            # that union (each side only accepts its own family). Kept as Any.
            new_prefix: Any = ipaddress.ip_network(prefix)
            old_prefix: Any = ipaddress.ip_network(ixpfx.prefix)

            # Allow if new prefix is a subnet and covers same netixlans
            if new_prefix.subnet_of(old_prefix):
                ixlan = instance.ixlan
                ip_field = "ipaddr4" if new_prefix.version == 4 else "ipaddr6"

                netixlans = ixlan.netixlan_set.filter(status="ok")
                old_covered = {
                    n
                    for n in netixlans
                    if getattr(n, ip_field)
                    and ipaddress.ip_address(getattr(n, ip_field)) in old_prefix
                }
                new_covered = {
                    n
                    for n in netixlans
                    if getattr(n, ip_field)
                    and ipaddress.ip_address(getattr(n, ip_field)) in new_prefix
                }

                if set(old_covered).issubset(set(new_covered)):
                    being_renumbered = True
                    continue
                else:
                    raise ValidationError(
                        _(
                            "Cannot change prefix because at least one peer still uses an IP address in the original block."
                        )
                    )

            # Allow if new prefix is a subnet of old prefix
            # IN this case we dont need to check the netixlans, since the
            # new prefix contains the old prefix entirely.
            elif old_prefix.subnet_of(new_prefix):
                being_renumbered = True

            continue  # safe self-overlap in same ixlan

        # Otherwise check for prefix overlap across ixlan
        if ixpfx.prefix.overlaps(prefix):
            overlap_found = ixpfx
            break

    if overlap_found:
        raise ValidationError(
            _("Prefix overlaps with prefix {} on IXP '{}'").format(
                overlap_found.prefix, overlap_found.ixlan.ix.name
            )
        )

    if being_renumbered:
        # `being_renumbered` is only ever set inside the `if instance and ...`
        # branch above, so `instance` is guaranteed non-None here; mypy cannot
        # correlate the two conditions, hence the narrow ignore.
        instance._being_renumbered = True  # type: ignore[union-attr]


def tokenize_irr_as_set(value: str, keep_empty: bool = False) -> list[str]:
    """
    Split an irr_as_set value into its upper-cased set-name tokens (#1973).

    The single home for this field's separator handling — comma, space, or both. The
    validator, the cap and the batch jobs (pdb_irr_as_set_cleanup, the nudge in
    pdb_irr_as_set_notify) must all tokenize the same way, or the warning and the
    enforcement drift apart.

    `keep_empty` retains the empty strings a stray separator produces, which the
    validator needs so its per-token format check rejects them; every other caller
    is counting or resolving real names.
    """
    normalized = value.replace(", ", ",").replace(" ", ",")
    tokens = normalized.split(",")
    return [token.upper() for token in tokens if keep_empty or token]


def split_irr_as_set_token(token: str) -> tuple[str | None, str]:
    """
    (source, name) for one irr_as_set token; source is None when the token carries
    no SOURCE:: prefix at all.

    Shape only. A prefix naming a registry that is not in IRR_SOURCE is still
    returned as a source, because validate_irr_as_set has to reject it by name
    ("Unknown IRR source: X") and cannot do that if the split hides it. Callers
    that mean "prefixed with a registry I recognize" want
    irr_as_set_pinned_source() instead.
    """
    match = _SOURCE_PREFIX_RE.match(token)
    if match:
        return match.group(1), match.group(2)
    return None, token


def irr_as_set_pinned_source(token: str) -> tuple[str | None, str]:
    """
    (source, name) where source is None unless the token pins a registry that
    PeeringDB knows.

    What the batch jobs (pdb_irr_as_set_cleanup, pdb_irr_as_set_status) mean by
    "prefixed": an unrecognized prefix is not a pin anything can be verified
    against, so it reads as unprefixed and the whole token stays the name.
    """
    source, name = split_irr_as_set_token(token)
    if source is not None and source in IRR_SOURCE:
        return source, name
    return None, token


def _cap_enforced_now() -> bool:
    """
    Whether the #1974 single-set cap (IRR_AS_SET_MAX_SETS) is enforced right now.

    Staged like MFA (#1810): with a hard-start date the cap rejects only on/after
    it; a soft-start with no hard date is warn-only (never rejects — the
    pdb_irr_as_set_notify nudge does the warning); with neither date set it is a
    plain immediate cap (legacy on/off behavior).
    """
    soft = get_setting_time("IRR_AS_SET_CAP_SOFT_START")
    hard = get_setting_time("IRR_AS_SET_CAP_HARD_START")
    if soft is None and hard is None:
        return True
    if hard is None:
        return False
    return timezone.now() >= hard


def validate_irr_as_set(value: str, strict: bool = False) -> str:
    """
    Validate irr as-set string.

    - the as-set/rs-set name has to conform to RFC 2622 (5.1 and 5.2)
    - the source may be specified by SOURCE::AS-SET
    - multiple values must be separated by either comma, space or comma followed by space

    When `strict` (#1973) the extra "unambiguous name" rules apply, superusers
    excepted (#741): every token needs a known `SOURCE::` prefix and route-sets
    are rejected (both gated by `settings.IRR_AS_SET_REQUIRE_SOURCE`), and the
    set count is capped at `settings.IRR_AS_SET_MAX_SETS` (0 = uncapped). Pass
    `strict` only when the value changes (change-gated by the callers) so legacy
    values keep validating; the default `strict=False` is the historical
    format-only behavior.

    Under `strict` a live existence check then confirms each token's object
    actually exists in its pinned registry via the IRR lookup service (`irr.py`).
    Only a provably-absent object is rejected; when the lookup infrastructure
    cannot answer the save is accepted (fail open).

    Arguments:

    - value: irr as-set string
    - strict: apply the #1973 unambiguous-name rules

    Returns:

    - str: validated irr as-set string

    """

    if not isinstance(value, str):
        raise ValueError(_("IRR AS-SET value must be string type"))

    # superusers bypass the strict rules, as with the existing depth check (#741)
    strict_rules = strict and not bypass_validation()

    validated = []
    # (source, name) pairs to confirm live in their pinned registry (#1973)
    existence_checks = []

    # validate each set name (separator handling lives in tokenize_irr_as_set;
    # keep_empty so a stray separator still fails the format check below)
    for item in tokenize_irr_as_set(value, keep_empty=True):
        # <source>::<name>
        source, as_set = split_irr_as_set_token(item)
        if source is None:
            if not re.match(r"^[A-Z0-9_:-]+$", item):
                raise ValidationError(
                    _(
                        "Invalid formatting: {} - should be AS-SET, ASx, or SOURCE::AS-SET"
                    ).format(item)
                )

        # Change-gated like the other #1973 rules. IRR_SOURCE is pruned over time as
        # registries die, and an unconditional check here would make every value
        # naming a retired registry unsaveable through clean() -- a network could
        # not update its phone number. A newly typed unknown source is still
        # rejected, because typing one is a change. `validated` keeps the original
        # token, so a legacy value's prefix is preserved, not silently rewritten.
        if strict_rules and source and source not in IRR_SOURCE:
            raise ValidationError(_("Unknown IRR source: {}").format(source))

        # #1973: require an unambiguous SOURCE:: prefix on every token
        if strict_rules and settings.IRR_AS_SET_REQUIRE_SOURCE and not source:
            raise ValidationError(
                _(
                    "An IRR source prefix is required: {} - use SOURCE::AS-SET (e.g. RIPE::AS-EXAMPLE)"
                ).format(item)
            )

        # validate set name and as hierarchy
        as_parts = as_set.split(":")

        # validate max depth (superusers are allowed to bypass this validation, see #741)
        if (
            len(as_parts) > settings.DATA_QUALITY_MAX_IRR_DEPTH
            and not bypass_validation()
        ):
            raise ValidationError(
                _("Maximum AS-SET hierarchy depth: {}").format(
                    settings.DATA_QUALITY_MAX_IRR_DEPTH
                )
            )

        set_found = False
        types = []

        for part in as_parts:
            match_set = re.match(r"^(AS|RS)-[A-Z0-9_-]+$", part)
            match_as = re.match(r"^AS[0-9]+$", part)

            # set name found

            if match_set:
                set_found = True
                types.append(match_set.group(1))
            elif not match_as:
                raise ValidationError(
                    _(
                        "Invalid formatting: {} - should be RS-SET, AS-SET or AS123"
                    ).format(part)
                )

        if len(list(set(types))) > 1:
            raise ValidationError(
                _("All parts of an hierarchical name have to be of the same type")
            )

        if not set_found and len(as_parts) > 1:
            raise ValidationError(
                _("At least one component must be an actual set name")
            )

        # #1973: route-set (RS-*) names are no longer accepted on new updates
        if strict_rules and settings.IRR_AS_SET_REQUIRE_SOURCE and "RS" in types:
            raise ValidationError(
                _("Route-set names (RS-*) are not accepted: {}").format(item)
            )

        validated.append(item)
        if strict_rules and source:
            existence_checks.append((source, as_set))

    # #1973/#1974: cap the number of set names on a changed value. Staged like
    # MFA — the cap only rejects once its hard-start date has passed; in the soft
    # window multiple sets are still accepted (pdb_irr_as_set_notify warns of the
    # deadline). With no dates configured it is a plain immediate cap.
    max_sets = settings.IRR_AS_SET_MAX_SETS
    if strict_rules and max_sets and len(validated) > max_sets and _cap_enforced_now():
        raise ValidationError(
            _("At most {} IRR set name(s) may be listed").format(max_sets)
        )

    # On a changed value, verify each token's object actually exists in its
    # pinned registry (#1973).
    if strict_rules and settings.IRR_AS_SET_VERIFY_EXISTENCE and existence_checks:
        _verify_irr_existence(existence_checks)

    return " ".join(validated)


def _verify_irr_existence(existence_checks: list[tuple[str, str]]) -> None:
    """
    #1973 live existence check + rejection hints, split out of
    `validate_irr_as_set` to keep that function's shape manageable.

    Each entry of `existence_checks` is a `(source, name)` pair that has already
    passed format validation and carries an explicit `SOURCE::` prefix. For each,
    confirm the named object exists in its pinned registry via the IRR lookup
    service (`irr.py`). Only a provably absent object (a definitive `False` from
    the lookup pool) is rejected; when the IRR infrastructure cannot answer
    (`None`) the value is accepted and left for the periodic checker, so a
    third-party outage never locks the field.

    On rejection the error lists, per missing token, the registries that *do*
    hold the object (best effort — omitted when the lookup pool is unreachable),
    pointing the user at the correct prefix.

    The local import avoids import-time coupling and keeps format-only callers of
    `validate_irr_as_set` free of the network dependency.

    Raises ValidationError when at least one token is provably absent.
    """
    from peeringdb_server import irr

    missing = [
        (source, name)
        for source, name in existence_checks
        if irr.exists_in(source, name) is False
    ]
    if not missing:
        return

    hints = []
    for source, name in missing:
        found = irr.sources_for(name)
        if found.ok and found.sources:
            hints.append(
                _("{}::{} (found in: {})").format(
                    source, name, ", ".join(sorted(found.sources))
                )
            )
        else:
            hints.append(f"{source}::{name}")
    raise ValidationError(
        _("IRR object does not exist in the specified registry: {}").format(
            "; ".join(hints)
        )
    )


def validate_irr_as_set_on_change(value: str, old: str) -> str:
    """
    Change-gated `irr_as_set` validation (#1973).

    Apply the strict unambiguous-name rules only when `value` differs from the
    stored `old` (the comparison ignores case and separator differences via
    `_normalize_irr_as_set`), so legacy values keep validating on a no-op save
    and the rules bite only on a genuine edit. Shared by the DRF serializer
    (`NetworkSerializer.validate_irr_as_set`) and the admin form
    (`NetworkAdminForm.clean_irr_as_set`) so the change-gate semantics live in
    one place instead of being duplicated across those call sites.
    """
    strict = _normalize_irr_as_set(value) != _normalize_irr_as_set(old)
    return validate_irr_as_set(value, strict=strict)


def _normalize_irr_as_set(value: object) -> str:
    """
    Canonicalize an irr_as_set value (separator/case) WITHOUT validating, so
    callers can tell whether a submitted value differs from the stored one (the
    #1973 change-gate). Tolerates legacy / invalid stored values by design.
    """
    if not isinstance(value, str):
        return ""
    normalized = value.replace(", ", ",").replace(" ", ",")
    return " ".join(token.upper() for token in normalized.split(",") if token)


def validate_bool(value: str | int | bool) -> bool:
    """
    Validates a boolean value

    This can be passed a string for `True` or `False` or an integer as 1, 0 as well
    to convert and return a boolean value

    Will raise ValidationError on failure.

    Arguments:

    - value (`str`|`int`|`bool`)

    Returns:

    - validated value (`bool`)
    """
    try:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() == "true":
                return True
            if value.lower() == "false":
                return False
        return bool(int(value))
    except TypeError:
        raise ValidationError(_("Needs to be 'True', 'False', 1 or 0"))


def validate_api_rate(value: str) -> str:
    """
    Validates a number/time-unit format used to determine rate limits

    e.g., 10/second or 100/minute

    Will raise a ValidationError on failure

    Arguments:

    - value(`str`)

    Returns:

    - validated value (`str`)
    """

    value = str(value)
    if re.match(r"([/\d]+)\s*(?:minute|hour|seconds|day|week|month|year)", value):
        return value
    else:
        raise ValidationError(
            _(
                "Invalid setting! Acceptable value is a number followed by one of the following: minute, hour, seconds, day, week, month, year. eg (10/minute, 1/hour, 5/day, 1/week, 1/month, 1/year)"
            )
        )


def validate_django_ratelimit_rate(value: str) -> str:
    """
    Validates a rate string in django-ratelimit format.

    e.g., 30/m, 100/5m, 1000/h, 10/s, 800/d

    Will raise a ValidationError on failure.

    Arguments:

    - value(`str`)

    Returns:

    - validated value (`str`)
    """

    value = str(value)
    if not value or re.match(r"^[\d]+/[\d]*[smhd]$", value):
        return value
    else:
        raise ValidationError(
            _(
                "Invalid setting! Acceptable value is a number/period format "
                "where period is one of: s (second), m (minute), h (hour), "
                "d (day). eg (30/m, 100/h, 10/5m, 800/d)"
            )
        )


def validate_identifier(service: str, identifier: str) -> None:
    """
    Validates a identifier based on the specific rules of different social media platforms.
    Raises a ValueError if the identifier is invalid for the given service.

    Args:
        service (str): The name of the social media service (e.g., "x", "instagram").
        identifier (str): The identifier string to validate.

    Raises:
        ValueError: If the identifier does not meet the specified platform's criteria.
    """

    service = service.lower()
    is_valid = False  # Default to False, will be updated if a regex matches

    # Define regex patterns and specific rules for each service
    if service == "x":
        # X: 4-15 characters, alphanumeric and underscores only.
        is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9_]{4,15}$", identifier))

    elif service == "instagram":
        # Instagram: 1-30 characters, alphanumeric, periods, and underscores.
        # Cannot start or end with a period, and cannot have consecutive periods.
        if identifier.startswith(".") or identifier.endswith(".") or ".." in identifier:
            is_valid = False
        else:
            is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9._]{1,30}$", identifier))

    elif service == "facebook":
        # Facebook: Min 5 characters, alphanumeric and periods only.
        # Cannot start or end with a period, and cannot have consecutive periods.
        if identifier.startswith(".") or identifier.endswith(".") or ".." in identifier:
            is_valid = False
        else:
            is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9.]{5,}$", identifier))

    elif service == "tiktok":
        # TikTok: 2-24 characters, alphanumeric, periods, and underscores.
        is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9._]{2,24}$", identifier))

    elif service == "youtube":
        # YouTube (Handles): 3-30 characters, alphanumeric and periods only.
        # Cannot start or end with a period, and cannot have consecutive periods.
        if identifier.startswith(".") or identifier.endswith(".") or ".." in identifier:
            is_valid = False
        else:
            is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9._]{3,30}$", identifier))

    elif service == "linkedin":
        # LinkedIn: 5-100 characters, alphanumeric and hyphens only.
        is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9-]{5,100}$", identifier))

    elif service == "pinterest":
        # Pinterest: 3-30 characters, alphanumeric, hyphens, and underscores.
        is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9_-]{3,30}$", identifier))

    elif service == "reddit":
        # Reddit: 3-20 characters, alphanumeric and underscores only.
        is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9_]{3,20}$", identifier))

    elif service == "snapchat":
        # Snapchat: 3-15 characters, alphanumeric and hyphens only.
        is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9-]{3,15}$", identifier))

    elif service == "telegram":
        # Telegram: 5-32 characters, alphanumeric and underscores only.
        is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9_]{5,32}$", identifier))

    elif service == "bluesky":
        # Bluesky: 4-32 characters, alphanumeric (case-insensitive) and hyphens.
        # Must start and end with letter/number. No consecutive hyphens.
        if "--" in identifier:
            is_valid = False
        else:
            is_valid = bool(
                re.fullmatch(
                    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,30}[a-zA-Z0-9])?$", identifier
                )
            )

    elif service == "threads":
        # Threads: Follows Instagram's identifier rules due to integration.
        if identifier.startswith(".") or identifier.endswith(".") or ".." in identifier:
            is_valid = False
        else:
            is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9._]{1,30}$", identifier))

    # For platforms primarily used in China (Douyin, Kuaishou, Weibo),
    # their identifier rules can be more complex and may involve CJK characters.
    # A simple alphanumeric regex might not be fully comprehensive for native users.
    elif service in ["douyin", "kuaishou", "weibo"]:
        is_valid = bool(re.fullmatch(r"^[a-zA-Z0-9._-]{4,30}$", identifier))

    else:
        # If the service is not recognized, consider it an error in the input service name.
        raise ValueError(
            f"Unrecognized service: '{service}'. Cannot validate identifier."
        )

    # If after all checks, the identifier is not valid, raise an exception.
    if not is_valid:
        raise ValueError(f"Invalid identifier {identifier} for service {service}!")


def validate_url(url: str) -> None:
    try:
        URLValidator()(url)
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"] or not parsed.netloc:
            raise ValidationError("Invalid URL: missing scheme or host.")
    except Exception:
        raise ValidationError("Invalid URL.")


def validate_social_media(
    value: list[Any] | None,
) -> list[Any] | None:
    """
    Validates a social media value

    Will raise a ValidationError on failure

    Arguments:

    - value(`dict`)

    Returns:

    - validated value (`dict`)
    """
    if value:
        schema = Schema([{"service": str, "identifier": str}])
        try:
            schema.validate(value)
        except Exception:
            raise ValidationError(_("Malformed social media data."))
        service = [sc.get("service") for sc in value]
        if not len(set(service)) == len(service):
            raise ValidationError(_("Duplicate social media services set."))
        for data in value:
            service = data.get("service")
            identifier = data.get("identifier")
            if service == "":
                raise ValidationError(_("Service should not be empty!"))
            elif identifier == "":
                raise ValidationError(_("Identifier should not be empty!"))
            if service in ["website", "mastodon", "qq"]:
                # validate URL
                try:
                    validate_url(identifier)
                except Exception:
                    raise ValidationError(
                        _("Invalid {service} URL!").format(service=service)
                    )
            elif service in ["whatsapp"]:
                # validate phone number
                try:
                    validate_phonenumber(identifier)
                except Exception:
                    raise ValidationError(
                        _("Invalid {service} phone number!").format(service=service)
                    )
            elif service in [
                "bluesky",
                "douyin",
                "facebook",
                "instagram",
                "kuaishou",
                "linkedin",
                "pinterest",
                "reddit",
                "snapchat",
                "telegram",
                "threads",
                "tiktok",
                "weibo",
                "x",
                "youtube",
            ]:
                # validate username
                try:
                    validate_identifier(service, identifier)
                except ValueError as e:
                    raise ValidationError(_("{error_message}").format(error_message=e))

            elif not service:
                # service can't be None and empty.
                raise ValidationError(_("Invalid service!"))
            elif not identifier:
                # identifier can't be None and empty.
                raise ValidationError(_("Invalid identifier!"))
    return value


def validate_website_override(
    website: str | None, org_website: str | None
) -> str | None:
    """
    Validates a website value

    Will raise a ValidationError on failure

    Arguments:

    - value(`str`)

    Returns:

    - validated value (`str`)
    """
    if not website and not org_website:
        raise ValidationError({"website": ["Website required"]})
    elif not website and org_website:
        return org_website
    return website


def validate_verified_update_data(
    # `data` values are polymorphic: they arrive as strings but are coerced to
    # bool/int below, so the mapping value stays `Any`.
    ref_tag: str,
    obj_id: int,
    data: dict[str, Any],
) -> tuple[bool, str | dict[str, Any]]:
    """
    Validates a VerifiedUpdate updates value

    Will return a False and message on failure

    Arguments:

    - ref_tag(`str`)
    - obj_id(`int`)
    - data(`dict`)

    Returns:

    - status (`bool`)
    - validated data (`dict`)
    """
    if not data:
        return False, _("Data is empty")
    if ref_tag not in const.SUPPORTED_FIELDS:
        return False, _(f"Unknown object type: {ref_tag}")
    # `Any`: REFTAG_MAP maps a ref tag to a concrete Django model class, but
    # without django-stubs the mapping resolves to `type[object]`, which hides
    # the `.objects` manager and `.DoesNotExist`. Kept as Any.
    model: Any = peeringdb_server.models.REFTAG_MAP[ref_tag]
    try:
        obj = model.objects.get(id=obj_id)
    except model.DoesNotExist:
        return False, _(f"object {ref_tag}.{obj_id} not found")
    result = {}
    for field, value in data.items():
        if field not in const.SUPPORTED_FIELDS[ref_tag]:
            continue

        if not hasattr(obj, field):
            continue

        if value == "true":
            value = True
        elif value == "false":
            value = False
        else:
            try:
                value = int(value)
            except (TypeError, ValueError):
                pass
        if value != getattr(obj, field):
            result.update({field: value})
    return True, result


def validate_asn_prefix(asn: str | int) -> str:
    """
    Validates a ASN prefix value

    Will raise RestValidationError on failure

    Arguments:

    - asn(`str`)

    Returns:

    - status (`bool`)
    - validated_value (`int`)
    """
    value = str(asn)
    validated_value = re.match(r"^(asn|as|)(\d+)$", value.lower())
    if validated_value:
        return validated_value.group(2)
    else:
        raise RestValidationError({"asn": ["ASN contains invalid value"]})


def validate_latitude(latitude: str | float | int) -> float:
    try:
        value = float(latitude)
        is_valid = -90 <= value <= 90
    except ValueError:
        is_valid = False
    if not is_valid:
        raise ValidationError({"latitude": f"Invalid {latitude} latitude!"})
    return value


def validate_longitude(longitude: str | float | int) -> float:
    try:
        value = float(longitude)
        is_valid = -180 <= value <= 180
    except ValueError:
        is_valid = False
    if not is_valid:
        raise ValidationError({"longitude": f"Invalid {longitude} longitude!"})
    return value


def validate_distance_geocode(
    current_geocode: tuple[float | None, float | None] | None,
    new_geocode: tuple[float | None, float | None],
    current_city: str | None,
    new_city: str | None,
) -> tuple[float | None, float | None]:
    if (
        current_geocode
        and type(tuple)
        and all(value is not None for value in current_geocode)
        and current_city == new_city
    ):
        # When geocode already and city not change
        max_distance = settings.FACILITY_MAX_DISTANCE_GEOCODE_EXISTS
        distance = geodesic(current_geocode, new_geocode).km
        if distance > max_distance:
            message = f"exceeds the maximum distance of {max_distance}KM from the previous geocode"
            raise ValidationError({"latitude": message, "longitude": message})
    else:
        # When no geocode currently exists or city change
        gmaps = geo.GoogleMaps(settings.GOOGLE_GEOLOC_API_KEY, timeout=5)
        city_geocode: tuple = ()
        max_distance = settings.FACILITY_MAX_DISTANCE_GEOCODE_NOT_EXISTS

        try:
            result = gmaps.geocode_freeform(new_city)
            city_geocode = (result.get("lat"), result.get("lng"))
        except geo.Timeout:
            raise ValidationError(_("Geo coding timed out"))
        except geo.RequestError as exc:
            raise ValidationError(_("Geo coding failed: {}").format(exc))
        except geo.NotFound:
            raise ValidationError(_("Geo coding failed: City not found"))

        distance = geodesic(city_geocode, new_geocode).km
        if distance > max_distance:
            message = (
                f"exceeds a maximum distance of {max_distance}KM from the city center"
            )
            raise ValidationError({"latitude": message, "longitude": message})

    return new_geocode


def validate_status(value: str) -> str:
    """
    Validate that the status field only accepts allowed values.

    Valid status values are: 'ok', 'pending', 'deleted'

    This prevents the API from accepting arbitrary status values that
    can lead to data being inaccessible or cause unexpected behavior.

    Arguments:
        - value (str): The status value to validate

    Raises:
        - RestValidationError: If the status value is not in the allowed list

    Returns:
        - str: The validated status value
    """

    # Extract status values from HANDLEREF_STATUS tuple
    # HANDLEREF_STATUS is a tuple of (value, display) tuples
    allowed_statuses = [
        status[0] for status in peeringdb_server.models.HANDLEREF_STATUS
    ]

    if value not in allowed_statuses:
        raise RestValidationError(
            {
                "status": [
                    f"Invalid status value '{value}'. Allowed values are: {', '.join(allowed_statuses)}"
                ]
            }
        )
    return value
