Generated from pagination.py on 2026-05-12 15:10:38.212377

# peeringdb_server.pagination

Shared pagination classes for the PeeringDB REST API.

Extracted here to avoid circular imports between rest.py and api_cache.py.

# Classes
---

## UnlimitedIfNoPagePagination

```
UnlimitedIfNoPagePagination(rest_framework.pagination.PageNumberPagination)
```

A simple page number based style that supports page numbers as
query parameters. For example:

http://api.example.org/accounts/?page=4
http://api.example.org/accounts/?page=4&page_size=100


### Methods

#### build_pagination_meta
`def build_pagination_meta(self)`

Build pagination metadata. Call after paginate_queryset() with pagination_applied=True.

---
#### paginate_queryset
`def paginate_queryset(self, queryset, request, view=None)`

Paginate a queryset if required, either returning a
page object, or `None` if pagination is not configured for this view.

---
