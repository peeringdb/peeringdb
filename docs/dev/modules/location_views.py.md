Generated from location_views.py on 2026-09-22 17:40:35.243351

# peeringdb_server.location_views

Session-authenticated location helpers for the website editor.

# Classes
---

## LocationRequest

```
LocationRequest(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## LocationSaveRequest

```
LocationSaveRequest(peeringdb_server.location_views.LocationRequest)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## LocationSaveView

```
LocationSaveView(peeringdb_server.location_views.LocationView)
```

Intentionally simple parent class for all views. Only implements
dispatch-by-method and simple sanity checking.


## LocationView

```
LocationView(django.views.generic.base.View)
```

Intentionally simple parent class for all views. Only implements
dispatch-by-method and simple sanity checking.


### Methods

#### \__annotate_func__
`def __annotate_func__(format)`

The type of the None singleton.

---
