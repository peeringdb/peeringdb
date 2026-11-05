Generated from middleware.py on 2026-11-05 20:07:16.953937

# peeringdb_server.middleware

Custom django middleware.

# Functions
---

## basic_auth_disabled
`def basic_auth_disabled()`

Returns True once MFA enforcement (MFA_FORCE_HARD_START) has started, from
which point Basic authentication is refused. An unset date counts as
started.

---
## build_log_uri
`def build_log_uri(request)`

Builds the URI to log for the request.

Values of sensitive path parameters are redacted. The query string is
kept only on API paths, where filters help abuse triage, and there only
the parameters the API filters on are kept. Elsewhere a query string is
replaced as a whole.

---
## find_kwarg_spans
`def find_kwarg_spans(resolver, path, offset=0)`

Resolves `path` the way `resolver` does and returns where each named
group of the matching patterns was captured, as {name: [(start, end)]}
offsets into the full path, outermost first, or None if nothing matches.

---
## get_auth_identity
`def get_auth_identity(request)`

Returns a string that uniquely identifies the authentication
method used for the request.

This is used to cache negative authentication responses

---
## get_auth_status
`def get_auth_status(request)`

Returns the value of the X-Auth-Status header for the request.

---
## get_inactive_cache_key
`def get_inactive_cache_key(identifier)`

Returns the negative cache key that marks the credentials `identifier`
stands for as inactive.

The identifier can carry a Basic auth username, often a mistyped
password, or a whole API key, so it goes into the key as a digest (#495).

---
## get_log_api_query
`def get_log_api_query(request, match)`

Returns the API query string to log, as the client sent it, with every
parameter the API doesn't filter on replaced.

Nothing under /api/ reads a credential from the query string, so a
parameter the API ignores is the only kind that can hold one; its name
is dropped too, a secret can be sent as the name.

---
## get_log_auth_id
`def get_log_auth_id(request)`

Returns the caller identity to log for the request (#487).

PDBPermissionMiddleware records it as `request.log_auth_id` where it
authenticates. An OAuth access token accepted by an endpoint that takes
one logs `u<user_id>_oauth`, and a request without an identity logs
`anon`, or `unverified` if it sent credentials that were never accepted.

---
## get_log_invalid_key_id
`def get_log_invalid_key_id(key)`

Returns the caller identity to log for an API key that matched no key.

Only a key shaped like a generated one, `<prefix>.<secret>`, has a
public part to log; any other value may be secret throughout.

---
## get_log_path_candidates
`def get_log_path_candidates(request)`

Returns the paths the request may resolve as, in the order to try them.

---
## get_log_redacted_spans
`def get_log_redacted_spans(request, redact)`

Returns the merged spans in `request.path_info` of the path parameters
in `redact`, a {name: value} mapping from the URL match, or None unless
the walk captured exactly those values.

---
## get_log_uri
`def get_log_uri(request)`

Returns the URI to log for the request in place of the one it was sent
with (#495).

Never raises: request logging must not be able to change a response.

---
## get_pattern_spans
`def get_pattern_spans(pattern, path, offset)`

Returns the spans of the named groups `pattern` captures from `path`,
matching the way the pattern does.

---
## is_basic_auth
`def is_basic_auth(http_auth)`

Returns True if the Authorization header uses the Basic scheme, in any
case, as DRF's `BasicAuthentication` accepts it in any case too.

---
## is_log_alias_filter
`def is_log_alias_filter(field)`

Returns whether `field` is an `<alias>__<field>` relation filter of the
serializers' prepare_query, such as `net__asn` on /api/ix, naming a
concrete field of the aliased object.

---
## is_log_api_query_param
`def is_log_api_query_param(name, view_class)`

Returns whether the API view filters on the query parameter `name`,
matching it the way the API does: an optional lookup suffix, then the
serializer's field name translation.

---
## is_log_sensitive_param
`def is_log_sensitive_param(name)`

Returns whether a URL path parameter name marks its value as secret.

Matches whole words, so `access_token`, `client_secret`, `user_code` and
`apiKey` match while `zipcode` does not.

---
## redact_log_path
`def redact_log_path(request, redact)`

Returns the quoted request path with the path parameters in `redact`
replaced, or the whole path replaced if they can't be located.

---
## resolve_for_log
`def resolve_for_log(request)`

Returns the URL match for the request, resolving it here when the
response was returned before URL resolution.

---
## truncate_log_uri
`def truncate_log_uri(uri)`

Cuts the URI to what a uWSGI log variable holds.

uWSGI stores a log variable's length in one byte and wraps longer values
around silently.

---
# Classes
---

## CacheControlMiddleware

```
CacheControlMiddleware(django.utils.deprecation.MiddlewareMixin)
```

Sets the Cache-Control s-maxage header on responses


### Methods

#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

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

## HealthcheckHostMiddleware

```
HealthcheckHostMiddleware(builtins.object)
```

Gives `/healthcheck` the BASE_URL host, so load balancer and k8s probes
pass ALLOWED_HOSTS. ALB health checks send the target address as Host
and cannot be configured to send another one.

Must run before anything that calls `request.get_host()`.


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

#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### get_username_and_password
`def get_username_and_password(self, http_auth)`

Get the username and password from the HTTP auth header.

---
#### response_unauthorized
`def response_unauthorized(self, request, status=None, message=None)`

Return a Unauthorized response.

---

## PDBSessionMiddleware

```
PDBSessionMiddleware(django.contrib.sessions.middleware.SessionMiddleware)
```

As PeeringDB gets a lot of repeated anonymous requests that do not
store and re-use session cookies this lead to substantial amount of junk
django session objects.

It was decided in #1205 that new django sessions are only to be established
On the login and registration processes.


### Methods

#### process_response
`def process_response(self, request, response)`

If request.session was modified, or if the configuration is to save the
session every time, save the changes and set a session cookie or delete
the session cookie if the session has been emptied.

---

## RateLimitWebPageMiddleware

```
RateLimitWebPageMiddleware(django.utils.deprecation.MiddlewareMixin)
```

Rate limits unauthenticated requests to web pages
(non-API, non-static, non-media paths).

Uses django-ratelimit's core get_usage() for rate tracking,
keyed by client IP address.

Configurable via RATELIMIT_WEB_PAGE_RATE EnvironmentSetting. Set to empty string to disable.


### Methods

#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

---

## RedisNegativeCacheMiddleware

```
RedisNegativeCacheMiddleware(django.utils.deprecation.MiddlewareMixin)
```

Middleware that uses Django's cache framework with Redis backend to cache error responses.


### Methods

#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### generate_cache_key
`def generate_cache_key(self, request)`

Generate the cache key using the IP address, HTTP_AUTHORIZATION value or session ID, request path, and URL parameters.

---
#### is_exempt
`def is_exempt(self, request)`

Returns True if error responses for this request must not be cached.

An exempt name that no longer resolves is logged and ignored, so the
rest of the negative cache keeps working.

---
#### process_request
`def process_request(self, request)`

Process the request before it's passed to the view.

---
#### process_response
`def process_response(self, request, response)`

Process the response before it's sent to the client.

---

## UwsgiLogUriMiddleware

```
UwsgiLogUriMiddleware(builtins.object)
```

Adds the request URI with secrets redacted to the uWSGI request log as
the `log_uri` log variable (#495), for the log format to use in place of
the URI the request was sent with.

Runs first, so responses that middleware such as WhiteNoise return early
get it too. Not used outside uWSGI.


### Methods

#### \__call__
`def __call__(self, request)`

Call self as a function.

---
#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

---

## UwsgiLogVarsMiddleware

```
UwsgiLogVarsMiddleware(builtins.object)
```

Adds the caller identity to the uWSGI request log as the `auth_id` and
`auth_status` log variables (#487).

Not used outside uWSGI.


### Methods

#### \__call__
`def __call__(self, request)`

Call self as a function.

---
#### \__init__
`def __init__(self, get_response)`

Initialize self.  See help(type(self)) for accurate signature.

---
