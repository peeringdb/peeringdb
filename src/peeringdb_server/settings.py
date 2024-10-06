"""
(Being DEPRECATED) django settings preparation.

This is mostly DEPRECATED at this point and any new settings should be directly
defined in mainsite/settings.
"""

from django.conf import settings

PEERINGDB_VERSION = getattr(settings, "PEERINGDB_VERSION", "")

# TODO - move these out of peeringdb.settings
RDAP_URL = getattr(settings, "PEERINGDB_RDAP_URL", "https://rdap.db.ripe.net/")
RDAP_LACNIC_APIKEY = getattr(settings, "PEERINGDB_RDAP_LACNIC_APIKEY", None)
RDAP_RECURSE_ROLES = getattr(
    settings, "PEERINGDB_RDAP_RECURSE_ROLES", ["administrative", "technical"]
)
RDAP_SELF_BOOTSTRAP = getattr(settings, "RDAP_SELF_BOOTSTRAP")
RDAP_BOOTSTRAP_DIR = getattr(settings, "RDAP_BOOTSTRAP_DIR")
RDAP_IGNORE_RECURSE_ERRORS = getattr(settings, "RDAP_IGNORE_RECURSE_ERRORS")

TUTORIAL_MODE = getattr(settings, "TUTORIAL_MODE", False)
RELEASE_ENV = getattr(settings, "RELEASE_ENV", "dev")
SHOW_AUTO_PROD_SYNC_WARNING = getattr(settings, "SHOW_AUTO_PROD_SYNC_WARNING", False)
AUTO_APPROVE_AFFILIATION = getattr(settings, "AUTO_APPROVE_AFFILIATION", False)
AUTO_VERIFY_USERS = getattr(settings, "AUTO_VERIFY_USERS", False)
MAINTENANCE_MODE_LOCKFILE = getattr(
    settings, "MAINTENANCE_MODE_LOCKFILE", "maintenance.lock"
)
