from django.contrib.auth.backends import ModelBackend

from peeringdb_server.models import SecurityKey


class PasswordlessAuthenticationBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):

        # clean up last used passwordless key

        try:
            del request.session["webauthn_passwordless"]
        except KeyError:
            pass

        credential = kwargs.get("u2f_credential")

        # no username supplied, abort password-less login silently
        # normal login process will raise required-field error
        # on username

        if not username or not credential:
            return

        has_credentials = SecurityKey.credentials(
            username, request.session, for_login=True
        )

        # no credential supplied

        if not has_credentials:
            return

        # verify password-less login
        try:
            key = SecurityKey.verify_authentication(
                username, request.session, credential, for_login=True
            )
            request.session["webauthn_passwordless"] = key.id
            return key.user
        except Exception:
            raise
