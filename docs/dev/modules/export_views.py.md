Generated from export_views.py on 2022-06-14 09:38:55.484251

# peeringdb_server.export_views

Define export views used for IX-F export and advanced search file download.

# Classes
---

## AdvancedSearchExportView

```
AdvancedSearchExportView(peeringdb_server.export_views.ExportView)
```

Allow exporting of advanced search result data.


### Methods

#### fetch
`def fetch(self, request)`

Fetch data from API according to GET parameters.

Note that `limit` and `depth` will be overwritten, other API
parameters will be passed along as-is.

Returns:
    - dict: un-rendered dataset returned by API

---
#### generate
`def generate(self, request)`

Generate data for the reftag specified in self.tag

This function will call generate_<tag> and return the result.

Arguments:
    - request <Request>

Returns:
    - list: list containing rendered data rows ready for export

---
#### generate_fac
`def generate_fac(self, request)`

Fetch facility data from the API according to request and then render
it ready for export.

Arguments:
    - request <Request>

Returns:
    - list: list containing rendered data ready for export

---
#### generate_ix
`def generate_ix(self, request)`

Fetch exchange data from the API according to request and then render
it ready for export.

Arguments:
    - request <Request>

Returns:
    - list: list containing rendered data ready for export

---
#### generate_net
`def generate_net(self, request)`

Fetch network data from the API according to request and then render
it ready for export.

Arguments:
    - request <Request>

Returns:
    - list: list containing rendered data ready for export

---
#### generate_org
`def generate_org(self, request)`

Fetch organization data from the API according to request and then render
it ready for export.

Arguments:
    - request <Request>

Returns:
    - list: list containing rendered data ready for export

---
#### get
`def get(self, request, tag, fmt)`

Handle export.

LGTM Notes: signature-mismatch: order of arguments are defined by the
url routing set up for this view. (e.g., /<tag>/<fmt>)

The `get` method will never be called in a different
context where a mismatching signature would matter so
the lgtm warning can be ignored in this case.

---

## ExportView

```
ExportView(django.views.generic.base.View)
```

Base class for more complex data exports.


### Methods

#### generate
`def generate(self, request)`

Function that generates export data from request.

Override this.

---
#### response_csv
`def response_csv(self, data)`

Return Response object for CSV response.

Arguments:
    - data <list>

Returns:
    - HttpResponse

---
#### response_json
`def response_json(self, data)`

Return Response object for normal json response.

Arguments:
    - data <list|dict>: serializable data, if list is passed you will need
        to specify a value in self.json_root_key

Returns:
    - JsonResponse

---
#### response_json_pretty
`def response_json_pretty(self, data)`

Return Response object for pretty (indented) json response.

Arguments:
    - data <list|dict>: serializable data, if list is passed tou will need
        to specify a value in self.json_root_key

Returns:
    - HttpResponse: http response with appropriate json headers, cannot use
        JsonResponse here because we need to specify indent level

---
