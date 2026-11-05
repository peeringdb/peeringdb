Generated from oauth_views.py on 2026-11-05 20:07:16.953937

# peeringdb_server.oauth_views

# Functions
---

## has_recent_oauth_login
`def has_recent_oauth_login(request)`

True when the current user completed a login wizard for an OAuth
authorization within the last `OAUTH_COOKIE_MAX_AGE` seconds.

The marker is set on the session by `LoginView.done`.

---
# Classes
---

## AuthorizationView

```
AuthorizationView(peeringdb_server.oauth_views.BaseAuthorizationView, django.views.generic.edit.FormView)
```

Implements an endpoint to handle *Authorization Requests* as in :rfc:`4.1.1` and prompting the
user with a form to determine if she authorizes the client application to access her data.
This endpoint is reached two times during the authorization process:
* first receive a ``GET`` request from user asking authorization for a certain client
application, a form is served possibly showing some useful info and prompting for
*authorize/do not authorize*.

* then receive a ``POST`` request possibly after user authorized the access

Some informations contained in the ``GET`` request and needed to create a Grant token during
the ``POST`` request would be lost between the two steps above, so they are temporarily stored in
hidden fields on the form.
A possible alternative could be keeping such informations in the session.

The endpoint is used in the following flows:
* Authorization code
* Implicit grant


### Methods

#### form_valid
`def form_valid(self, form)`

If the form is valid, redirect to the supplied URL.

---
#### get
`def get(self, request, *args, **kwargs)`

Handle GET requests: instantiate a blank version of the form.

---
#### get_initial
`def get_initial(self)`

Return the initial data to use for forms on this view.

---

## BaseAuthorizationView

```
BaseAuthorizationView(peeringdb_server.oauth_views.LoginRequiredMixin, oauth2_provider.views.mixins.OAuthLibMixin, django.views.generic.base.View)
```

Implements a generic endpoint to handle *Authorization Requests* as in :rfc:`4.1.1`. The view
does not implement any strategy to determine *authorize/do not authorize* logic.
The endpoint is used in the following flows:

* Authorization code
* Implicit grant


### Methods

#### create_authorization_response
`def create_authorization_response(self, request, scopes, credentials, allow)`

A wrapper method that calls create_authorization_response on `server_class`
instance.

:param request: The current django.http.HttpRequest object
:param scopes: A space-separated string of provided scopes
:param credentials: Authorization credentials dictionary containing
                   `client_id`, `state`, `redirect_uri` and `response_type`
:param allow: True if the user authorize the client, otherwise False

---
#### error_response
`def error_response(self, error, application, **kwargs)`

Handle errors either by redirecting to redirect_uri with a json in the body containing
error details or providing an error response

---

## ConnectDiscoveryInfoView

```
ConnectDiscoveryInfoView(oauth2_provider.views.oidc.ConnectDiscoveryInfoView)
```

OIDC discovery document without HS256 in the advertised ID token
signing algorithms (#2055)


## DeviceConfirmView

```
DeviceConfirmView(peeringdb_server.oauth_views.LoginRequiredMixin, oauth2_provider.views.device.DeviceConfirmView)
```

Device flow approval, behind the same recent login as consent.


## DeviceUserCodeView

```
DeviceUserCodeView(peeringdb_server.oauth_views.LoginRequiredMixin, oauth2_provider.views.device.DeviceUserCodeView)
```

Device flow user code entry, behind the same recent login as consent.


## LoginRequiredMixin

```
LoginRequiredMixin(django.contrib.auth.mixins.AccessMixin)
```

Verify that the current user logged in for this authorization recently.


## OAuthMetadataView

```
OAuthMetadataView(django.views.generic.base.View)
```

Intentionally simple parent class for all views. Only implements
dispatch-by-method and simple sanity checking.
