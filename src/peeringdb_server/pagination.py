"""
Shared pagination classes for the PeeringDB REST API.

Extracted here to avoid circular imports between rest.py and api_cache.py.
"""

from django.conf import settings as dj_settings
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class UnlimitedIfNoPagePagination(PageNumberPagination):
    page_size = dj_settings.PAGE_SIZE  # default page_size
    page_size_query_param = "per_page"
    max_page_size = 250

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        if "page" in request.query_params:
            self.pagination_applied = True
            return super().paginate_queryset(queryset, request)
        else:
            self.pagination_applied = False
            return list(queryset)  # Return all without pagination

    def get_paginated_response(self, data):
        return Response(
            {
                "count": len(data),
                "next": None,
                "previous": None,
                "results": data,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "required": ["data", "meta"],
            "properties": {
                "data": schema,
                "meta": {
                    "type": "object",
                    "properties": {
                        "generated": {
                            "type": "number",
                            "description": "Unix timestamp of when the cached response was generated. Only present for cached responses.",
                        },
                        "pagination": {
                            "type": "object",
                            "description": "Only present when using the ?page= parameter.",
                            "properties": {
                                "count": {"type": "integer"},
                                "has_next": {"type": "boolean"},
                                "has_previous": {"type": "boolean"},
                                "next": {
                                    "type": "string",
                                    "nullable": True,
                                    "format": "uri",
                                },
                                "previous": {
                                    "type": "string",
                                    "nullable": True,
                                    "format": "uri",
                                },
                                "page": {"type": "integer"},
                                "per_page": {"type": "integer"},
                                "total_pages": {"type": "integer"},
                            },
                        },
                    },
                },
            },
        }

    def build_pagination_meta(self):
        """Build pagination metadata. Call after paginate_queryset() with pagination_applied=True."""
        return {
            "count": self.page.paginator.count,
            "has_next": self.page.has_next(),
            "has_previous": self.page.has_previous(),
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "page": self.page.number,
            "per_page": self.page.paginator.per_page,
            "total_pages": self.page.paginator.num_pages,
        }
