"""
Template filters / tags to help with two-factor auth
"""

from django import template
from django.utils.translation import gettext_lazy as _
from django_otp import devices_for_user
from django_otp.plugins.otp_email.models import EmailDevice
from two_factor.plugins.phonenumber.templatetags import phonenumber

register = template.Library()


@register.filter
def device_action(device):
    if isinstance(device, EmailDevice):
        return _("Email one time password")
    elif device:
        try:
            if device.method == "security-key":
                return _("U2F security key")
        except AttributeError:
            pass


@register.filter
def user_has_u2f_device(user):
    return user.webauthn_security_keys.exists()


@register.filter
def user_has_topt_device(user):
    for device in devices_for_user(user):
        if device.method == "token":
            return True
    return False
