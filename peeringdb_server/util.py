"""
Assorted utility functions for peeringdb site templates.
"""
import ipaddress
from decimal import Decimal

from django.conf import settings
from django_grainy.util import Permissions, check_permissions, get_permissions  # noqa
from grainy.core import NamespaceKeyApplicator


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


class APIPermissionsApplicator(NamespaceKeyApplicator):
    @property
    def is_generating_api_cache(self):
        try:
            return getattr(settings, "GENERATING_API_CACHE", False)
        except IndexError:
            return False

    def __init__(self, user):
        super().__init__(None)
        self.permissions = Permissions(user)
        self.pset = self.permissions
        self.set_peeringdb_handlers()

        if self.is_generating_api_cache:
            self.drop_namespace_key = False

    def set_peeringdb_handlers(self):
        self.handler(
            "peeringdb.organization.*.network.*.poc_set.private", explicit=True
        )
        self.handler("peeringdb.organization.*.network.*.poc_set.users", explicit=True)
        self.handler(
            "peeringdb.organization.*.internetexchange.*", fn=self.handle_ixlan
        )

    def handle_ixlan(self, namespace, data):
        if "ixf_ixp_member_list_url" in data:
            visible = data["ixf_ixp_member_list_url_visible"].lower()
            _namespace = f"{namespace}.ixf_ixp_member_list_url.{visible}"

            perms = self.permissions.check(_namespace, 0x01, explicit=True)
            if not perms:
                del data["ixf_ixp_member_list_url"]
