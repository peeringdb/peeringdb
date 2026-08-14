"""
Template filters / tags to help with two-factor auth
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.utils.translation import gettext_lazy as _
from django_otp import devices_for_user
from django_otp.plugins.otp_email.models import EmailDevice

if TYPE_CHECKING:
    from django_otp.models import Device

    from peeringdb_server.models import User

register = template.Library()


@register.filter
def device_action(device: Device | None) -> str | None:
    if isinstance(device, EmailDevice):
        return _("Email one time password")
    elif device:
        try:
            if device.method == "security-key":
                return _("U2F security key")
        except AttributeError:
            pass
    return None


@register.filter
def user_has_u2f_device(user: User) -> bool:
    return user.webauthn_security_keys.exists()


@register.filter
def user_has_topt_device(user: User) -> bool:
    for device in devices_for_user(user):
        if device.method == "token":
            return True
    return False
