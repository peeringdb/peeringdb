import json
import base64

from webauthn import base64url_to_bytes

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


@login_required
def request_authentication(request, **kwargs):
    """
    Requests webauthn registration options from the server
    as a JSON response
    """

    username = request.POST.get("username")

    if not username:
        return JsonResponse({"non_field_errors": _("No username supplied")}, status=403)

    return JsonResponse(
        json.loads(SecurityKey.generate_authentication(username, request.session))
    )


@login_required
def register_security_key(request, **kwargs):
    """
    Register a webauthn security key.

    This requires the following POST data:

    - challenge(`base64`): the challenge as it was returne from the server in request_registration
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
def verify_authentication(request):

    credential = request.POST.get("credential")
    username = request.POST.get("username")

    try:
        security_key = SecurityKey.verify_authentication(
            username,
            request.session,
            credential,
        )
    except Exception as exc:
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
    Revoke user api key.
    """

    user = request.user
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
