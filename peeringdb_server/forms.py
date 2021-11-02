"""
Custom django forms.

Note: This does not includes forms pointed directly
at the REST api to handle updates (such as /net, /ix, /fac or /org endpoints).

Look in rest.py and serializers.py for those.
"""

import os.path
import re
import uuid

import requests
from captcha.fields import CaptchaField
from captcha.models import CaptchaStore
from django import forms
from django.conf import settings as dj_settings
from django.contrib.auth import forms as auth_forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError
from grainy.const import PERM_CRUD, PERM_DENY, PERM_READ

from peeringdb_server.inet import get_client_ip
from peeringdb_server.models import Organization, User


class OrganizationAPIKeyForm(forms.Form):
    name = forms.CharField()
    email = forms.EmailField()
    org_id = forms.IntegerField()


class OrgAdminUserPermissionForm(forms.Form):

    entity = forms.CharField()
    perms = forms.IntegerField()

    def clean_perms(self):
        perms = self.cleaned_data.get("perms")
        if not perms & PERM_READ:
            perms = perms | PERM_READ
        if perms & PERM_DENY:
            perms = perms ^ PERM_DENY
        if perms > PERM_CRUD or perms < PERM_READ:
            raise forms.ValidationError(_("Invalid permission level"))
        return perms


class AffiliateToOrgForm(forms.Form):

    asn = forms.CharField(required=False)
    org = forms.CharField(required=False)

    def clean_org(self):
        org_id = self.cleaned_data.get("org")
        if not org_id:
            return 0

        # if org id can be inted, an existing org id has been submitted
        # otherwise an org name has been submitted that may or may not exist
        try:
            org_id = int(org_id)
            if not Organization.objects.filter(id=org_id).exists():
                if self.cleaned_data.get("asn"):
                    return 0
        except ValueError:
            try:
                org = Organization.objects.get(name=org_id)
                return org.id
            except Organization.DoesNotExist:
                self.cleaned_data["org_name"] = org_id
                return 0

        return org_id

    def clean_asn(self):
        asn = self.cleaned_data.get("asn")
        if not asn:
            return 0
        try:
            asn = int(re.sub(r"\D", r"", asn))
        except ValueError:
            raise forms.ValidationError(_("ASN needs to be a number"))
        return asn


class PasswordChangeForm(forms.Form):
    password = forms.CharField()
    password_v = forms.CharField()

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if len(password) < 10:
            raise forms.ValidationError(_("Needs to be at least 10 characters long"))
        return password

    def clean_password_v(self):
        password = self.cleaned_data.get("password")
        password_v = self.cleaned_data.get("password_v")

        if password != password_v:
            raise forms.ValidationError(
                _("Passwords need to match"), code="password_mismatch"
            )
        return password_v


class PasswordResetForm(forms.Form):
    email = forms.EmailField()


class UsernameRetrieveForm(forms.Form):
    email = forms.EmailField()


class UserCreationForm(auth_forms.UserCreationForm):
    recaptcha = forms.CharField(required=False)
    captcha = forms.CharField(required=False)
    captcha_generator = CaptchaField(required=False)

    require_captcha = True

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
        )

    def clean(self):
        super().clean()
        recaptcha = self.cleaned_data.get("recaptcha", "")
        captcha = self.cleaned_data.get("captcha", "")

        if not self.require_captcha:
            return
        elif not recaptcha and not captcha:
            raise forms.ValidationError(
                _("Please fill out the anti-spam challenge (captcha) field")
            )

        elif recaptcha:
            cpt_params = {
                "secret": dj_settings.RECAPTCHA_SECRET_KEY,
                "response": recaptcha,
                "remoteip": get_client_ip(self.request),
            }
            cpt_response = requests.post(
                dj_settings.RECAPTCHA_VERIFY_URL, params=cpt_params
            ).json()
            if not cpt_response.get("success"):
                raise forms.ValidationError(_("reCAPTCHA invalid"))
        else:
            try:
                hashkey, value = captcha.split(":")
                self.captcha_object = CaptchaStore.objects.get(
                    response=value, hashkey=hashkey, expiration__gt=timezone.now()
                )
            except CaptchaStore.DoesNotExist:
                raise forms.ValidationError(_("captcha invalid"))

    def delete_captcha(self):
        captcha_object = getattr(self, "captcha_object", None)
        if captcha_object:
            captcha_object.delete()


class UserLocaleForm(forms.Form):
    locale = forms.CharField()

    def clean_locale(self):
        loc = self.cleaned_data.get("locale")
        # django.utils.translation.check_for_language() #lang_code
        if loc:
            return loc
        return None

    class Meta:
        model = User
        fields = "locale"


class OrganizationLogoUploadForm(forms.ModelForm):
    logo = forms.FileField()

    class Meta:
        model = Organization
        fields = ["logo"]

    def clean_logo(self):

        logo = self.cleaned_data["logo"]
        max_size = dj_settings.ORG_LOGO_MAX_SIZE

        # normalize the file name
        ext = os.path.splitext(logo.name)[1].lower()
        randomize = str(uuid.uuid4())[:8]
        logo.name = f"org-{self.instance.id}-{randomize}{ext}"

        # validate file type
        if ext not in dj_settings.ORG_LOGO_ALLOWED_FILE_TYPE.split(","):
            raise ValidationError(
                _("File type %(value)s not allowed"),
                code="invalid",
                params={"value": ext},
            )

        # validate file size
        if logo.size > max_size:
            raise ValidationError(
                _("File size too big, max. %(value)s"),
                code="invalid",
                params={"value": f"{max_size / 1024:.0f} kb"},
            )

        return logo
