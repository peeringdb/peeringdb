Generated from renderers.py on 2025-02-11 10:26:51.333315

# peeringdb_server.renderers

REST API renderer.

Ensure valid json output of the REST API.

# Classes
---

## JSONEncoder

```
JSONEncoder(rest_framework.utils.encoders.JSONEncoder)
```

Define json encoder to be able to encode
datatime and django countryfields.

Make the munge renderer use this encoder to encode json. This approach
may need to be tidied up a bit.


### Methods

#### default
`def default(self, obj)`

Default JSON serializer.

---

## MetaJSONRenderer

```
MetaJSONRenderer(peeringdb_server.renderers.MungeRenderer)
```

Renderer which serializes to JSON.
Does *not* apply JSON's character escaping for non-ascii characters.


### Methods

#### render
`def render(self, data, accepted_media_type=None, renderer_context=None, file_name=None, default_meta=None)`

Tweak output rendering and pass to parent.

---

## MungeRenderer

```
MungeRenderer(rest_framework.renderers.BaseRenderer)
```

All renderers should extend this class, setting the `media_type`
and `format` attributes, and override the `.render()` method.
