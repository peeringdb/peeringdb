Generated from two_factor_ui_next.py on 2025-08-19 14:17:58.294002

# peeringdb_server.two_factor_ui_next

# Classes
---

## BackupTokensView

```
BackupTokensView(peeringdb_server.two_factor_ui_next.UIAwareMixin, two_factor.views.core.BackupTokensView)
```

Override of BackupTokensView that supports template switching based on UI version.


## LoginView

```
LoginView(peeringdb_server.two_factor_ui_next.UIAwareMixin, peeringdb_server.views.LoginView)
```

Override of LoginView from peeringdb_server to support template switching.


## ProfileView

```
ProfileView(peeringdb_server.two_factor_ui_next.UIAwareMixin, two_factor.views.profile.ProfileView)
```

Override of ProfileView that supports template switching based on UI version.


## QRGeneratorView

```
QRGeneratorView(peeringdb_server.two_factor_ui_next.UIAwareMixin, two_factor.views.core.QRGeneratorView)
```

Override of QRGeneratorView that supports template switching based on UI version.


## SetupCompleteView

```
SetupCompleteView(peeringdb_server.two_factor_ui_next.UIAwareMixin, two_factor.views.core.SetupCompleteView)
```

Override of SetupCompleteView that supports template switching based on UI version.


## TwoFactorDisableView

```
TwoFactorDisableView(peeringdb_server.two_factor_ui_next.UIAwareMixin, django_security_keys.ext.two_factor.views.DisableView)
```

Override of TwoFactorDisableView from peeringdb_server to support template switching.


## TwoFactorSetupView

```
TwoFactorSetupView(peeringdb_server.two_factor_ui_next.UIAwareMixin, peeringdb_server.views.TwoFactorSetupView)
```

Override of TwoFactorSetupView from peeringdb_server to support template switching.


## UIAwareMixin

```
UIAwareMixin(builtins.object)
```

Mixin to override the template selection based on the user's UI version preference.

It uses `resolve_template()` to determine whether to serve the default or 'next' version
of the template dynamically, depending on user flags or default settings.
