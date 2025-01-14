# Django settings

import os
import sys

import django.conf.global_settings
import django.conf.locale
import redis
import structlog
import urllib3

from mainsite.oauth2.scopes import SupportedScopes

_DEFAULT_ARG = object()


def non_zipcode_countries():
    return {
        "AE": "United Arab Emirates",
        "AG": "Antigua and Barbuda",
        "AN": "Netherlands Antilles",
        "AO": "Angola",
        "AW": "Aruba",
        "BF": "Burkina Faso",
        "BI": "Burundi",
        "BJ": "Benin",
        "BS": "Bahamas",
        "BW": "Botswana",
        "BZ": "Belize",
        "CD": "Congo, the Democratic Republic of the",
        "CF": "Central African Republic",
        "CG": "Congo",
        "CI": "Cote d'Ivoire",
        "CK": "Cook Islands",
        "CM": "Cameroon",
        "DJ": "Djibouti",
        "DM": "Dominica",
        "ER": "Eritrea",
        "FJ": "Fiji",
        "GD": "Grenada",
        "GH": "Ghana",
        "GM": "Gambia",
        "GN": "Guinea",
        "GQ": "Equatorial Guinea",
        "GY": "Guyana",
        "HK": "Hong Kong",
        "IE": "Ireland",
        "JM": "Jamaica",
        "KE": "Kenya",
        "KI": "Kiribati",
        "KM": "Comoros",
        "KN": "Saint Kitts and Nevis",
        "KP": "North Korea",
        "LC": "Saint Lucia",
        "ML": "Mali",
        "MO": "Macao",
        "MR": "Mauritania",
        "MS": "Montserrat",
        "MU": "Mauritius",
        "MW": "Malawi",
        "NR": "Nauru",
        "NU": "Niue",
        "PA": "Panama",
        "QA": "Qatar",
        "RW": "Rwanda",
        "SB": "Solomon Islands",
        "SC": "Seychelles",
        "SL": "Sierra Leone",
        "SO": "Somalia",
        "SR": "Suriname",
        "ST": "Sao Tome and Principe",
        "SY": "Syria",
        "TF": "French Southern Territories",
        "TK": "Tokelau",
        "TL": "Timor-Leste",
        "TO": "Tonga",
        "TT": "Trinidad and Tobago",
        "TV": "Tuvalu",
        "TZ": "Tanzania, United Republic of",
        "UG": "Uganda",
        "VU": "Vanuatu",
        "YE": "Yemen",
        "ZA": "South Africa",
        "ZW": "Zimbabwe",
    }


def print_debug(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


def get_locale_name(code):
    """Gets the readble name for a locale code."""
    language_map = dict(django.conf.global_settings.LANGUAGES)

    # check for exact match
    if code in language_map:
        return language_map[code]

    # try for the language, fall back to just using the code
    language = code.split("-")[0]
    return language_map.get(language, code)


def set_from_env(name, default=_DEFAULT_ARG):
    return _set_from_env(name, globals(), default)


def _set_from_env(name, context, default):
    """
    Sets a global variable from a environment variable of the same name.

    This is useful to leave the option unset and use Django's default
    (which may change).
    """
    if default is _DEFAULT_ARG and name not in os.environ:
        return

    context[name] = os.environ.get(name, default)


def set_option(name, value, envvar_type=None):
    return _set_option(name, value, globals(), envvar_type)


def _set_option(name, value, context, envvar_type=None):
    """
    Sets an option, first checking for env vars,
    then checking for value already set,
    then going to the default value if passed.
    Environment variables are always strings, but
    we try to coerce them to the correct type first by checking
    the type of the default value provided. If the default
    value is None, then we check the optional envvar_type arg.
    """

    # If value is in True or False we
    # call set_bool to take advantage of
    # its type checking for environment variables
    if isinstance(value, bool):
        _set_bool(name, value, context)
        return

    # If value is a list call set_list
    if isinstance(value, list):
        _set_list(name, value, context)
        return

    if value is not None:
        envvar_type = type(value)
    else:
        # If value is None, we'll use the provided envvar_type, if it is not None
        if envvar_type is None:
            raise ValueError(
                f"If no default value is provided for the setting {name} the envvar_type argument must be set."
            )

    if name in os.environ:
        env_var = os.environ.get(name)
        # Coerce type based on provided value
        context[name] = envvar_type(env_var)
    # If the environment variable isn't set
    else:
        _set_default(name, value, context)


def set_bool(name, value):
    return _set_bool(name, value, globals())


def _set_bool(name, value, context):
    """Sets and option, first checking for env vars, then checking for value already set, then going to the default value if passed."""
    if name in os.environ:
        envval = os.environ.get(name).lower()
        if envval in ["1", "true", "y", "yes"]:
            context[name] = True
        elif envval in ["0", "false", "n", "no"]:
            context[name] = False
        else:
            raise ValueError(f"{name} is a boolean, cannot match '{os.environ[name]}'")

    _set_default(name, value, context)


def _set_list(name, value, context):
    """
    For list types we split the env variable value using a comma as a delimiter
    """

    if name in os.environ:
        context[name] = os.environ.get(name).lower().split(",")

    _set_default(name, value, context)


def set_default(name, value):
    return _set_default(name, value, globals())


def _set_default(name, value, context):
    """Sets the default value for the option if it's not already set."""
    if name not in context:
        context[name] = value


def try_include(filename):
    """Tries to include another file from the settings directory."""
    print_debug(f"including {filename} {RELEASE_ENV}")
    try:
        with open(filename) as f:
            exec(compile(f.read(), filename, "exec"), globals())

        print_debug(f"loaded additional settings file '{filename}'")

    except FileNotFoundError:
        print_debug(f"additional settings file '{filename}' was not found, skipping")


def read_file(name):
    with open(name) as fh:
        return fh.read()


def set_from_file(name, path, default=_DEFAULT_ARG, envvar_type=None):
    try:
        value = read_file(path).strip()
    except OSError:
        value = default

    set_option(name, value, envvar_type)


def can_ping_redis(host, port, password):
    """
    Check if Redis is available.
    """
    client = redis.StrictRedis(host=host, port=port, password=password)
    try:
        return client.ping()
    except redis.ConnectionError:
        return False


def get_cache_backend(cache_name):
    """
    Function to get cache backend based on environment variable.
    """
    cache_backend = globals().get(f"{cache_name.upper()}_CACHE_BACKEND", "RedisCache")

    options = {}

    if cache_name == "error_emails":
        options["MAX_ENTRIES"] = 2
    elif cache_name == "default":
        options["MAX_ENTRIES"] = CACHE_MAX_ENTRIES
        options["CULL_FREQUENCY"] = 10

    if cache_backend == "RedisCache":
        print_debug(f"Checking if Redis is available for {cache_name}")
        if can_ping_redis(REDIS_HOST, REDIS_PORT, REDIS_PASSWORD):
            print_debug("Was able to ping Redis, using RedisCache")
            return {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}",
                "OPTIONS": {},
            }
        else:
            # fall back to DatabseCache if cache_name is sessions else
            # LocMemCache
            cache_backend = (
                "DatabaseCache" if cache_name == "session" else "LocMemCache"
            )
            print_debug(
                f"Was not able to ping Redis for {cache_name}, falling back to {cache_backend}"
            )

    if cache_backend == "LocMemCache":
        return {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": cache_name,
            "OPTIONS": options,
        }

    if cache_backend == "DatabaseCache":
        return {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "django_cache",
            "OPTIONS": options,
        }

    if cache_backend.startswith("DatabaseCache."):
        _, location = cache_backend.split(".", 1)

        return {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": location.strip(),
            "OPTIONS": options,
        }


_ = lambda s: s

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# initial CACHES object so it can be used by release env specific
# setup files

CACHES = {}

# set RELEASE_ENV, usually one of dev, beta, tutor, prod
set_option("RELEASE_ENV", "dev")

if RELEASE_ENV == "dev":
    set_bool("DEBUG", True)
else:
    set_bool("DEBUG", False)

# look for mainsite/settings/${RELEASE_ENV}.py and load if it exists
env_file = os.path.join(os.path.dirname(__file__), f"{RELEASE_ENV}.py")
try_include(env_file)

print_debug(f"Release env is '{RELEASE_ENV}'")

# set version, default from /srv/www.peeringdb.com/etc/VERSION
set_option(
    "PEERINGDB_VERSION", read_file(os.path.join(BASE_DIR, "etc/VERSION")).strip()
)

MIGRATION_MODULES = {"django_peeringdb": None}

# Contact email, from address, support email
set_from_env("SERVER_EMAIL")

# Error emails are dispatched to this address
set_option("OPERATIONS_EMAIL", SERVER_EMAIL)

set_from_env("SECRET_KEY")

# database
set_option("DATABASE_ENGINE", "mysql")
set_option("DATABASE_HOST", "127.0.0.1")
set_option("DATABASE_PORT", "")
set_option("DATABASE_NAME", "peeringdb")
set_option("DATABASE_USER", "peeringdb")
set_option("DATABASE_PASSWORD", "")

# redis
set_option("REDIS_HOST", "127.0.0.1")
set_option("REDIS_PORT", "6379")
set_from_env("REDIS_PASSWORD", "")

# API Cache
set_option("API_CACHE_ENABLED", True)
set_option("API_CACHE_ROOT", os.path.join(BASE_DIR, "api-cache"))
set_option("API_CACHE_LOG", os.path.join(BASE_DIR, "var/log/api-cache.log"))

# KMZ export file
set_option("KMZ_EXPORT_FILE", os.path.join(API_CACHE_ROOT, "peeringdb.kmz"))
set_option("KMZ_DOWNLOAD_PATH", "^export/kmz/$")
if RELEASE_ENV == "dev":
    # setting to blank means KMZ_DOWNLOAD_PATH is used instead and
    # the file is served from the local filesystem
    set_option("KMZ_DOWNLOAD_URL", "")
else:
    # setting this will override KMZ_DOWNLOAD_PATH to an absolute / external
    # url. We do this by default if the release env is not dev
    set_option("KMZ_DOWNLOAD_URL", "https://public.peeringdb.com/peeringdb.kmz")

# Keys
set_from_env("MELISSA_KEY", "")
set_from_env("GOOGLE_GEOLOC_API_KEY")

set_from_env("RDAP_LACNIC_APIKEY")

set_from_env("RECAPTCHA_PUBLIC_KEY")
set_from_env("RECAPTCHA_SECRET_KEY")

set_from_env("DESKPRO_KEY")
set_from_env("DESKPRO_URL")

set_from_env(
    "OIDC_RSA_PRIVATE_KEY_ACTIVE_PATH", os.path.join(API_CACHE_ROOT, "keys", "oidc.key")
)

# Google tags

# Analytics

set_option("GOOGLE_ANALYTICS_ID", "")

# Limits

API_THROTTLE_ENABLED = True
set_option("API_THROTTLE_RATE_ANON", "100/second")
set_option("API_THROTTLE_RATE_USER", "100/second")
set_option("API_THROTTLE_RATE_FILTER_DISTANCE", "10/minute")
set_option("API_THROTTLE_IXF_IMPORT", "1/minute")

# Configuration for melissa request rate limiting in the api (#1124)

set_option("API_THROTTLE_MELISSA_ENABLED_ADMIN", False)
set_option("API_THROTTLE_MELISSA_RATE_ADMIN", "10/minute")

set_option("API_THROTTLE_MELISSA_ENABLED_USER", False)
set_option("API_THROTTLE_MELISSA_RATE_USER", "10/minute")

set_option("API_THROTTLE_MELISSA_ENABLED_ORG", False)
set_option("API_THROTTLE_MELISSA_RATE_ORG", "10/minute")

set_option("API_THROTTLE_MELISSA_ENABLED_IP", False)
set_option("API_THROTTLE_MELISSA_RATE_IP", "1/minute")

# configuration for write request limiting in the api (#1322)

set_option("API_THROTTLE_RATE_WRITE", "100/minute")

# Configuration for response-size rate limiting in the api (#1126)


# Anonymous (ip-address) - Size threshold (bytes, default = 1MB)
set_option("API_THROTTLE_REPEATED_REQUEST_THRESHOLD_IP", 1000000)
# Anonymous (ip-address) - Rate limit
set_option("API_THROTTLE_REPEATED_REQUEST_RATE_IP", "10/minute")
# Anonymous (ip-address) - On/Off toggle
set_option("API_THROTTLE_REPEATED_REQUEST_ENABLED_IP", False)


# Anonymous (cidr ipv4/24, ipv6/64) - Size threshold (bytes, default = 1MB)
set_option("API_THROTTLE_REPEATED_REQUEST_THRESHOLD_CIDR", 1000000)
# Anonymous (cidr ipv4/24, ipv6/64) - Rate limit
set_option("API_THROTTLE_REPEATED_REQUEST_RATE_CIDR", "10/minute")
# Anonymous (cidr ipv4/24, ipv6/64) - On/Off toggle
set_option("API_THROTTLE_REPEATED_REQUEST_ENABLED_CIDR", False)


# User - Size threshold (bytes, default = 1MB)
set_option("API_THROTTLE_REPEATED_REQUEST_THRESHOLD_USER", 1000000)
# User - Rate limit
set_option("API_THROTTLE_REPEATED_REQUEST_RATE_USER", "10/minute")
# User - On/Off toggle
set_option("API_THROTTLE_REPEATED_REQUEST_ENABLED_USER", False)


# Organization- Size threshold (bytes, default = 1MB)
set_option("API_THROTTLE_REPEATED_REQUEST_THRESHOLD_ORG", 1000000)
# Organization - Rate limit
set_option("API_THROTTLE_REPEATED_REQUEST_RATE_ORG", "10/minute")
# Organization - On/Off toggle
set_option("API_THROTTLE_REPEATED_REQUEST_ENABLED_ORG", False)

# Expected repeated requests are cached for n seconds (default = 31 days)
set_option("API_THROTTLE_REPEATED_REQUEST_CACHE_EXPIRY", 86400 * 31)


# spatial queries require user auth
set_option("API_DISTANCE_FILTER_REQUIRE_AUTH", True)

# spatial queries required verified user
set_option("API_DISTANCE_FILTER_REQUIRE_VERIFIED", True)

# specifies the expiry period of cached geo-coordinates
# in seconds (default 30days)
set_option("GEOCOORD_CACHE_EXPIRY", 86400 * 30)

# maximum value to allow in network.info_prefixes4
set_option("DATA_QUALITY_MAX_PREFIX_V4_LIMIT", 1200000)

# maximum value to allow in network.info_prefixes6
set_option("DATA_QUALITY_MAX_PREFIX_V6_LIMIT", 180000)

# minimum value to allow for prefix length on a v4 prefix
set_option("DATA_QUALITY_MIN_PREFIXLEN_V4", 18)

# maximum value to allow for prefix length on a v4 prefix
set_option("DATA_QUALITY_MAX_PREFIXLEN_V4", 28)

# minimum value to allow for prefix length on a v6 prefix
set_option("DATA_QUALITY_MIN_PREFIXLEN_V6", 64)

# maximum value to allow for prefix length on a v6 prefix
set_option("DATA_QUALITY_MAX_PREFIXLEN_V6", 116)

# maximum value to allow for irr set hierarchy depth
set_option("DATA_QUALITY_MAX_IRR_DEPTH", 3)

# minimum value to allow for speed on an netixlan (currently 100Mbit)
set_option("DATA_QUALITY_MIN_SPEED", 100)

# maximum value to allow for speed on an netixlan (currently 5Tbit)
set_option("DATA_QUALITY_MAX_SPEED", 5000000)

# validate parent status when saving objects (e.g., ensure an active object cannot have a deleted parent)
# this SHOULD BE ENABLED in 99% of cases
# developers may disable before running pdb_load if the sync source has broken parent -> child status relationships
set_option("DATA_QUALITY_VALIDATE_PARENT_STATUS", True)

set_option(
    "RATELIMITS",
    {
        "request_login_POST": "4/m",
        "request_translation": "2/m",
        "resend_confirmation_mail": "2/m",
        "view_request_ownership_POST": "3/m",
        "view_request_ownership_GET": "3/m",
        "view_affiliate_to_org_POST": "3/m",
        "view_verify_POST": "2/m",
        "view_username_retrieve_initiate": "2/m",
        "view_import_ixlan_ixf_preview": "1/m",
        "view_import_net_ixf_postmortem": "1/m",
        "view_verified_update_POST": "3/m",
        "view_verified_update_accept_POST": "4/m",
    },
)

# maximum number of affiliation requests a user can have pending
set_option("MAX_USER_AFFILIATION_REQUESTS", 5)

# Determines age of network contact objects that get hard deleted
# during `pdb_delete_poc` execution. (days)
set_option("POC_DELETION_PERIOD", 30)

# Sets maximum age for a user-request in the verification queue
# Otherwise we delete with the pdb_cleanup_vq tool
set_option("VQUEUE_USER_MAX_AGE", 90)

# NEGATIVE CACHE

# 401 - unauthorized - 1 minute
set_option("NEGATIVE_CACHE_EXPIRY_401", 60)

# 403 - forbidden - 10 seconds (permission check failure)
# it is recommended to keep this low as some permission checks
# on write (POST, PUT) requests check the payload to determine
# permission namespaces
set_option("NEGATIVE_CACHE_EXPIRY_403", 10)

# 429 - too many requests - 10 seconds
# recommended to keep this low as to not interfer with the
# REST api rate limiting that is already in place which includes
# a timer as to when the rate limit will reset - the negative
# cache will be on top of that and will obscure the accurate
# rate limit reset time
set_option("NEGATIVE_CACHE_EXPIRY_429", 10)

# inactive users and inactive keys - 1 hour
set_option("NEGATIVE_CACHE_EXPIRY_INACTIVE_AUTH", 3600)

# throttled negative cache for repeated 401/403s (X per minute)
set_option("NEGATIVE_CACHE_REPEATED_RATE_LIMIT", 10)

# global on / off switch for negative cache
set_option("NEGATIVE_CACHE_ENABLED", True)


# Django config

ALLOWED_HOSTS = ["*"]
SITE_ID = 1

TIME_ZONE = "UTC"
USE_TZ = True

ADMINS = [
    ("Operations", OPERATIONS_EMAIL),
]
MANAGERS = ADMINS

set_option("MEDIA_ROOT", os.path.abspath(os.path.join(BASE_DIR, "media")))
MEDIA_URL = f"/m/{PEERINGDB_VERSION}/"

set_option("STATIC_ROOT", os.path.abspath(os.path.join(BASE_DIR, "static")))
STATIC_URL = f"/s/{PEERINGDB_VERSION}/"

# limit error emails (2/minute)
set_option("ERROR_EMAILS_PERIOD", 60)
set_option("ERROR_EMAILS_LIMIT", 2)

# maximum number of entries in the cache
set_option("CACHE_MAX_ENTRIES", 5000)

# dont allow going below 5000 (#1151)
if CACHE_MAX_ENTRIES < 5000:
    raise ValueError("CACHE_MAX_ENTRIES needs to be >= 5000 (#1151)")


set_option("SESSION_ENGINE", "django.contrib.sessions.backends.db")

set_option("DEFAULT_CACHE_BACKEND", "DatabaseCache")
set_option("ERROR_EMAILS_CACHE_BACKEND", "LocMemCache")
set_option("NEGATIVE_CACHE_BACKEND", "RedisCache")
set_option("GEO_CACHE_BACKEND", "DatabaseCache.geo")

# only relevant if SESSION_ENGINE = "django.contrib.sessions.backends.cache"
set_option("SESSION_CACHE_ALIAS", "session")
set_option("SESSION_CACHE_BACKEND", "RedisCache")

# setup caches
cache_names = ["default", "negative", "session", "error_emails", "geo"]
for cache_name in cache_names:
    if cache_name not in CACHES:
        CACHES[cache_name] = get_cache_backend(cache_name)

# keep database connection open for n seconds
# this is defined at the module level so we can expose
# it as an environment variable
#
# it will be set again in the DATABASES configuration
# from this global
set_option("CONN_MAX_AGE", 3600)

DATABASES = {
    "default": {
        "ENGINE": f"django.db.backends.{DATABASE_ENGINE}",
        "HOST": DATABASE_HOST,
        "PORT": DATABASE_PORT,
        "NAME": DATABASE_NAME,
        "USER": DATABASE_USER,
        "PASSWORD": DATABASE_PASSWORD,
        "CONN_MAX_AGE": CONN_MAX_AGE,
        # "TEST": { "NAME": f"{DATABASE_NAME}_test" }
    },
}

# Set file logging path
set_option("LOGFILE_PATH", os.path.join(BASE_DIR, "var/log/django.log"))

if DEBUG:
    set_option("DJANGO_LOG_LEVEL", "INFO")
else:
    set_option("DJANGO_LOG_LEVEL", "ERROR")

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=structlog.threadlocal.wrap_dict(dict),
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
        },
        "color_console": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.dev.ConsoleRenderer(),
        },
        "key_value": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.KeyValueRenderer(
                key_order=["timestamp", "level", "event", "logger"]
            ),
        },
    },
    "handlers": {
        # Include the default Django email handler for errors
        # This is what you'd get without configuring logging at all.
        "mail_admins": {
            # "class": "django.utils.log.AdminEmailHandler",
            "class": "peeringdb_server.log.ThrottledAdminEmailHandler",
            # only send emails for error logs
            "level": "ERROR",
            # But the emails are plain text by default - HTML is nicer
            "include_html": True,
        },
        # Log to a text file that can be rotated by logrotate
        "logfile": {
            "class": "logging.handlers.WatchedFileHandler",
            "filename": LOGFILE_PATH,
            "formatter": "key_value",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "color_console",
            "stream": sys.stdout,
        },
        "console_json": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": sys.stdout,
        },
        "console_debug": {
            "class": "logging.StreamHandler",
            "formatter": "color_console",
            "stream": sys.stdout,
            "level": "DEBUG",
        },
    },
    "loggers": {
        # Django log
        "django": {
            "handlers": ["mail_admins", "logfile", "console_debug"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": True,
        },
        # geo normalization / geo-coding
        "peeringdb_server.geo": {
            "handlers": ["logfile"],
            "level": "INFO",
            "propagate": False,
        },
        # django-structlog specific
        "django_structlog": {
            "handlers": ["logfile"],
            "level": "DEBUG",
        },
    },
}

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "haystack",
    "django_otp",
    "django_otp.plugins.otp_static",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_email",
    "two_factor",
    "two_factor.plugins.email",
    "dal",
    "dal_select2",
    "grappelli",
    "import_export",
    "django.contrib.admin",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.facebook",
    "django_bootstrap5",
    "corsheaders",
    "crispy_forms",
    "django_countries",
    "django_inet",
    "django_grainy",
    "django_peeringdb",
    "django_tables2",
    "oauth2_provider",
    "peeringdb_server",
    "django.contrib.staticfiles",
    "django_security_keys",
    "reversion",
    "captcha",
    "django_handleref",
]

# allows us to regenerate the schema graph image for documentation
# purposes in a dev environment
if RELEASE_ENV == "dev":
    INSTALLED_APPS.append("django_extensions")


# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = (
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    "django.contrib.staticfiles.finders.FileSystemFinder",
    #    'django.contrib.staticfiles.finders.DefaultStorageFinder',
)

# List of callables that know how to import templates from various sources.
_TEMPLATE_LOADERS = (
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
    #     'django.template.loaders.eggs.Loader',
)

_TEMPLATE_CONTEXT_PROCESSORS = (
    "django.contrib.auth.context_processors.auth",
    "django.template.context_processors.debug",
    "django.template.context_processors.request",
    "django.template.context_processors.i18n",
    "django.template.context_processors.media",
    "django.template.context_processors.static",
    "django.template.context_processors.tz",
    "django.contrib.messages.context_processors.messages",
    "peeringdb_server.context_processors.theme_mode",
)

_TEMPLATE_DIRS = (os.path.join(BASE_DIR, "peeringdb_server", "templates"),)

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": _TEMPLATE_DIRS,
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": _TEMPLATE_CONTEXT_PROCESSORS,
            # "loaders" : _TEMPLATE_LOADERS
        },
    }
]

TEST_RUNNER = "django.test.runner.DiscoverRunner"
set_option("X_FRAME_OPTIONS", "DENY")
set_option("SECURE_BROWSER_XSS_FILTER", True)
set_option("SECURE_CONTENT_TYPE_NOSNIFF", True)
set_option("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
set_option("SECURE_HSTS_SECONDS", 47304000)
set_option("SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin")

set_option(
    "CSP_DEFAULT_SRC",
    [
        "'self'",
    ],
)
set_option("CSP_STYLE_SRC", ["'self'", "fonts.googleapis.com", "'unsafe-inline'"])
set_option(
    "CSP_SCRIPT_SRC",
    [
        "'self'",
        "www.google.com",
        "www.googletagmanager.com",
        "www.gstatic.com",
        "cdn.redoc.ly",
        "'unsafe-inline'",
    ],
)
set_option("CSP_FRAME_SRC", ["'self'", "www.google.com", "'unsafe-inline'"])
set_option("CSP_FONT_SRC", ["'self'", "fonts.gstatic.com"])
set_option("CSP_IMG_SRC", ["'self'", "cdn.redoc.ly", "data:"])
set_option("CSP_WORKER_SRC", ["'self'", "blob:"])
set_option(
    "CSP_CONNECT_SRC",
    [
        "*.google-analytics.com",
        "'self'",
    ],
)

MIDDLEWARE = (
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "peeringdb_server.middleware.RedisNegativeCacheMiddleware",
    "csp.middleware.CSPMiddleware",
    "peeringdb_server.middleware.PDBSessionMiddleware",
    "peeringdb_server.middleware.CacheControlMiddleware",
    "peeringdb_server.middleware.ActivateUserLocaleMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
)

AUTHENTICATION_BACKENDS = list()

PASSWORD_HASHERS = (
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
    "django.contrib.auth.hashers.SHA1PasswordHasher",
    "django.contrib.auth.hashers.MD5PasswordHasher",
    "django.contrib.auth.hashers.CryptPasswordHasher",
    "hashers_passlib.md5_crypt",
    "hashers_passlib.des_crypt",
    "hashers_passlib.bsdi_crypt",
)

ROOT_URLCONF = "mainsite.urls"

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

set_from_env("FLAG_BAD_DATA_NEEDS_AUTH", None)

# email vars should be already set from the release environment file
# override here from env if set

set_from_env("EMAIL_HOST")
set_from_env("EMAIL_PORT")
set_from_env("EMAIL_HOST_USER")
set_from_env("EMAIL_HOST_PASSWORD")
set_from_env("EMAIL_USE_TLS")

set_from_env("SESSION_COOKIE_DOMAIN", "localhost")
set_from_env("SESSION_COOKIE_SECURE")
set_option("SECURE_PROXY_SSL_HEADER", ("HTTP_X_FWD_PROTO", "https"))

DEFAULT_FROM_EMAIL = SERVER_EMAIL

OTP_EMAIL_SENDER = SERVER_EMAIL
OTP_EMAIL_SUBJECT = "One time password request"


# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = "mainsite.wsgi.application"


AUTH_USER_MODEL = "peeringdb_server.User"

GRAPPELLI_ADMIN_TITLE = "PeeringDB"

TABLE_PREFIX = "peeringdb_"
ABSTRACT_ONLY = True

LOGIN_URL = "two_factor:login"
LOGIN_REDIRECT_URL = "/"

# App config

CRISPY_TEMPLATE_PACK = "django_bootstrap5"

## django-cors-headers

# No one specific host is allow Allow-Origin at this point]
# Origin for API get request is handled via signals (signals.py)
CORS_ORIGIN_WHITELIST = []

# don't allow cookies
CORS_ALLOW_CREDENTIALS = False

# only allow for cross origin requests for GET and OPTIONS
CORS_ALLOW_METHODS = ["GET", "OPTIONS"]

## OAuth2

# allows PeeringDB to use external OAuth2 sources
set_bool("OAUTH_ENABLED", False)

# https://django-oauth-toolkit.readthedocs.io/en/latest/changelog.html#id12
# default changed to True in django-oauth-toolkit v2, set to False for now
# to avoid breaking existing clients
set_bool("PKCE_REQUIRED", False)

# enables OpenID Connect support
set_bool("OIDC_ENABLED", True)

# enables JWT signing algorithm RS256
set_from_file("OIDC_RSA_PRIVATE_KEY", OIDC_RSA_PRIVATE_KEY_ACTIVE_PATH, "", str)


AUTHENTICATION_BACKENDS += (
    # for passkey auth using security-key
    # this needs to be first so it can do some clean up
    "django_security_keys.backends.PasskeyAuthenticationBackend",
    # for OAuth provider
    "oauth2_provider.backends.OAuth2Backend",
    # for OAuth against external sources
    "allauth.account.auth_backends.AuthenticationBackend",
)

MIDDLEWARE += (
    "peeringdb_server.maintenance.Middleware",
    "peeringdb_server.middleware.CurrentRequestContext",
    "peeringdb_server.middleware.PDBCommonMiddleware",
    "peeringdb_server.middleware.PDBPermissionMiddleware",
    "oauth2_provider.middleware.OAuth2TokenMiddleware",
    "django_structlog.middlewares.RequestMiddleware",
)

OAUTH2_PROVIDER = {
    "OIDC_ENABLED": OIDC_ENABLED,
    "OIDC_RSA_PRIVATE_KEY": OIDC_RSA_PRIVATE_KEY,
    "PKCE_REQUIRED": PKCE_REQUIRED,
    "OAUTH2_VALIDATOR_CLASS": "mainsite.oauth2.validators.OIDCValidator",
    "SCOPES": {
        SupportedScopes.OPENID: "OpenID Connect scope",
        SupportedScopes.PROFILE: "user profile",
        SupportedScopes.EMAIL: "email address",
        SupportedScopes.NETWORKS: "list of user networks and permissions",
        SupportedScopes.AMR: "authentication method reference",
    },
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https"],
    "REQUEST_APPROVAL_PROMPT": "auto",
}


# override this to `peeringdb_server.OAuthApplication` once peeringdb_server
# migration 0085 has been applied.

set_option("OAUTH2_PROVIDER_APPLICATION_MODEL", "oauth2_provider.Application")
set_option("OAUTH2_PROVIDER_GRANT_MODEL", "oauth2_provider.Grant")
set_option("OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL", "oauth2_provider.AccessToken")

# This is setting is for cookie timeout for oauth sessions.
# After the timeout, the ongoing oauth session would expire.

set_option("OAUTH_COOKIE_MAX_AGE", 1800)

## grainy

AUTHENTICATION_BACKENDS += ("django_grainy.backends.GrainyBackend",)

## Django Elasticsearch DSL


set_from_env("ELASTICSEARCH_URL", "")
# same env var as used by ES server docker image
set_from_env("ELASTIC_PASSWORD", "")

if ELASTICSEARCH_URL:
    INSTALLED_APPS.append("django_elasticsearch_dsl")
    ELASTICSEARCH_DSL = {
        "default": {
            "hosts": ELASTICSEARCH_URL,
            "http_auth": ("elastic", ELASTIC_PASSWORD),
            "verify_certs": False,
        }
    }
    # stop ES from spamming about unsigned certs
    urllib3.disable_warnings()

    ELASTICSEARCH_DSL_INDEX_SETTINGS = {"number_of_shards": 1}
    ELASTICSEARCH_DSL_SIGNAL_PROCESSOR = (
        "peeringdb_server.signals.ESSilentRealTimeSignalProcessor"
    )
else:
    # disable ES

    ELASTICSEARCH_DSL_AUTOSYNC = False
    ELASTICSEARCH_DSL_AUTO_REFRESH = False

# Elasticsearch score boost configuration
set_option("ES_MATCH_PHRASE_BOOST", 10.0)
set_option("ES_MATCH_PHRASE_PREFIX_BOOST", 5.0)
set_option("ES_QUERY_STRING_BOOST", 2.0)

# Set Elasticsearch request timeout
set_option("ES_REQUEST_TIMEOUT", 30.0)

## Django Rest Framework

INSTALLED_APPS += ("rest_framework", "rest_framework_swagger", "rest_framework_api_key")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    # Use hyperlinked styles by default.
    # Only used if the `serializer_class` attribute is not set on a view.
    "DEFAULT_MODEL_SERIALIZER_CLASS": "rest_framework.serializers.HyperlinkedModelSerializer",
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly",
        "django_grainy.rest.ModelViewSetPermissions",
    ],
    "DEFAULT_RENDERER_CLASSES": ("peeringdb_server.renderers.MetaJSONRenderer",),
    "DEFAULT_SCHEMA_CLASS": "peeringdb_server.api_schema.BaseSchema",
    "EXCEPTION_HANDLER": "peeringdb_server.exceptions.rest_exception_handler",
}

if API_THROTTLE_ENABLED:
    REST_FRAMEWORK.update(
        {
            "DEFAULT_THROTTLE_CLASSES": (
                "peeringdb_server.rest_throttles.APIAnonUserThrottle",
                "peeringdb_server.rest_throttles.APIUserThrottle",
                "peeringdb_server.rest_throttles.ResponseSizeThrottle",
                "peeringdb_server.rest_throttles.FilterDistanceThrottle",
                "peeringdb_server.rest_throttles.MelissaThrottle",
                "peeringdb_server.rest_throttles.WriteRateThrottle",
            ),
            "DEFAULT_THROTTLE_RATES": {
                "anon": API_THROTTLE_RATE_ANON,
                "user": API_THROTTLE_RATE_USER,
                "filter_distance": API_THROTTLE_RATE_FILTER_DISTANCE,
                "ixf_import_request": API_THROTTLE_IXF_IMPORT,
                "response_size_ip": API_THROTTLE_REPEATED_REQUEST_RATE_IP,
                "response_size_cidr": API_THROTTLE_REPEATED_REQUEST_RATE_CIDR,
                "response_size_user": API_THROTTLE_REPEATED_REQUEST_RATE_USER,
                "response_size_org": API_THROTTLE_REPEATED_REQUEST_RATE_ORG,
                "melissa_user": API_THROTTLE_MELISSA_RATE_USER,
                "melissa_org": API_THROTTLE_MELISSA_RATE_ORG,
                "melissa_ip": API_THROTTLE_MELISSA_RATE_IP,
                "melissa_admin": API_THROTTLE_MELISSA_RATE_ADMIN,
                "write_api": API_THROTTLE_RATE_WRITE,
            },
        }
    )

## RDAP

set_bool("RDAP_SELF_BOOTSTRAP", True)
# put it under the main cache dir
set_option("RDAP_BOOTSTRAP_DIR", os.path.join(BASE_DIR, "api-cache", "rdap-bootstrap"))
set_bool("RDAP_IGNORE_RECURSE_ERRORS", True)

## PeeringDB

# TODO for tests

# from address for sponsorship emails
set_option("SPONSORSHIPS_EMAIL", SERVER_EMAIL)


set_option("API_URL", "https://www.peeringdb.com/api")
set_option("PAGE_SIZE", 250)
set_option("API_DEPTH_ROW_LIMIT", 250)

# limit results for the standard search
# (hitting enter on the main search bar)
set_option("SEARCH_RESULTS_LIMIT", 1000)

# limit results for the quick search
# (autocomplete on the main search bar)
set_option("SEARCH_RESULTS_AUTOCOMPLETE_LIMIT", 40)

# boost org,net,fac,ix matches over secondary entites (1.0 == no boost)
set_option("SEARCH_MAIN_ENTITY_BOOST", 1.5)


set_option("BASE_URL", "http://localhost")
set_option("PASSWORD_RESET_URL", os.path.join(BASE_URL, "reset-password"))

# Sets the maximum allowed length for user passwords.
set_option("MAX_LENGTH_PASSWORD", 1024)

ACCOUNT_EMAIL_CONFIRMATION_ANONYMOUS_REDIRECT_URL = "/login"
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = "/verify"
ACCOUNT_EMAIL_REQUIRED = True

# Webauthn (U2F) settings

# unique id for the relying party
set_option("WEBAUTHN_RP_ID", SESSION_COOKIE_DOMAIN)

# name of the relying party (displayed to the user)
set_option("WEBAUTHN_RP_NAME", "PeeringDB")

# webauthn origin validation
if RELEASE_ENV == "prod":
    set_option(
        "WEBAUTHN_ORIGIN",
        [
            "https://peeringdb.com",
            "https://www.peeringdb.com",
            "https://auth.peeringdb.com",
        ],
    )
else:
    set_option("WEBAUTHN_ORIGIN", [BASE_URL.rstrip("/")])


# collect webauthn device attestation
set_option("WEBAUTHN_ATTESTATION", "none")


# haystack

set_option("WHOOSH_INDEX_PATH", os.path.join(API_CACHE_ROOT, "whoosh-index"))
set_option("WHOOSH_STORAGE", "file")
HAYSTACK_CONNECTIONS = {
    "default": {
        "ENGINE": "haystack.backends.whoosh_backend.WhooshEngine",
        "PATH": WHOOSH_INDEX_PATH,
        "STORAGE": WHOOSH_STORAGE,
        "BATCH_SIZE": 40000,
    },
}


set_option("HAYSTACK_ITERATOR_LOAD_PER_QUERY", 20000)
set_option("HAYSTACK_LIMIT_TO_REGISTERED_MODELS", False)

# add user defined iso code for Kosovo
COUNTRIES_OVERRIDE = {
    "XK": _("Kosovo"),
}


# Which client config versions we support
set_option(
    "CLIENT_COMPAT",
    {
        "client": {
            "min": (0, 6),
            "max": (255, 0),
        },
        "backends": {
            "django_peeringdb": {
                "min": (3, 3, 0),
                "max": (255, 0),
            },
        },
    },
)

set_option("IXF_POSTMORTEM_LIMIT", 250)

# when encountering problems where an exchange's IX-F feed
# becomes unavilable / unparsable this setting controls
# the interval in which we communicate the issue to them (hours)
set_option("IXF_PARSE_ERROR_NOTIFICATION_PERIOD", 360)

# toggle the creation of DeskPRO tickets from IX-F importer
# conflicts
set_option("IXF_TICKET_ON_CONFLICT", True)

# send the IX-F importer generated tickets to deskpro
set_option("IXF_SEND_TICKETS", False)

# toggle the notification of exchanges via email
# for IX-F importer conflicts
set_option("IXF_NOTIFY_IX_ON_CONFLICT", False)

# toggle the notification of networks via email
# for IX-F importer conflicts
set_option("IXF_NOTIFY_NET_ON_CONFLICT", False)

# number of days of a conflict being unresolved before
# deskpro ticket is created
set_option("IXF_IMPORTER_DAYS_UNTIL_TICKET", 6)

# number of days until bad NetworkIXLan data is deleted
# regardless of ixf-automation status on the network (#1271)
set_option("IXF_REMOVE_STALE_NETIXLAN_PERIOD", 90)

# number of notifications required to the network before
# stale removal period is started (#1271)
set_option("IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT", 3)

# number of days between repeated notification of stale
# #netixlan data (#1271)
set_option("IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD", 30)

# on / off toggle for automatic stale netixlan removal
# through IX-F (#1271)
#
# default was changed to False as part of #1360
set_option("IXF_REMOVE_STALE_NETIXLAN", False)

# clean up data change notification queue by discarding
# entries older than this (7 days)
set_option("DATA_CHANGE_NOTIFY_MAX_AGE", 86400 * 7)

# data change emails will only be sent if this True
set_option("DATA_CHANGE_SEND_EMAILS", False)


# when a user tries to delete a protected object, a deskpro
# ticket is dispatched. This setting throttles repeat
# updates for the same object (hours)
#
# deskpro will sort messages with the same subject into
# the same ticket, so this is mostly to avoid ticket spam
# from users repeat-clicking the delete button
set_option("PROTECTED_OBJECT_NOTIFICATION_PERIOD", 1)

set_option("MAINTENANCE_MODE_LOCKFILE", "maintenance.lock")

# django_peeringdb settings
PEERINGDB_ABSTRACT_ONLY = True

# In a beta environment that gets sync'd from production this
# flag allows you to enable / disable showing of next sync date in
# the beta notification banner
set_option("SHOW_AUTO_PROD_SYNC_WARNING", False)

# all suggested entities will be created under this org
set_option("SUGGEST_ENTITY_ORG", 20525)
set_option("DEFAULT_SELF_ORG", 25554)
set_option("DEFAULT_SELF_NET", 666)
set_option("DEFAULT_SELF_IX", 4095)
set_option("DEFAULT_SELF_FAC", 13346)
set_option("DEFAULT_SELF_CARRIER", 66)
set_option("DEFAULT_SELF_CAMPUS", 25)
set_option("CAMPUS_MAX_DISTANCE", 50)
set_option("FACILITY_MAX_DISTANCE_GEOCODE_NOT_EXISTS", 50)
set_option("FACILITY_MAX_DISTANCE_GEOCODE_EXISTS", 1)

set_option("TUTORIAL_MODE", False)
set_option(
    "TUTORIAL_MODE_MESSAGE",
    "The tutorial environment is automatically restored from production when a new release is deployed. Any changes made here will not be permanent.",
)

#'guest' user group
GUEST_GROUP_ID = 1
set_option("GRAINY_ANONYMOUS_GROUP", "Guest")

#'user' user group
USER_GROUP_ID = 2

CSRF_FAILURE_VIEW = "peeringdb_server.views.view_http_error_csrf"

RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

# Organization logo limitations for public users
# These limits dont necessarily apply for logos submitted through
# /cp (django-admin)

set_option("ORG_LOGO_ALLOWED_FILE_TYPE", ".jpg,.jpeg,.png")

# max file size for public organization logo uploads (bytes)
set_option("ORG_LOGO_MAX_SIZE", 50 * 1024)

# max rendering height for the organization logo in net / org / fac / ix views
# does NOT affect sponsorship logo rendering (pixels)
set_option("ORG_LOGO_MAX_VIEW_HEIGHT", 75)

# Set countries that don't use zipcodes
set_option("NON_ZIPCODE_COUNTRIES", non_zipcode_countries())

## Locale

LANGUAGE_CODE = "en-us"
LANGUAGE_COOKIE_AGE = 31557600  # one year
USE_I18N = True
USE_L10N = True

LOCALE_PATHS = (os.path.join(BASE_DIR, "locale"),)

LANGUAGES = [
    #   ("ar", _("Arabic")),
    ("cs-cz", _("Czech")),
    ("de-de", _("German")),
    ("el-gr", _("Greek")),
    ("en", _("English")),
    ("es-es", _("Spanish")),
    ("fr-fr", _("French")),
    ("it", _("Italian")),
    ("ja-jp", _("Japanese")),
    #    ("ko", _("Korean")),
    ("oc", _("Occitan")),
    ("pt", _("Portuguese")),
    ("ro-ro", _("Romanian")),
    ("ru-ru", _("Russian")),
    ("zh-cn", _("Chinese (Simplified)")),
    ("zh-tw", _("Chinese (Traditional)")),
]


# enable all languages available in the locale directory
set_option("ENABLE_ALL_LANGUAGES", False)

if ENABLE_ALL_LANGUAGES:
    language_dict = dict(LANGUAGES)
    for locale_path in LOCALE_PATHS:
        for name in os.listdir(locale_path):
            path = os.path.join(locale_path, name)
            if not os.path.isdir(os.path.join(path, "LC_MESSAGES")):
                continue
            code = name.replace("_", "-").lower()
            if code not in language_dict:
                name = _(get_locale_name(code))
                language_dict[code] = name

    LANGUAGES = sorted(language_dict.items())

EXTRA_LANG_INFO = {
    "oc": {
        "bidi": False,
        "code": "oc",
        "name": "Occitan",
        "name_local": "occitan",
    },
}

# Add custom languages not provided by Django
LANG_INFO = dict(django.conf.locale.LANG_INFO, **EXTRA_LANG_INFO)
django.conf.locale.LANG_INFO = LANG_INFO


# dynamic config starts here

API_DOC_INCLUDES = {}
API_DOC_PATH = os.path.join(BASE_DIR, "docs", "api")
for _, _, files in os.walk(API_DOC_PATH):
    for file in files:
        base, ext = os.path.splitext(file)
        if ext == ".md":
            API_DOC_INCLUDES[base] = os.path.join(API_DOC_PATH, file)


set_option("MAIL_DEBUG", DEBUG)

# Setting for automated resending of failed ixf import emails
set_option("IXF_RESEND_FAILED_EMAILS", False)

# Set value for IX-F fetch timeout
set_option("IXF_FETCH_TIMEOUT", 30)

# Setting for number of days before deleting childless Organizations
set_option("ORG_CHILDLESS_DELETE_DURATION", 90)

# Grace period before an organization is processed for childless cleanup
# n days after creation
set_option("ORG_CHILDLESS_GRACE_DURATION", 1)

# Delete orphaned user accounts after n days
set_option("DELETE_ORPHANED_USER_DAYS", 90)

# Notify orphaned users n days before deletion
set_option("NOTIFY_ORPHANED_USER_DAYS", 30)

# Grace period before a newly created user can be flagged for deletion
# This is so users have some time to affiliate naturally. (days)
set_option("MIN_AGE_ORPHANED_USER_DAYS", 14)

# Setting for number of days before deleting pending user to organization affiliation requests
set_option("AFFILIATION_REQUEST_DELETE_DAYS", 90)

# Notification period to notify organizations of users missing 2FA (days)
set_option("NOTIFY_MISSING_2FA_DAYS", 30)

# pdb_validate_data cache timeout default
set_option("PDB_VALIDATE_DATA_CACHE_TIMEOUT", 3600)

# cache global stats (footer statistics) for N seconds
set_option("GLOBAL_STATS_CACHE_DURATION", 900)

# cache settings for optimal CDN use

# static Pages - pages that only update through release deployment (seconds)
set_option("CACHE_CONTROL_STATIC_PAGE", 15 * 60)

# dynamic pages - entity views
set_option("CACHE_CONTROL_DYNAMIC_PAGE", 10)

# api cache responses (seconds)
set_option("CACHE_CONTROL_API_CACHE", 15 * 60)

# api responses (seconds)
set_option("CACHE_CONTROL_API", 10)

if RELEASE_ENV == "prod":
    set_option("PDB_PREPEND_WWW", True)
else:
    set_option("PDB_PREPEND_WWW", False)

TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG

# set custom throttling message
set_option(
    "API_THROTTLE_RATE_ANON_MSG", "Request was throttled. Expected available in {time}."
)
set_option(
    "API_THROTTLE_RATE_USER_MSG", "Request was throttled. Expected available in {time}."
)

set_from_env(
    "RIR_ALLOCATION_DATA_PATH", os.path.join(API_CACHE_ROOT, "rdap-rir-status")
)

# Setting for number of days before deleting notok RIR
set_option("KEEP_RIR_STATUS", 90)

# A toggle for RIR status check
set_option("AUTO_UPDATE_RIR_STATUS", True)

set_option("RIR_ALLOCATION_DATA_CACHE_DAYS", 1)

# A toggle for read only mode
set_option("DJANGO_READ_ONLY", False)

# A toggle to skip updating the last_login on login
set_option("SKIP_LAST_LOGIN_UPDATE", False)

if DJANGO_READ_ONLY:
    INSTALLED_APPS += [
        "django_read_only",
    ]

# show last database sync
set_from_env("DATABASE_LAST_SYNC", None)


if TUTORIAL_MODE:
    EMAIL_SUBJECT_PREFIX = "[PDB TUTORIAL] "
    DISABLE_VERIFICATION_QUEUE_EMAILS = True
    DISABLE_VERIFICATION_QUEUE = True
    AUTO_APPROVE_AFFILIATION = True
    AUTO_VERIFY_USERS = True
else:
    EMAIL_SUBJECT_PREFIX = f"[{RELEASE_ENV}] "

CSRF_USE_SESSIONS = True

set_option("CSRF_TRUSTED_ORIGINS", WEBAUTHN_ORIGIN)

# A toggle for the periodic re-authentication process propagated
# by organizations (#736)
set_option("PERIODIC_REAUTH_ENABLED", True)

# Maximum amount of email addresses allowed per user
set_option("USER_MAX_EMAIL_ADDRESSES", 5)

# Authentication settings to use when syncing via pdb_load
set_option("PEERINGDB_SYNC_USERNAME", "")
set_option("PEERINGDB_SYNC_PASSWORD", "")

# If the api key is specified it will be used over the username and password
set_option("PEERINGDB_SYNC_API_KEY", "")

# peeringdb sync cache
set_option("PEERINGDB_SYNC_CACHE_URL", "https://public.peeringdb.com")
set_option("PEERINGDB_SYNC_CACHE_DIR", os.path.join(BASE_DIR, "sync-cache"))

# The default protocol used by django-allauth when generating URLs in email message to be https.
# https://docs.allauth.org/en/dev/account/configuration.html
set_option("ACCOUNT_DEFAULT_HTTP_PROTOCOL", "https")

# Geo normalization settings
set_option("GEO_COUNTRIES_WITH_STATES", ["US", "CA"])
set_option(
    "GEO_SOVEREIGN_MICROSTATES",
    [
        "AD",  # Andorra
        "LI",  # Liechtenstein
        "MC",  # Monaco
        "MT",  # Malta
        "MV",  # Maldives
        "SC",  # Seychelles
        "SG",  # Singapore
        "SM",  # San Marino
        "VA",  # Vatican City
    ],
)

print_debug(f"loaded settings for PeeringDB {PEERINGDB_VERSION} (DEBUG: {DEBUG})")
