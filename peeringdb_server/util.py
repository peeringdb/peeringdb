from grainy.const import *
from grainy.core import NamespaceKeyApplicator
from django.conf import settings
from django_grainy.const import *
from django_grainy.util import (
    get_permissions,
    check_permissions,
    Permissions
)


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
            "peeringdb.organization.*.network.*.poc_set.private",
            explicit=True
        )
        self.handler(
            "peeringdb.organization.*.network.*.poc_set.users",
            explicit=True
        )
        self.handler(
            "peeringdb.organization.*.internetexchange.*",
            fn=self.handle_ixlan
        )

    def handle_ixlan(self, namespace, data):
        if "ixf_ixp_member_list_url" in data:
            visible = data["ixf_ixp_member_list_url_visible"].lower()
            _namespace = f"{namespace}.ixf_ixp_member_list_url.{visible}"

            perms = self.permissions.check(
                _namespace, 0x01, explicit=True
            )
            if not perms:
                del data["ixf_ixp_member_list_url"]
