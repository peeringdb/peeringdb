Generated from log.py on 2026-11-05 20:07:16.953937

# peeringdb_server.log

# Classes
---

## ExceptionReporter

```
ExceptionReporter(django.views.debug.ExceptionReporter)
```

Masks credentials passed in the query string, such as the password reset
token, in the request URL and GET parameters of error reports.


### Methods

#### get_traceback_data
`def get_traceback_data(self)`

Return a dictionary containing traceback information.

---

## ExceptionReporterFilter

```
ExceptionReporterFilter(django.views.debug.SafeExceptionReporterFilter)
```

Masks credentials in error reports by name: POST and query string
parameters, local variables and the keys of dicts in local variables.
Applies to every view, also those that do not declare
`sensitive_post_parameters` or `sensitive_variables`.


### Methods

#### cleanse_request_repr
`def cleanse_request_repr(self, request)`

Returns the request's repr with the query string cleansed.

---
#### cleanse_value
`def cleanse_value(self, value, depth=0, path=frozenset())`

Cleanses a local variable: the query string of a request and the
sensitive keys of a dict, also inside dicts, lists, tuples and
template contexts, such as the `args` of view decorators.

`path` holds the ids of the containers being cleansed, so a container
that contains itself is left as it is.

---
#### get_cleansed_multivaluedict
`def get_cleansed_multivaluedict(self, request, multivaluedict)`

Replace the keys in a MultiValueDict marked as sensitive with stars.
This mitigates leaking sensitive POST parameters if something like
request.POST['nonexistent_key'] throws an exception (#21098).

---
#### get_post_parameters
`def get_post_parameters(self, request)`

Replace the values of POST parameters marked as sensitive with
stars (*********).

---
#### get_safe_request_meta
`def get_safe_request_meta(self, request)`

Return a dictionary of request.META with sensitive values redacted.

---
#### get_traceback_frame_variables
`def get_traceback_frame_variables(self, request, tb_frame)`

Replace the values of variables marked as sensitive with
stars (*********).

---

## ThrottledAdminEmailHandler

```
ThrottledAdminEmailHandler(django.utils.log.AdminEmailHandler)
```

Throttled admin email handler


### Instanced Attributes

These attributes / properties will be available on instances of the class

- cache (`@property`): returns the specific cache handler set up for this purpose

### Methods

#### emit
`def emit(self, record)`

Do whatever it takes to actually log the specified logging record.

This version is intended to be implemented by subclasses and so
raises a NotImplementedError.

---
