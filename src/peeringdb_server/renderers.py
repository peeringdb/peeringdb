"""
REST API renderer.

Ensure valid json output of the REST API.
"""

from __future__ import annotations

import json
from typing import Any

from rest_framework import renderers
from rest_framework.utils import encoders

from peeringdb_server.rest_throttles import ResponseSizeThrottle


class JSONEncoder(encoders.JSONEncoder):
    """
    Define json encoder to be able to encode
    datatime and django countryfields.

    Make the munge renderer use this encoder to encode json. This approach
    may need to be tidied up a bit.
    """

    def default(self, obj: object) -> Any:
        """Default JSON serializer."""
        # Return stays Any: our branches return str, but the parent
        # encoder's default() returns an unconstrained JSON-encodable value.
        import datetime

        import django_countries.fields

        if isinstance(obj, datetime.datetime):
            return obj.isoformat()

        if isinstance(obj, django_countries.fields.Country):
            return str(obj)

        return encoders.JSONEncoder.default(self, obj)


class MungeRenderer(renderers.BaseRenderer):
    media_type = "text/plain"
    format = "txt"
    charset = "utf-8"

    def render(
        self,
        data: object,
        media_type: str | None = None,
        # renderer_context is DRF's context mapping; it is used here without a
        # None guard yet defaults to None per the base signature, so Any is the
        # only annotation that is both accurate and keeps the body type-clean.
        renderer_context: Any = None,
        file_name: str | None = None,
        # Return stays Any: this returns str (json.dumps) or None (json.dump
        # file path). Narrowing to `str | None` makes MetaJSONRenderer's
        # `len(super().render(...))` a None error, unfixable without a
        # behavior change, and breaks the subclass override (which returns
        # bytes). So the base signature is left permissive on purpose.
    ) -> Any:
        indent = None
        if "request" in renderer_context:
            request = renderer_context.get("request")
            if "pretty" in request.GET:
                indent = 2
        if file_name:
            # json.dump writes to the file and returns None.
            json.dump(data, open(file_name, "w"), cls=JSONEncoder, indent=indent)
            return None
        return json.dumps(data, cls=JSONEncoder, indent=indent)


class MetaJSONRenderer(MungeRenderer):
    """
    Renderer which serializes to JSON.
    Does *not* apply JSON's character escaping for non-ascii characters.
    """

    ensure_ascii = False

    media_type = "application/json"
    format = "json"

    def render(
        self,
        # data is the arbitrary serialized payload: a dict, a list, or None.
        # It is inspected (membership tests, .pop, iteration), so it cannot be
        # narrowed to object and stays Any.
        data: Any,
        accepted_media_type: str | None = None,
        # See MungeRenderer.render: used without a None guard but defaults to
        # None, so Any is the accurate green annotation.
        renderer_context: Any = None,
        file_name: str | None = None,
        default_meta: dict[str, Any] | None = None,
        # Return stays Any: returns bytes (b"") or the parent's str/None. See
        # MungeRenderer.render for why this is not narrowed.
    ) -> Any:
        """
        Tweak output rendering and pass to parent.
        """

        if data is None:
            return b""

        result = {}

        if "__meta" in data:
            meta = data.pop("__meta")
        else:
            meta = default_meta or dict()

        if "request" in renderer_context:
            request = renderer_context.get("request")
            meta.update(getattr(request, "meta_response", {}))
        else:
            request = None

        res = renderer_context["response"]
        if res.status_code < 400:
            if "results" in data:
                result["data"] = data.pop("results")
            elif data:
                if isinstance(data, dict):
                    result["data"] = [data]
                else:
                    result["data"] = [r for r in data if r is not None]
            else:
                result["data"] = []

        elif res.status_code < 500:
            meta["error"] = data.pop("detail", res.reason_phrase)

            result.update(**data)

        elif res.status_code == 500 and "cache_corrupted" in data:
            data.pop("cache_corrupted")
            meta["error"] = data.pop("detail", res.reason_phrase)

            result.update(**data)

        result["meta"] = meta

        rendered_content = super(self.__class__, self).render(
            result, accepted_media_type, renderer_context, file_name=file_name
        )

        # handle caching of response size (#1129)
        if request:
            ResponseSizeThrottle.cache_response_size(request, len(rendered_content))

        return rendered_content
