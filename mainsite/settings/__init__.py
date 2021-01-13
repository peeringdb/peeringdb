# Django settings

import os

import django.conf.global_settings


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
    """ Gets the readble name for a locale code. """
    language_map = dict(django.conf.global_settings.LANGUAGES)

    # check for exact match
    if code in language_map:
        return language_map[code]

    # try for the language, fall back to just using the code
    language = code.split("-")[0]
    return language_map.get(language, code)


def set_default(name, value):
    """ Sets the default value for the option if it's not already set. """
    if name not in globals():
        globals()[name] = value


def set_from_env(name, default=_DEFAULT_ARG):
    """
    Sets a global variable from a environment variable of the same name.

    This is useful to leave the option unset and use Django's default (which may change).
    """
    if default is _DEFAULT_ARG and name not in os.environ:
        return

    globals()[name] = os.environ.get(name, default)


def set_option(name, value):
    """ Sets an option, first checking for env vars, then checking for value already set, then going to the default value if passed. """
    if name in os.environ:
        globals()[name] = os.environ.get(name)

    if name not in globals():
        globals()[name] = value


def set_bool(name, value):
    """ Sets and option, first checking for env vars, then checking for value already set, then going to the default value if passed. """
    if name in os.environ:
        envval = os.environ.get(name).lower()
        if envval in ["1", "true", "y", "yes"]:
            globals()[name] = True
        elif envval in ["0", "false", "n", "no"]:
            globals()[name] = False
        else:
            raise ValueError(
                "{} is a boolean, cannot match '{}'".format(name, os.environ[name])
            )

    if name not in globals():
        globals()[name] = value


def try_include(filename):
    """ Tries to include another file from the settings directory. """
    print_debug(f"including {filename} {RELEASE_ENV}")
    try:
        with open(filename) as f:
            exec(compile(f.read(), filename, "exec"), globals())

        print_debug(f"loaded additional settings file '{filename}'")

    except FileNotFoundError:
        print_debug(f"additional settings file '{filename}' was not found, skipping")
        pass


def read_file(name):
    with open(name) as fh:
        return fh.read()


_ = lambda s: s

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

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

MIGRATION_MODULES={"django_peeringdb": None}

# Contact email, from address, support email
set_from_env("SERVER_EMAIL")

set_from_env("SECRET_KEY")

# database
set_option("DATABASE_ENGINE", "mysql")
set_option("DATABASE_HOST", "127.0.0.1")
set_option("DATABASE_PORT", "")
set_option("DATABASE_NAME", "peeringdb")
set_option("DATABASE_USER", "peeringdb")
set_option("DATABASE_PASSWORD", "")

# Keys

set_from_env("GOOGLE_GEOLOC_API_KEY")

set_from_env("RDAP_LACNIC_APIKEY")

set_from_env("RECAPTCHA_PUBLIC_KEY")
set_from_env("RECAPTCHA_SECRET_KEY")

set_from_env("DESKPRO_KEY")
set_from_env("DESKPRO_URL")

# Limits

API_THROTTLE_ENABLED = True
API_THROTTLE_RATE_ANON = "100/second"
API_THROTTLE_RATE_USER = "100/second"

# maximum value to allow in network.info_prefixes4
set_option("DATA_QUALITY_MAX_PREFIX_V4_LIMIT", 1000000)

# maximum value to allow in network.info_prefixes6
set_option("DATA_QUALITY_MAX_PREFIX_V6_LIMIT", 100000)

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

# maximum value to allow for speed on an netixlan (currently 1Tbit)
set_option("DATA_QUALITY_MAX_SPEED", 1000000)

set_option("RATELIMITS", {
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
})

# maximum number of affiliation requests a user can have pending
set_option("MAX_USER_AFFILIATION_REQUESTS", 5)

# Determines age of network contact objects that get hard deleted
# during `pdb_delete_poc` execution. (days)
set_option("POC_DELETION_PERIOD", 30)

# Sets maximum age for a user-request in the verification queue
# Otherwise we delete with the pdb_cleanup_vq tool
set_option("VQUEUE_USER_MAX_AGE", 90)

# Django config

ALLOWED_HOSTS = ["*"]
SITE_ID = 1

TIME_ZONE = "UTC"
USE_TZ = True

ADMINS = ("Support", SERVER_EMAIL)
MANAGERS = ADMINS

MEDIA_ROOT = os.path.abspath(os.path.join(BASE_DIR, "media"))
MEDIA_URL = f"/m/{PEERINGDB_VERSION}/"

STATIC_ROOT = os.path.abspath(os.path.join(BASE_DIR, "static"))
STATIC_URL = f"/s/{PEERINGDB_VERSION}/"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
        "OPTIONS": {
            # maximum number of entries in the cache
            "MAX_ENTRIES": 5000,
            # once max entries are reach delete 500 of the oldest entries
            "CULL_FREQUENCY": 10,
        },
    }
}

DATABASES = {
    "default": {
        "ENGINE": f"django.db.backends.{DATABASE_ENGINE}",
        "HOST": DATABASE_HOST,
        "PORT": DATABASE_PORT,
        "NAME": DATABASE_NAME,
        "USER": DATABASE_USER,
        "PASSWORD": DATABASE_PASSWORD,
       # "TEST": { "NAME": f"{DATABASE_NAME}_test" }
    },
}


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        # Include the default Django email handler for errors
        # This is what you'd get without configuring logging at all.
        "mail_admins": {
            "class": "django.utils.log.AdminEmailHandler",
            "level": "ERROR",
            # But the emails are plain text by default - HTML is nicer
            "include_html": True,
        },
        # Log to a text file that can be rotated by logrotate
        "logfile": {
            "class": "logging.handlers.WatchedFileHandler",
            "filename": os.path.join(BASE_DIR, "var/log/django.log"),
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        # Again, default Django configuration to email unhandled exceptions
        "django.request": {
            "handlers": ["mail_admins"],
            "level": "ERROR",
            "propagate": True,
        },
        # Might as well log any errors anywhere else in Django
        "django": {
            #            'handlers': ['console', 'logfile'],
            #            'level': 'DEBUG',
            "handlers": ["logfile"],
            "level": "ERROR",
            "propagate": False,
        },
        # Your own app - this assumes all your logger names start with "myapp."
        "": {
            "handlers": ["logfile"],
            "level": "WARNING",  # Or maybe INFO or DEBUG
            "propagate": False,
        },
    },
}
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_static",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_email",
    "two_factor",
    "dal",
    "dal_select2",
    "grappelli",
    "django.contrib.admin",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.facebook",
    "bootstrap3",
    "corsheaders",
    "crispy_forms",
    "django_countries",
    "django_inet",
    "django_namespace_perms",
    "django_peeringdb",
    "django_tables2",
    "oauth2_provider",
    "peeringdb_server",
    "reversion",
    "captcha",
    "django_handleref",
]

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

MIDDLEWARE = (
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
CONN_MAX_AGE = 3600


# email vars should be already set from the release environment file
# override here from env if set
set_from_env("EMAIL_HOST")
set_from_env("EMAIL_PORT")
set_from_env("EMAIL_HOST_USER")
set_from_env("EMAIL_HOST_PASSWORD")
set_from_env("EMAIL_USE_TLS")

set_from_env("SESSION_COOKIE_DOMAIN")
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

CRISPY_TEMPLATE_PACK = "bootstrap3"

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
set_option("OAUTH_ENABLED", False)

AUTHENTICATION_BACKENDS += (
    # for OAuth provider
    "oauth2_provider.backends.OAuth2Backend",
    # for OAuth against external sources
    "allauth.account.auth_backends.AuthenticationBackend",
)

MIDDLEWARE += (
    "peeringdb_server.maintenance.Middleware",
    "oauth2_provider.middleware.OAuth2TokenMiddleware",
)

OAUTH2_PROVIDER = {
    "SCOPES": {
        "profile": "user profile",
        "email": "email address",
        "networks": "list of user networks and permissions",
    },
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https"],
    "REQUEST_APPROVAL_PROMPT": "auto",
}


## NSP

NSP_MODE = "crud"
AUTHENTICATION_BACKENDS += ("django_namespace_perms.auth.backends.NSPBackend",)


## Django Rest Framework

INSTALLED_APPS += ("rest_framework", "rest_framework_swagger")

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
    # Handle rest of permissioning via django-namespace-perms
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly",
        "django_namespace_perms.rest.BasePermission",
    ],
    "DEFAULT_RENDERER_CLASSES": ("peeringdb_server.renderers.MetaJSONRenderer",),
    "DEFAULT_SCHEMA_CLASS": "peeringdb_server.api_schema.BaseSchema",
}

if API_THROTTLE_ENABLED:
    REST_FRAMEWORK.update(
        {
            "DEFAULT_THROTTLE_CLASSES": (
                "rest_framework.throttling.AnonRateThrottle",
                "rest_framework.throttling.UserRateThrottle",
            ),
            "DEFAULT_THROTTLE_RATES": {
                "anon": API_THROTTLE_RATE_ANON,
                "user": API_THROTTLE_RATE_USER,
            },
        }
    )

## RDAP

set_option("RDAP_SELF_BOOTSTRAP", True)
# put it under the main cache dir
set_option("RDAP_BOOTSTRAP_DIR", os.path.join(BASE_DIR, "api-cache", "rdap-bootstrap"))


## PeeringDB

# TODO for tests

# from address for sponsorship emails
set_option("SPONSORSHIPS_EMAIL", SERVER_EMAIL)


set_option("API_URL", "https://peeringdb.com/api")
set_option("API_DEPTH_ROW_LIMIT",250)
set_option("API_CACHE_ENABLED",  True)
set_option("API_CACHE_ROOT", os.path.join(BASE_DIR, "api-cache"))
set_option("API_CACHE_LOG", os.path.join(BASE_DIR, "var/log/api-cache.log"))


set_option("BASE_URL", "http://localhost")
set_option("PASSWORD_RESET_URL", os.path.join(BASE_URL, "reset-password"))

ACCOUNT_EMAIL_CONFIRMATION_ANONYMOUS_REDIRECT_URL = "/login"
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = "/verify"
ACCOUNT_EMAIL_REQUIRED = True


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
                "min": (2, 3, 0, 1),
                "max": (255, 0),
            },
        },
    },
)

set_option("IXF_POSTMORTEM_LIMIT", 250)

# when encountering problems where an exchange's ix-f feed
# becomes unavilable / unparsable this setting controls
# the interval in which we communicate the issue to them (hours)
set_option("IXF_PARSE_ERROR_NOTIFICATION_PERIOD", 360)

# toggle the creation of DeskPRO tickets from ix-f importer
# conflicts
set_option("IXF_TICKET_ON_CONFLICT", True)

# send the ix-f importer generated tickets to deskpro
set_option("IXF_SEND_TICKETS", False)

# toggle the notification of exchanges via email
# for ix-f importer conflicts
set_option("IXF_NOTIFY_IX_ON_CONFLICT", False)

# toggle the notification of networks via email
# for ix-f importer conflicts
set_option("IXF_NOTIFY_NET_ON_CONFLICT", False)

# number of days of a conflict being unresolved before
# deskpro ticket is created
set_option("IXF_IMPORTER_DAYS_UNTIL_TICKET", 6)


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


# TODO -- let's make this 1
# TODO -- why are the ids different for prod, beta, tutor, etc?
# all suggested entities will be created under this org
set_option("SUGGEST_ENTITY_ORG", 20525)

set_option("TUTORIAL_MODE", False)

#'guest' user group
GUEST_GROUP_ID = 1

#'user' user group
USER_GROUP_ID = 2

CSRF_FAILURE_VIEW = "peeringdb_server.views.view_http_error_csrf"

RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


# Set countries that don't use zipcodes
set_option("NON_ZIPCODE_COUNTRIES", non_zipcode_countries())

## Locale

LANGUAGE_CODE = "en-us"
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

TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG

if DEBUG:
    # make all loggers use the console.
    for logger in LOGGING["loggers"]:
        LOGGING["loggers"][logger]["handlers"] = ["console"]


if TUTORIAL_MODE:
    EMAIL_SUBJECT_PREFIX = "[PDB TUTORIAL] "
    DISABLE_VERIFICATION_QUEUE_EMAILS = True
    DISABLE_VERIFICATION_QUEUE = True
    AUTO_APPROVE_AFFILIATION = True
    AUTO_VERIFY_USERS = True
else:
    EMAIL_SUBJECT_PREFIX = f"[{RELEASE_ENV}] "

print_debug(f"loaded settings for PeeringDB {PEERINGDB_VERSION} (DEBUG: {DEBUG})")
