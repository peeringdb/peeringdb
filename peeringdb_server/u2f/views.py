import json
import base64

from webauthn import base64url_to_bytes

from django.db import transaction
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils.translation import ugettext_lazy as _

from peeringdb_server.models import SecurityKey
from peeringdb_server.api_key_views import convert_to_bool


@login_required
def request_registration(request, **kwargs):
    """
    Requests webauthn registration options from the server
    as a JSON response
    """

    return JsonResponse(
        json.loads(SecurityKey.generate_registration(request.user, request.session))
    )


def request_authentication(request, **kwargs):
    """
    Requests webauthn authentications options from the server
    as a JSON response

    Expects a `username` POST parameter
    """

    username = request.POST.get("username")
    for_login = request.POST.get("for_login")

    if not username:
        return JsonResponse({"non_field_errors": _("No username supplied")}, status=403)

    return JsonResponse(
        json.loads(SecurityKey.generate_authentication(username, request.session, for_login=for_login))
    )


@login_required
@transaction.atomic
def register_security_key(request, **kwargs):
    """
    Register a webauthn security key.

    This requires the following POST data:

    - credential(`base64`): registration credential
    - name(`str`): key nick name
    - passwordless_login (`bool`): allow passwordless login
    """

    name = request.POST.get("name", "security-key")
    credential = request.POST.get("credential")
    passwordless_login = convert_to_bool(request.POST.get("passwordless_login", False))

    security_key = SecurityKey.verify_registration(
        request.user,
        request.session,
        credential,
        name=name,
        passwordless_login=passwordless_login,
    )

    return JsonResponse(
        {"status": "ok", "name": security_key.name, "id": security_key.id}
    )


@login_required
@transaction.atomic
def verify_authentication(request):

    """
    Verify the authentication attempt.

    This requires the following POST data:

    - credential(`base64`): registration credential
    - username(`str`): username
    - auth_type(`str`): "login" or "mfa"

    ### Authentication typers

    #### login

    the attempt is for a passwordless login process and will only
    success if the chosen key has that option enabled.

    #### 2fa

    the attempt is for 2fa process

    """

    credential = request.POST.get("credential")
    username = request.POST.get("username")

    try:
        SecurityKey.verify_authentication(
            username,
            request.session,
            credential,
            for_login=(request.POST.get("auth_type") == "login"),
        )
    except Exception as exc:
        # XXX
        raise
        return JsonResponse({"non_field_errors": exc}, status=403)

    return JsonResponse(
        {
            "status": "ok",
        }
    )


@login_required
def remove_security_key(request, **kwargs):
    """
    Decommission a security key.
    """

    user = request.user
    # XXX should be credential id instead ?
    id = request.POST.get("id")

    try:
        print("checking key", id, "on", user)
        sec_key = request.user.webauthn_security_keys.get(pk=id)
    except SecurityKey.DoesNotExist:
        return JsonResponse({"non_field_errors": [_("Key not found")]}, status=404)
    sec_key.delete()

    return JsonResponse(
        {
            "status": "ok",
        }
    )
