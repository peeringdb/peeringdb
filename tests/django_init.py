from django.conf import settings

# lazy init for translations
_ = lambda s: s

#from django.utils.translation import ugettext_lazy as _

settings.configure(
    PACKAGE_VERSION="dev",
    RELEASE_ENV="dev",
    MIGRATION_MODULES={"django_peeringdb":None},
    INSTALLED_APPS=[
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.admin',
        'django.contrib.sessions',
        'django.contrib.sites',
        'django_inet',
        'django_peeringdb',
        'django_namespace_perms',
        'django_countries',
        'oauth2_provider',
        'peeringdb_server',
        'allauth',
        'allauth.account',
        'reversion',
        'rest_framework',
        'dal',
        'dal_select2',
        'corsheaders',
        'captcha',
    ],
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "django_cache"
        }
    },
    TEMPLATES=[{
        "BACKEND": 'django.template.backends.django.DjangoTemplates',
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
            ],
            #"loaders" : TEMPLATE_LOADERS
        }
    }],
    LANGUAGE_CODE='en-us',
    LANGUAGES=[
        ('en', _('English')),
        ('pt', _('Portuguese')),
    ],
    USE_L10N=True,
    USE_I18N=True,
    MIDDLEWARE_CLASSES=(
        'corsheaders.middleware.CorsMiddleware',
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.middleware.locale.LocaleMiddleware',
        'django.middleware.common.CommonMiddleware',
        'django.middleware.csrf.CsrfViewMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'django.contrib.messages.middleware.MessageMiddleware',
        'peeringdb_server.maintenance.Middleware',
    ),
    SOUTH_TESTS_MIGRATE=False,
    SOUTH_SKIP_TESTS=True,
    AUTH_USER_MODEL='peeringdb_server.User',
    TABLE_PREFIX='peeringdb_',
    PEERINGDB_ABSTRACT_ONLY=True,
    COUNTRIES_OVERRIDE={'XK': _('Kosovo')},
    CLIENT_COMPAT={
        "client":{"min": (0,6), "max":(0,6,5)},
        "backends":{
            "django_peeringdb":{"min":(0,6), "max":(0,6,5)}
        }
    },
    DATABASE_ENGINE='django.db.backends.sqlite3',
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        },
        #XXX - this is supposed to work to mimic replication
        # during tests, but doesnt. So instead we use the
        # peeringdb_server.db_router.TestRouter class instead
        # which just always used the default db for read and writes
        #'read' : {
        #    'ENGINE': 'django.db.backends.sqlite3',
        #    'NAME': ':memory:',
        #    'TEST' : { 'MIRROR' : 'default' }
        #}
    },
    #XXX - change to peeringdb_server.db_router.DatabaseRouter
    #if repliation mimicing (see above) gets fixed
    DATABASE_ROUTERS=["peeringdb_server.db_router.TestRouter"],
    DEBUG=False,
    GUEST_GROUP_ID=1,
    USER_GROUP_ID=2,
    TEMPLATE_DEBUG=False,
    BASE_URL="localost",
    PASSWORD_RESET_URL="localhost",
    API_CACHE_ROOT="tests/api-cache",
    API_CACHE_ENABLED=False,
    SUGGEST_ENTITY_ORG=1234,
    API_URL="localhost",
    REST_FRAMEWORK={
        'DEFAULT_AUTHENTICATION_CLASSES': (
            'rest_framework.authentication.BasicAuthentication',
            'rest_framework.authentication.SessionAuthentication'),
        'DEFAULT_MODEL_SERIALIZER_CLASS': 'rest_framework.serializers.HyperlinkedModelSerializer',
        'DEFAULT_PERMISSION_CLASSES': [
            'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly',
            'django_namespace_perms.rest.BasePermission',
        ],
        'DEFAULT_RENDERER_CLASSES': (
            'peeringdb_server.renderers.MetaJSONRenderer', )
    },
    NSP_MODE="crud",
    NSP_GUEST_GROUP="guest",
    DEBUG_EMAIL=True,
    TIME_ZONE="UTC",
    USE_TZ=True,
    AUTHENTICATION_BACKENDS=(
        "django_namespace_perms.auth.backends.NSPBackend", ),
    ROOT_URLCONF="peeringdb_com.urls",
    LOGGING={
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'stderr': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
            },
        },
        'loggers': {
            '': {
                'handlers': ['stderr'],
                'level': 'DEBUG',
                'propagate': False
            },
        },
    },
    OAUTH_ENABLED=False,
    RECAPTCHA_PUBLIC_KEY="",
    EMAIL_SUBJECT_PREFIX="[test]",
    CORS_ORIGIN_WHITELIST=[],
    CORS_ALLOW_METHODS=["GET", "OPTIONS"],
    CORS_ALLOW_CREDENTIALS=False,
    DATA_QUALITY_MAX_PREFIX_V4_LIMIT=500000,
    DATA_QUALITY_MAX_PREFIX_V6_LIMIT=500000,
    DATA_QUALITY_MIN_PREFIXLEN_V4 = 18,
    DATA_QUALITY_MAX_PREFIXLEN_V4 = 28,
    DATA_QUALITY_MIN_PREFIXLEN_V6 = 64,
    DATA_QUALITY_MAX_PREFIXLEN_V6 = 116,
    TUTORIAL_MODE=False,
    CAPTCHA_TEST_MODE=True,
    SITE_ID=1,
    IXF_POSTMORTEM_LIMIT=250,
    ABSTRACT_ONLY=True,
    GOOGLE_GEOLOC_API_KEY="AIzatest",
    RATELIMITS={
        "view_affiliate_to_org_POST": "100/m",
        "resend_confirmation_mail": "2/m",
        "view_request_ownership_GET": "3/m",
        "view_username_retrieve_initiate": "2/m",
        "view_request_ownership_POST": "3/m",
        "request_login_POST": "10/m",
        "view_verify_POST": "2/m",
        "request_translation": "10/m",
        "view_import_ixlan_ixf_preview": "1/m",
        "view_import_net_ixf_postmortem": "1/m"
    })
