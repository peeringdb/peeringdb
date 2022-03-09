Generated from validators.py on 2022-03-07 17:01:26.860132

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
`def validate_prefix_overlap(prefix)`

Validate that a prefix does not overlap with another prefix
on an already existing ixlan.

Arguments:
    - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network

Raises:
    - ValidationError on failed validation

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