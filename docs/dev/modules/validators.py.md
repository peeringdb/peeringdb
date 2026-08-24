Generated from validators.py on 2026-08-15 04:17:12.049436

# peeringdb_server.validators

peeringdb model / field validators

# Functions
---

## _cap_enforced_now
`def _cap_enforced_now()`

Whether the #1974 single-set cap (IRR_AS_SET_MAX_SETS) is enforced right now.

Staged like MFA (#1810): with a hard-start date the cap rejects only on/after
it; a soft-start with no hard date is warn-only (never rejects — the
pdb_irr_as_set_notify nudge does the warning); with neither date set it is a
plain immediate cap (legacy on/off behavior).

---
## _normalize_irr_as_set
`def _normalize_irr_as_set(value)`

Canonicalize an irr_as_set value (separator/case) WITHOUT validating, so
callers can tell whether a submitted value differs from the stored one (the
#1973 change-gate). Tolerates legacy / invalid stored values by design.

---
## _verify_irr_existence
`def _verify_irr_existence(existence_checks)`

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

---
## clean_ixp_update_exclude
`def clean_ixp_update_exclude(value)`

Normalize and validate a list of IX-F field names that a network has
opted to exclude from automatic import updates (#1943).

Returns a `(cleaned_list, error_message)` tuple. `error_message` is None
when the value is valid; otherwise `cleaned_list` is empty. Callers raise
the ValidationError flavor appropriate to their layer (django vs DRF) so
this helper stays framework-agnostic - it is shared by `Network.clean()`
and `NetworkSerializer.validate_ixp_update_exclude()`.

---
## irr_as_set_pinned_source
`def irr_as_set_pinned_source(token)`

(source, name) where source is None unless the token pins a registry that
PeeringDB knows.

What the batch jobs (pdb_irr_as_set_cleanup, pdb_irr_as_set_status) mean by
"prefixed": an unrecognized prefix is not a pin anything can be verified
against, so it reads as unprefixed and the whole token stays the name.

---
## normalize_name
`def normalize_name(value)`

Collapse runs of 2+ whitespace to a single space and strip the ends - the
collapse counterpart to validate_name (which rejects). Used by the
pdb_normalize_name_whitespace backfill to fix rows that predate the
validator.

---
## split_irr_as_set_token
`def split_irr_as_set_token(token)`

(source, name) for one irr_as_set token; source is None when the token carries
no SOURCE:: prefix at all.

Shape only. A prefix naming a registry that is not in IRR_SOURCE is still
returned as a source, because validate_irr_as_set has to reject it by name
("Unknown IRR source: X") and cannot do that if the split hides it. Callers
that mean "prefixed with a registry I recognize" want
irr_as_set_pinned_source() instead.

---
## tokenize_irr_as_set
`def tokenize_irr_as_set(value, keep_empty=False)`

Split an irr_as_set value into its upper-cased set-name tokens (#1973).

The single home for this field's separator handling — comma, space, or both. The
validator, the cap and the batch jobs (pdb_irr_as_set_cleanup, the nudge in
pdb_irr_as_set_notify) must all tokenize the same way, or the warning and the
enforcement drift apart.

`keep_empty` retains the empty strings a stray separator produces, which the
validator needs so its per-token format check rejects them; every other caller
is counting or resolving real names.

---
## validate_account_name
`def validate_account_name(value)`

Validate account name (first name or last name).

Allows native character sets while blocking characters that could be
used for URL building or injection attacks.

---
## validate_address_space
`def validate_address_space(prefix)`

Validate an ip prefix according to peeringdb specs.

Arguments:
    - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network

Raises:
    - ValidationError on failed validation

---
## validate_api_rate
`def validate_api_rate(value)`

Validates a number/time-unit format used to determine rate limits

e.g., 10/second or 100/minute

Will raise a ValidationError on failure

Arguments:

- value(`str`)

Returns:

- validated value (`str`)

---
## validate_asn_prefix
`def validate_asn_prefix(asn)`

Validates a ASN prefix value

Will raise RestValidationError on failure

Arguments:

- asn(`str`)

Returns:

- status (`bool`)
- validated_value (`int`)

---
## validate_bool
`def validate_bool(value)`

Validates a boolean value

This can be passed a string for `True` or `False` or an integer as 1, 0 as well
to convert and return a boolean value

Will raise ValidationError on failure.

Arguments:

- value (`str`|`int`|`bool`)

Returns:

- validated value (`bool`)

---
## validate_django_ratelimit_rate
`def validate_django_ratelimit_rate(value)`

Validates a rate string in django-ratelimit format.

e.g., 30/m, 100/5m, 1000/h, 10/s, 800/d

Will raise a ValidationError on failure.

Arguments:

- value(`str`)

Returns:

- validated value (`str`)

---
## validate_identifier
`def validate_identifier(service, identifier)`

Validates a identifier based on the specific rules of different social media platforms.
Raises a ValueError if the identifier is invalid for the given service.

Args:
    service (str): The name of the social media service (e.g., "x", "instagram").
    identifier (str): The identifier string to validate.

Raises:
    ValueError: If the identifier does not meet the specified platform's criteria.

---
## validate_irr_as_set
`def validate_irr_as_set(value, strict=False)`

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

---
## validate_irr_as_set_on_change
`def validate_irr_as_set_on_change(value, old)`

Change-gated `irr_as_set` validation (#1973).

Apply the strict unambiguous-name rules only when `value` differs from the
stored `old` (the comparison ignores case and separator differences via
`_normalize_irr_as_set`), so legacy values keep validating on a no-op save
and the rules bite only on a genuine edit. Shared by the DRF serializer
(`NetworkSerializer.validate_irr_as_set`) and the admin form
(`NetworkAdminForm.clean_irr_as_set`) so the change-gate semantics live in
one place instead of being duplicated across those call sites.

---
## validate_name
`def validate_name(value)`

Reject `name` values with 2+ consecutive whitespace (#1984). Leading/trailing
whitespace is left to StripFieldMixin, so we check the stripped value.

---
## validate_phonenumber
`def validate_phonenumber(phonenumber, country=None)`

Validate a phonenumber to E.164

Arguments:
    - phonenumber (str)

Raises:
    - ValidationError if phone number isn't valid E.164 and cannot
    be made E.164 valid

Returns:
    - str: validated phonenumber

---
## validate_prefix
`def validate_prefix(prefix)`

Validate ip prefix.

Arguments:
    - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network

Raises:
    - ValidationError on failed validation

Returns:
    - ipaddress.ip_network instance

---
## validate_prefix_overlap
`def validate_prefix_overlap(prefix, instance=None)`

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

---
## validate_social_media
`def validate_social_media(value)`

Validates a social media value

Will raise a ValidationError on failure

Arguments:

- value(`dict`)

Returns:

- validated value (`dict`)

---
## validate_status
`def validate_status(value)`

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

---
## validate_verified_update_data
`def validate_verified_update_data(ref_tag, obj_id, data)`

Validates a VerifiedUpdate updates value

Will return a False and message on failure

Arguments:

- ref_tag(`str`)
- obj_id(`int`)
- data(`dict`)

Returns:

- status (`bool`)
- validated data (`dict`)

---
## validate_website_override
`def validate_website_override(website, org_website)`

Validates a website value

Will raise a ValidationError on failure

Arguments:

- value(`str`)

Returns:

- validated value (`str`)

---
## validate_zipcode
`def validate_zipcode(zipcode, country)`

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

---
