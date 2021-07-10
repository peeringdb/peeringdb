from django import template
from django.utils.translation import ugettext_lazy as _
from django_otp.plugins.otp_email.models import EmailDevice
from two_factor.templatetags import two_factor

register = template.Library()


@register.filter
def device_action(device):
    if isinstance(device, EmailDevice):
        return _("Email one time password")

    return two_factor.device_action(device)
