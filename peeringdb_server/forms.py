import re
from peeringdb_server.models import User, Organization
from django.contrib.auth import forms as auth_forms
from django import forms
from django_namespace_perms.constants import *
from django.utils.translation import ugettext_lazy as _


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
            asn = int(re.sub("\D", "", asn))
        except ValueError:
            raise forms.ValidationError(_("ASN needs to be a number"))
        return asn


class PasswordChangeForm(forms.Form):
    password = forms.CharField()
    password_v = forms.CharField()

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if len(password) < 10:
            raise forms.ValidationError(
                _("Needs to be at least 10 characters long"))
        return password

    def clean_password_v(self):
        password = self.cleaned_data.get("password")
        password_v = self.cleaned_data.get("password_v")

        if password != password_v:
            raise forms.ValidationError(
                _("Passwords need to match"), code="password_mismatch")
        return password_v


class PasswordResetForm(forms.Form):
    email = forms.EmailField()


class UsernameRetrieveForm(forms.Form):
    email = forms.EmailField()


class UserCreationForm(auth_forms.UserCreationForm):
    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
        )


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
        fields = ('locale')
