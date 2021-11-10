from django.contrib.auth.backends import ModelBackend

from peeringdb_server.models import SecurityKey


class PasswordlessAuthenticationBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):

        credential = kwargs.get("u2f_credential")

        # no username supplied, abort password-less login silently
        # normal login process will raise required-field error
        # on username

        if not username or not credential:
            return

        has_credentials = SecurityKey.credentials(username)

        # no credential supplied

        if not has_credentials:
            return

        # verify password-less login
        try:
            key = SecurityKey.verify_authentication(
                username, request.session, credential, for_login=True
            )
            return key.user
        except Exception:
            raise
