"""
peeringdb model / field validators
"""

import ipaddress
import re

import phonenumbers
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.utils.translation import gettext_lazy as _
from geopy.distance import geodesic
from rest_framework.exceptions import ValidationError as RestValidationError
from schema import Schema

import peeringdb_server.geo as geo
import peeringdb_server.models
from peeringdb_server.inet import IRR_SOURCE, network_is_pdb_valid
from peeringdb_server.request import bypass_validation
from peeringdb_server.verified_update import const


def validate_email_domains(text):
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


def validate_bool(value):
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


def validate_api_rate(value):
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


def validate_social_media(value):
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
            if service in ["website"]:
                # validate URL
                try:
                    URLValidator(identifier)
                except Exception:
                    raise ValidationError(
                        _("Invalid {service} URL!").format(service=service)
                    )
            elif service in ["instagram", "x", "tiktok", "facebook", "linkedin"]:
                # validate username
                if service in ["x"]:
                    regex = r"^[a-zA-Z0-9_]{4,15}$"
                else:
                    regex = r"^(-*)(?=.{4,32}$)(?![.\-])(?!.*[.]{2})[a-zA-Z0-9._\-]+(?<![.])$"

                matches = re.search(regex, identifier)
                if not matches:
                    raise ValidationError(
                        _("Invalid {service} username!").format(service=service)
                    )
            elif not service:
                # service can't be None and empty.
                raise ValidationError(_("Invalid service!"))
            elif not identifier:
                # identifier can't be None and empty.
                raise ValidationError(_("Invalid identifier!"))
    return value


def validate_website_override(website, org_website):
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


def validate_verified_update_data(ref_tag, obj_id, data):
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
    model = peeringdb_server.models.REFTAG_MAP[ref_tag]
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


def validate_asn_prefix(asn):
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


def validate_latitude(latitude):
    try:
        value = float(latitude)
        is_valid = -90 <= value <= 90
    except ValueError:
        is_valid = False
    if not is_valid:
        raise ValidationError({"latitude": f"Invalid {latitude} latitude!"})
    return value


def validate_longitude(longitude):
    try:
        value = float(longitude)
        is_valid = -180 <= value <= 180
    except ValueError:
        is_valid = False
    if not is_valid:
        raise ValidationError({"longitude": f"Invalid {longitude} longitude!"})
    return value


def validate_distance_geocode(current_geocode, new_geocode, current_city, new_city):
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
        city_geocode = ()
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
