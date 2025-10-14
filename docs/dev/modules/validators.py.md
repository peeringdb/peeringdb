Generated from validators.py on 2025-10-14 13:37:42.797475

# peeringdb_server.validators

peeringdb model / field validators

# Functions
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
`def validate_irr_as_set(value)`

Validate irr as-set string.

- the as-set/rs-set name has to conform to RFC 2622 (5.1 and 5.2)
- the source may be specified by AS-SET@SOURCE or SOURCE::AS-SET
- multiple values must be separated by either comma, space or comma followed by space

Arguments:

- value: irr as-set string

Returns:

- str: validated irr as-set string

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
