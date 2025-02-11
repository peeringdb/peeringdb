Generated from oauth_views.py on 2025-02-11 10:26:48.481231

# peeringdb_server.oauth_views

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

#### error_response
`def error_response(self, error, application, **kwargs)`

Handle errors either by redirecting to redirect_uri with a json in the body containing
error details or providing an error response

---

## LoginRequiredMixin

```
LoginRequiredMixin(django.contrib.auth.mixins.AccessMixin)
```

Verify that the current user is authenticated.


## OAuthMetadataView

```
OAuthMetadataView(django.views.generic.base.View)
```

Intentionally simple parent class for all views. Only implements
dispatch-by-method and simple sanity checking.
