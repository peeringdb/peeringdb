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

    return JsonResponse(json.loads(SecurityKey.generate_registration(request.user)))


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

    user = request.user
    name = request.POST.get("name")
    challenge = request.POST.get("challenge")
    credential = request.POST.get("credential")
    passwordless_login = convert_to_bool(request.POST.get("passwordless_login",False))

    security_key = SecurityKey.verify_registration(
        user,
        base64url_to_bytes(challenge),
        credential,
        name=name,
        passwordless_login=passwordless_login,
    )

    return JsonResponse(
        {
            "status": "ok",
            "name": security_key.name,
            "id": security_key.id
        }
    )


@login_required
def remove_security_key(request, **kwargs):
    """
    Revoke user api key.
    """

    user = request.user
    prefix = request.POST.get("prefix")

    try:
        api_key = UserAPIKey.objects.get(user=user, prefix=prefix)
    except UserAPIKey.DoesNotExist:
        return JsonResponse({"non_field_errors": [_("Key not found")]}, status=404)
    api_key.revoked = True
    api_key.save()

    return JsonResponse(
        {
            "status": "ok",
        }
    )
