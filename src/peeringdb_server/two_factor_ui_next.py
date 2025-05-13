import re

from django.urls import re_path
from two_factor.views import BackupTokensView as BaseBackupTokensView
from two_factor.views import ProfileView as BaseProfileView
from two_factor.views import QRGeneratorView as BaseQRGeneratorView
from two_factor.views import SetupCompleteView as BaseSetupCompleteView

from peeringdb_server.util import resolve_template
from peeringdb_server.views import LoginView as BaseLoginView
from peeringdb_server.views import TwoFactorDisableView as BaseTwoFactorDisableView
from peeringdb_server.views import TwoFactorSetupView as BaseTwoFactorSetupView


class UIAwareMixin:
    """
    Mixin to override the template selection based on the user's UI version preference.

    It uses `resolve_template()` to determine whether to serve the default or 'next' version
    of the template dynamically, depending on user flags or default settings.
    """

    def get_template_names(self):
        original_templates = super().get_template_names()
        return [resolve_template(self.request, t) for t in original_templates]


# UI-aware view overrides for two_factor and peeringdb views


class BackupTokensView(UIAwareMixin, BaseBackupTokensView):
    """
    Override of BackupTokensView that supports template switching based on UI version.
    """

    pass


class ProfileView(UIAwareMixin, BaseProfileView):
    """
    Override of ProfileView that supports template switching based on UI version.
    """

    pass


class QRGeneratorView(UIAwareMixin, BaseQRGeneratorView):
    """
    Override of QRGeneratorView that supports template switching based on UI version.
    """

    pass


class SetupCompleteView(UIAwareMixin, BaseSetupCompleteView):
    """
    Override of SetupCompleteView that supports template switching based on UI version.
    """

    pass


class LoginView(UIAwareMixin, BaseLoginView):
    """
    Override of LoginView from peeringdb_server to support template switching.
    """

    pass


class TwoFactorDisableView(UIAwareMixin, BaseTwoFactorDisableView):
    """
    Override of TwoFactorDisableView from peeringdb_server to support template switching.
    """

    pass


class TwoFactorSetupView(UIAwareMixin, BaseTwoFactorSetupView):
    """
    Override of TwoFactorSetupView from peeringdb_server to support template switching.
    """

    pass
