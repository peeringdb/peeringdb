Generated from autocomplete_views.py on 2026-11-05 20:07:16.953937

# peeringdb_server.autocomplete_views

Autocomplete views.

Handle most autocomplete functionality found in peeringdb.

Note: Quick search behavior is specified in search.py

# Classes
---

## ASNAutocomplete

```
ASNAutocomplete(peeringdb_server.autocomplete_views.AutocompleteHTMLResponse)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## AdminLookupPermissionMixin

```
AdminLookupPermissionMixin(builtins.object)
```

Limit grappelli's lookup views to models registered on the admin site
that the requesting user may view.

Stock grappelli only checks is_staff, resolves any installed model,
queries its default manager and applies caller supplied ORM filters
(`query_string`) and return fields (`to_field`), which lets any staff
account read any column of any table.


## AutocompleteHTMLResponse

```
AutocompleteHTMLResponse(dal_select2.views.Select2QuerySetView)
```

List options for a Select2 widget.


### Methods

#### render_to_response
`def render_to_response(self, context)`

Return a JSON response in Select2 format.

---

## BaseFacilityAutocompleteForPort

```
BaseFacilityAutocompleteForPort(peeringdb_server.autocomplete_views.AutocompleteHTMLResponse)
```

Base class for facility autocomplete for ports.

Provides the base queryset and result label logic for filtering
facilities based on a search query (name or address1) and ordering
by the facility's name. This class is intended to be extended by
more specific facility-related autocomplete classes.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## CommandLineToolHistoryAutocomplete

```
CommandLineToolHistoryAutocomplete(dal_select2.views.Select2QuerySetView)
```

Autocomplete for command line tools that were run via the admin ui.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## DeletedVersionAutocomplete

```
DeletedVersionAutocomplete(dal_select2.views.Select2QuerySetView)
```

Autocomplete that will show reversion versions where an object
was set to deleted.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## ExchangeAutocomplete

```
ExchangeAutocomplete(peeringdb_server.autocomplete_views.AutocompleteHTMLResponse)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## ExchangeAutocompleteJSON

```
ExchangeAutocompleteJSON(dal_select2.views.Select2QuerySetView)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---

## FacilityAutocomplete

```
FacilityAutocomplete(peeringdb_server.autocomplete_views.AutocompleteHTMLResponse)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## FacilityAutocompleteForExchange

```
FacilityAutocompleteForExchange(peeringdb_server.autocomplete_views.FacilityAutocomplete)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---

## FacilityAutocompleteForNetwork

```
FacilityAutocompleteForNetwork(peeringdb_server.autocomplete_views.FacilityAutocomplete)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---

## FacilityAutocompleteForOrganization

```
FacilityAutocompleteForOrganization(peeringdb_server.autocomplete_views.FacilityAutocomplete)
```

List of facilities under same organization ownership


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---

## FacilityAutocompleteJSON

```
FacilityAutocompleteJSON(dal_select2.views.Select2QuerySetView)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---

## FacilityNameAutocomplete

```
FacilityNameAutocomplete(peeringdb_server.autocomplete_views.AutocompleteHTMLResponse)
```

Autocomplete for the Facility Name field in Advanced Search.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## GrappelliHandlerefAutocomplete

```
GrappelliHandlerefAutocomplete(peeringdb_server.autocomplete_views.PDBAdminGrappelliAutocomplete)
```

Make sure that the auto-complete fields managed
by grappelli in django admin exclude soft-deleted
objects.


## IXLanAutocomplete

```
IXLanAutocomplete(peeringdb_server.autocomplete_views.AutocompleteHTMLResponse)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## InternetExchangeFacilityAutoComplete

```
InternetExchangeFacilityAutoComplete(peeringdb_server.autocomplete_views.BaseFacilityAutocompleteForPort)
```

Autocomplete class for facilities within a specific Internet Exchange (IX).

Extends the base class to filter facilities associated with a specific
Internet Exchange. The `ix_id` parameter is used to filter the related
facilities.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---

## NetworkAutocomplete

```
NetworkAutocomplete(peeringdb_server.autocomplete_views.AutocompleteHTMLResponse)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## NetworkFacilityAutocomplete

```
NetworkFacilityAutocomplete(peeringdb_server.autocomplete_views.BaseFacilityAutocompleteForPort)
```

Autocomplete class for facilities within a specific network.

Extends the base class to filter facilities associated with a
specific network. Excludes facilities not linked to the network.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---

## OrganizationAutocomplete

```
OrganizationAutocomplete(peeringdb_server.autocomplete_views.AutocompleteHTMLResponse)
```

List options for a Select2 widget.


### Methods

#### get_queryset
`def get_queryset(self)`

Filter the queryset with GET['q'].

---
#### get_result_label
`def get_result_label(self, item)`

Return the label of a result.

---

## PDBAdminGrappelliAutocomplete

```
PDBAdminGrappelliAutocomplete(peeringdb_server.autocomplete_views.AdminLookupPermissionMixin, grappelli.views.related.AutocompleteLookup)
```

Limit grappelli's lookup views to models registered on the admin site
that the requesting user may view.

Stock grappelli only checks is_staff, resolves any installed model,
queries its default manager and applies caller supplied ORM filters
(`query_string`) and return fields (`to_field`), which lets any staff
account read any column of any table.


## PDBAdminM2MLookup

```
PDBAdminM2MLookup(peeringdb_server.autocomplete_views.AdminLookupPermissionMixin, grappelli.views.related.M2MLookup)
```

Limit grappelli's lookup views to models registered on the admin site
that the requesting user may view.

Stock grappelli only checks is_staff, resolves any installed model,
queries its default manager and applies caller supplied ORM filters
(`query_string`) and return fields (`to_field`), which lets any staff
account read any column of any table.


## PDBAdminRelatedLookup

```
PDBAdminRelatedLookup(peeringdb_server.autocomplete_views.AdminLookupPermissionMixin, grappelli.views.related.RelatedLookup)
```

Limit grappelli's lookup views to models registered on the admin site
that the requesting user may view.

Stock grappelli only checks is_staff, resolves any installed model,
queries its default manager and applies caller supplied ORM filters
(`query_string`) and return fields (`to_field`), which lets any staff
account read any column of any table.


## ToolHistory

```
ToolHistory(peeringdb_server.autocomplete_views.CommandLineToolHistoryAutocomplete)
```

Autocomplete for command line tools that were run via the admin ui.
