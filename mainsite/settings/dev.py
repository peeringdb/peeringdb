import logging
import secrets


# database config
# set_option("DATABASE_ENGINE", "mysql")
# set_option("DATABASE_HOST", "127.0.0.1")
# set_option("DATABASE_PORT", "")
# set_option("DATABASE_NAME", "peeringdb")
# set_option("DATABASE_USER", "peeringdb")
# set_option("DATABASE_PASSWORD", "")

set_option("SERVER_EMAIL", "pdb@localhost")

set_from_env("SECRET_KEY", None)
if not SECRET_KEY:
    print_debug("SECRET_KEY not set, generating an ephemeral one")
    SECRET_KEY = secrets.token_urlsafe(64)

# Keys

GOOGLE_GEOLOC_API_KEY = ""

RDAP_LACNIC_APIKEY = ""

RECAPTCHA_PUBLIC_KEY = ""
RECAPTCHA_SECRET_KEY = ""

DESKPRO_KEY = ""
DESKPRO_URL = ""
