# settings for unit / integration test environment used
# by run_tests command

SERVER_EMAIL = "pdb@localhost"

SECRET_KEY = "tests"

# Keys


GOOGLE_GEOLOC_API_KEY = "AIzatest"
RDAP_LACNIC_APIKEY = ""
RDAP_SELF_BOOTSTRAP = False
RECAPTCHA_PUBLIC_KEY = ""
RECAPTCHA_SECRET_KEY = ""
DESKPRO_KEY = ""
DESKPRO_URL = ""
OIDC_RSA_PRIVATE_KEY_ACTIVE_PATH = ""

BASE_URL = "https://localhost"
PASSWORD_RESET_URL = "localhost"
DATABASE_ROUTERS = ["peeringdb_server.db_router.TestRouter"]
SUGGEST_ENTITY_ORG = 1234
API_CACHED_ENABLED = False
NSP_GUEST_GROUP = "guest"
NSP_USER_GROUP = "user"
IXF_POSTMORTEM_LIMIT = 250
IXF_NOTIFY_IX_ON_CONFLICT = True
IXF_NOTIFY_NET_ON_CONFLICT = True
IXF_TICKET_ON_CONFLICT = True
MAX_USER_AFFILIATION_REQUESTS = 10
MAIL_DEBUG = True
IXF_PARSE_ERROR_NOTIFICATION_PERIOD = 36
IXF_IMPORTER_DAYS_UNTIL_TICKET = 6
IXF_REMOVE_STALE_NETIXLAN_PERIOD = 90
IXF_SEND_TICKETS = False
TUTORIAL_MODE = False
CAPTCHA_TEST_MODE = True
GLOBAL_STATS_CACHE_DURATION = 0
CLIENT_COMPAT = {
    "client": {"min": (0, 6), "max": (0, 6, 5)},
    "backends": {"django_peeringdb": {"min": (0, 6), "max": (0, 6, 5)}},
}

RATELIMITS = {
    "view_affiliate_to_org_POST": "100/m",
    "resend_confirmation_mail": "2/m",
    "view_request_ownership_GET": "3/m",
    "view_username_retrieve_initiate": "2/m",
    "view_request_ownership_POST": "3/m",
    "request_login_POST": "10/m",
    "view_verify_POST": "2/m",
    "request_translation": "10/m",
    "view_import_ixlan_ixf_preview": "1/m",
    "view_import_net_ixf_postmortem": "1/m",
    "view_verified_update_POST": "3/m",
    "view_verified_update_accept_POST": "4/m",
}

GUEST_GROUP_ID = 1
USER_GROUP_ID = 2
WHOOSH_STORAGE = "ram"
ELASTICSEARCH_DSL_AUTOSYNC = False
ELASTICSEARCH_DSL_AUTO_REFRESH = False
IXF_REMOVE_STALE_NETIXLAN = True

CACHES["negative"] = {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "negative",
}
CACHES["session"] = {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "session",
}
CACHES["default"] = {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "default",
}
CACHES["error_emails"] = {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "error_emails",
}

# set to high amount so we dont trigger it during tests
NEGATIVE_CACHE_REPEATED_RATE_LIMIT = 10000000
