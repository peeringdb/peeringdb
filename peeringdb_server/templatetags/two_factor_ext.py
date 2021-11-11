"""
Template filters / tags to help with two-factor auth
"""
from django import template
from django.utils.translation import ugettext_lazy as _
from django_otp.plugins.otp_email.models import EmailDevice
from django_otp import devices_for_user
from two_factor.templatetags import two_factor

register = template.Library()


@register.filter
def device_action(device):
    if isinstance(device, EmailDevice):
        return _("Email one time password")
    elif device.method == "security-key":
        return _("U2F security key")

    return two_factor.device_action(device)

@register.filter
def user_has_u2f_device(user):
    return user.webauthn_security_keys.exists()

@register.filter
def user_has_topt_device(user):
    for device in devices_for_user(user):
        if device.method == "token":
            return True
    return False
