"""
peeringdb model / field validators
"""
import ipaddress
import re

import phonenumbers
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

import peeringdb_server.models
from peeringdb_server.inet import IRR_SOURCE, network_is_pdb_valid
from peeringdb_server.request import bypass_validation


def validate_poc_visible(visible):

    # we no longer allow "Private" network contacts
    # however until all private network contacts have
    # been either changed or deleted we cannot remove
    # the value from the choices set for the field
    #
    # for now we handle validation here (see #944)

    if visible == "Private":
        raise ValidationError(_("Private contacts are no longer supported."))
    return visible


def validate_phonenumber(phonenumber, country=None):
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


def validate_zipcode(zipcode, country):
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


def validate_prefix(prefix):
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


def validate_address_space(prefix):
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


def validate_info_prefixes4(value):
    if not value:
        value = 0

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


def validate_info_prefixes6(value):

    if not value:
        value = 0

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


def validate_prefix_overlap(prefix):
    """
    Validate that a prefix does not overlap with another prefix
    on an already existing ixlan.

    Arguments:
        - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network

    Raises:
        - ValidationError on failed validation
    """

    prefix = validate_prefix(prefix)
    qs = peeringdb_server.models.IXLanPrefix.objects.filter(
        protocol=f"IPv{prefix.version}", status="ok"
    )
    qs = qs.exclude(prefix=prefix)
    for ixpfx in qs:
        if ixpfx.prefix.overlaps(prefix):
            raise ValidationError(
                _(
                    "Prefix overlaps with {}'s prefix: {}".format(
                        ixpfx.ixlan.ix.name, ixpfx.prefix
                    )
                )
            )


def validate_irr_as_set(value):
    """
    Validate irr as-set string.

    - the as-set/rs-set name has to conform to RFC 2622 (5.1 and 5.2)
    - the source may be specified by AS-SET@SOURCE or SOURCE::AS-SET
    - multiple values must be separated by either comma, space or comma followed by space

    Arguments:

    - value: irr as-set string

    Returns:

    - str: validated irr as-set string

    """

    if not isinstance(value, str):
        raise ValueError(_("IRR AS-SET value must be string type"))

    # split multiple values

    # normalize value separation to commas
    value = value.replace(", ", ",")
    value = value.replace(" ", ",")

    validated = []

    # validate
    for item in value.split(","):
        item = item.upper()
        source = None
        as_set = None

        # <name>@<source>
        parts_match = re.match(r"^([\w\d\-:]+)@([\w\d\-:]+)$", item)
        if parts_match:
            source = parts_match.group(2)
            as_set = parts_match.group(1)

        # <source>::<name>
        else:
            parts_match = re.match(r"^([\w\d\-:]+)::([\w\d\-:]+)$", item)
            if parts_match:
                source = parts_match.group(1)
                as_set = parts_match.group(2)
            else:
                sourceless_match = re.match(r"^([\w\d\-:]+)$", item)
                if not sourceless_match:
                    raise ValidationError(
                        _(
                            "Invalid formatting: {} - should be AS-SET, ASx, AS-SET@SOURCE or SOURCE::AS-SET"
                        ).format(item)
                    )
                as_set = sourceless_match.group(1)

        if source and source not in IRR_SOURCE:
            raise ValidationError(_("Unknown IRR source: {}").format(source))

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
            match_set = re.match(r"^(AS|RS)-[\w\d\-]+$", part)
            match_as = re.match(r"^(AS)[\d]+$", part)

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

        validated.append(item)

    return " ".join(validated)
