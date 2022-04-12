Generated from middleware.py on 2022-04-12 16:41:02.631987

# peeringdb_server.middleware

Custom django middleware.

# Classes
---

## CurrentRequestContext

```
CurrentRequestContext(builtins.object)
```

Middleware that sets the current request context.

This allows access to the current request from anywhere.


### Methods

#### \__call__
`def __call__(self, request)`

Call self as a function.

---
#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

---

## HttpResponseUnauthorized

```
HttpResponseUnauthorized(django.http.response.HttpResponse)
```

An HTTP response class with a string as content.

This content can be read, appended to, or replaced.


## PDBCommonMiddleware

```
PDBCommonMiddleware(django.middleware.common.CommonMiddleware)
```

"Common" middleware for taking care of some basic operations:

    - Forbid access to User-Agents in settings.DISALLOWED_USER_AGENTS

    - URL rewriting: Based on the APPEND_SLASH and PREPEND_WWW settings,
      append missing slashes and/or prepends missing "www."s.

        - If APPEND_SLASH is set and the initial URL doesn't end with a
          slash, and it is not found in urlpatterns, form a new URL by
          appending a slash at the end. If this new URL is found in
          urlpatterns, return an HTTP redirect to this new URL; otherwise
          process the initial URL as usual.

      This behavior can be customized by subclassing CommonMiddleware and
      overriding the response_redirect_class attribute.


### Methods

#### process_request
`def process_request(self, request)`

Check for denied User-Agents and rewrite the URL based on
settings.APPEND_SLASH and settings.PREPEND_WWW

---

## PDBPermissionMiddleware

```
PDBPermissionMiddleware(django.utils.deprecation.MiddlewareMixin)
```

Middleware that checks if the current user has the correct permissions
to access the requested resource.


### Methods

#### get_username_and_password
`def get_username_and_password(self, http_auth)`

Get the username and password from the HTTP auth header.

---
#### response_unauthorized
`def response_unauthorized(self, request, status=None, message=None)`

Return a Unauthorized response.

---
