"""
Assorted utility functions for peeringdb site templates.
"""
import ipaddress
from decimal import Decimal

from django.conf import settings
from django_grainy.util import Permissions, check_permissions, get_permissions  # noqa
from grainy.core import NamespaceKeyApplicator

from peeringdb_server.permissions import APIPermissionsApplicator


def disable_auto_now_and_save(entity):
    updated_field = entity._meta.get_field("updated")
    updated_field.auto_now = False
    entity.save()
    updated_field.auto_now = True


def round_decimal(value, places):
    if value is not None:
        return value.quantize(Decimal(10) ** -places)
    return value


def coerce_ipaddr(value):
    """
    ipaddresses can have multiple formats that are equivalent.
    This function will standardize a ipaddress string.

    Note: this function is not a validator. If it errors
    It will return the original string.
    """
    try:
        value = str(ipaddress.ip_address(value))
    except ValueError:
        pass
    return value
