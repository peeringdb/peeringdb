Generated from log.py on 2026-11-17 18:01:18.661144

# peeringdb_server.log

# Classes
---

## ExceptionReporter

```
ExceptionReporter(django.views.debug.ExceptionReporter)
```

Masks credentials passed in the query string, such as the password reset
token, in the request URL and GET parameters of error reports.

When the filter masks the report wholesale, or a masking step failed, the
report is built with every frame variable and all request data masked,
and the request path hidden. The traceback and the exception stay.


### Methods

#### \__init__
`def __init__(self, request, exc_type, exc_value, tb, is_email=False)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### get_traceback_data
`def get_traceback_data(self)`

Return a dictionary containing traceback information.

---

## ExceptionReporterFilter

```
ExceptionReporterFilter(django.views.debug.SafeExceptionReporterFilter)
```

Masks credentials in error reports.

By name: POST and query string parameters, local variables and the keys
of dicts in local variables. Applies to every view, also those that do
not declare `sensitive_post_parameters` or `sensitive_variables`.

By module: every local variable in the frames of the libraries that hold
credentials under other names, and of form cleaning when the form has a
credential field.

Wholesale: every frame variable and all request data, for routes whose
path carries a credential and when masking itself fails. ExceptionReporter
works on a copy of the filter per report (`for_report`), so the shared
default filter keeps no state.


### Methods

#### cleans_credential_form
`def cleans_credential_form(self, frame)`

Whether the form the frame belongs to has a credential field: a
password input, or a field name masked by name. PeeringDB's own
password forms use plain text fields.

---
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
#### for_report
`def for_report(self, request)`

Returns a copy of the filter for one report, set to mask wholesale on
a route with a credential in the path, or when that can't be told.

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
#### get_safe_cookies
`def get_safe_cookies(self, request)`

Return a dictionary of request.COOKIES with sensitive values redacted.

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
#### mask_wholesale
`def mask_wholesale(self, request, attribute)`

Returns the names of a request mapping, such as META or POST, with
every value masked.

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
#### masked_record
`def masked_record(self, record)`

Returns a copy of the record with the request path masked in its
message (the mail subject) when the report for the request is masked
wholesale. Other handlers keep the record as it is.

---
