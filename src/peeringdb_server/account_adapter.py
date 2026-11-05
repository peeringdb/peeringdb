"""
django-allauth account adapter.
"""

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.urls import reverse


class AccountAdapter(DefaultAccountAdapter):
    def get_email_confirmation_url(self, request, emailconfirmation):
        """
        Builds the confirmation link from `BASE_URL` instead of the request
        `Host`, so the link in the mail always points at this site.
        """
        path = reverse("account_confirm_email", args=[emailconfirmation.key])
        return f"{settings.BASE_URL}{path}"
