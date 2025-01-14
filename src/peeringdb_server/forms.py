"""
Custom django forms.

Note: This does not includes forms pointed directly
at the REST api to handle updates (such as /net, /ix, /fac or /org endpoints).

Look in rest.py and serializers.py for those.
"""

import json
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
from django.utils.translation import gettext_lazy as _
from grainy.const import PERM_CRUD, PERM_DENY, PERM_READ
from schema import Schema, SchemaError

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

        if len(password) > dj_settings.MAX_LENGTH_PASSWORD:
            raise forms.ValidationError(_("Password is too long"))

        return password

    def clean_password_v(self):
        password = self.cleaned_data.get("password")
        password_v = self.cleaned_data.get("password_v")

        if password != password_v:
            raise forms.ValidationError(
                _("Passwords need to match"), code="password_mismatch"
            )
        return password_v


class UsernameChangeForm(forms.Form):
    username = forms.CharField()

    def clean_username(self):
        username = self.cleaned_data.get("username")

        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(_("This username is already taken"))
        return username


class NameChangeForm(forms.Form):
    first_name = forms.CharField(label=_("First Name"), required=True)
    last_name = forms.CharField(label=_("Last Name"), required=True)

    def clean_first_name(self):
        first_name = self.cleaned_data.get("first_name")
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get("last_name")
        return last_name


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


class VerifiedUpdateForm(forms.Form):
    source = forms.CharField(required=False)
    reason = forms.CharField(required=False)
    updates = forms.JSONField(required=True)

    def clean(self):
        cleaned_data = super().clean()
        updates = cleaned_data.get("updates")
        schema = Schema([{"ref_tag": str, "obj_id": int, "data": dict}])
        try:
            updates = json.loads(json.dumps(updates))
            schema.validate(updates)
        except (json.JSONDecodeError, TypeError, SchemaError):
            raise ValidationError("Malformed update data.")


class UserOrgForm(forms.Form):
    """
    Sets primary organization of the user
    """

    organization = forms.CharField()

    def clean_org(self):
        org = self.cleaned_data.get("organization")
        if org:
            return org
        return None

    class Meta:
        model = User
        fields = "primary_org"


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


class OrgUserOptions(forms.ModelForm):
    class Meta:
        model = Organization
        fields = [
            "require_2fa",
            "restrict_user_emails",
            "email_domains",
            "periodic_reauth",
            "periodic_reauth_period",
        ]
