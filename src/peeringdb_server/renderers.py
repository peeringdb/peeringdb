"""
REST API renderer.

Ensure valid json output of the REST API.
"""

import json

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

    def default(self, obj):
        """Default JSON serializer."""
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

    def render(self, data, media_type=None, renderer_context=None, file_name=None):
        indent = None
        if "request" in renderer_context:
            request = renderer_context.get("request")
            if "pretty" in request.GET:
                indent = 2
        if file_name:
            return json.dump(data, open(file_name, "w"), cls=JSONEncoder, indent=indent)
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
        data,
        accepted_media_type=None,
        renderer_context=None,
        file_name=None,
        default_meta=None,
    ):
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

        result["meta"] = meta

        rendered_content = super(self.__class__, self).render(
            result, accepted_media_type, renderer_context, file_name=file_name
        )

        # handle caching of response size (#1129)
        if request:
            ResponseSizeThrottle.cache_response_size(request, len(rendered_content))

        return rendered_content
