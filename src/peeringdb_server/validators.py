"""
peeringdb model / field validators
"""

import ipaddress
import re
from urllib.parse import urlparse

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


def validate_info_prefixes6(value):
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


def validate_prefix_overlap(prefix, instance=None):
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
            new_prefix = ipaddress.ip_network(prefix)
            old_prefix = ipaddress.ip_network(ixpfx.prefix)

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
        instance._being_renumbered = True


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


def validate_identifier(service: str, identifier: str):
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


def validate_url(url):
    try:
        URLValidator()(url)
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"] or not parsed.netloc:
            raise ValidationError("Invalid URL: missing scheme or host.")
    except Exception:
        raise ValidationError("Invalid URL.")


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


def validate_status(value):
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
