"""
peeringdb model / field validators
"""

import ipaddress
import phonenumbers

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from peeringdb_server.inet import network_is_pdb_valid
import peeringdb_server.models


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
        return u"{}".format(validated_number)
    except phonenumbers.phonenumberutil.NumberParseException as exc:
        raise ValidationError(_("Not a valid phone number (E.164)"))


def validate_prefix(prefix):
    """
    validate ip prefix

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
        except ValueError as exc:
            raise ValidationError(_("Invalid prefix: {}").format(prefix))
    return prefix


def validate_address_space(prefix):
    """
    validate an ip prefix according to peeringdb specs

    Arguments:
        - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network

    Raises:
        - ValidationError on failed validation
    """

    prefix = validate_prefix(prefix)

    if not network_is_pdb_valid(prefix):
        raise ValidationError(_("Address space invalid: {}").format(prefix))

    prefixlen_min = getattr(
        settings, "DATA_QUALITY_MIN_PREFIXLEN_V{}".format(prefix.version)
    )
    prefixlen_max = getattr(
        settings, "DATA_QUALITY_MAX_PREFIXLEN_V{}".format(prefix.version)
    )

    if prefix.prefixlen < prefixlen_min:
        raise ValidationError(
            _("Maximum allowed prefix length is {}").format(prefixlen_min)
        )
    elif prefix.prefixlen > prefixlen_max:
        raise ValidationError(
            _("Minimum allowed prefix length is {}").format(prefixlen_max)
        )


def validate_info_prefixes4(value):
    if value > settings.DATA_QUALITY_MAX_PREFIX_V4_LIMIT:
        raise ValidationError(
            _("Maximum value allowed {}").format(
                settings.DATA_QUALITY_MAX_PREFIX_V4_LIMIT
            )
        )
    if value < 0:
        raise ValidationError(_("Negative value not allowed"))


def validate_info_prefixes6(value):
    if value > settings.DATA_QUALITY_MAX_PREFIX_V6_LIMIT:
        raise ValidationError(
            _("Maximum value allowed {}").format(
                settings.DATA_QUALITY_MAX_PREFIX_V6_LIMIT
            )
        )

    if value < 0:
        raise ValidationError(_("Negative value not allowed"))


def validate_prefix_overlap(prefix):
    """
    validate that a prefix does not overlap with another prefix
    on an already existing ixlan

    Arguments:
        - prefix: ipaddress.IPv4Network or an ipaddress.IPv6Network

    Raises:
        - ValidationError on failed validation
    """

    prefix = validate_prefix(prefix)
    qs = peeringdb_server.models.IXLanPrefix.objects.filter(
        protocol="IPv{}".format(prefix.version), status="ok"
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
