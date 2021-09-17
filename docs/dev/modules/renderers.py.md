# peeringdb_server.renderers

REST API renderer

Ensures valid json output of the REST API

# Classes
---

## JSONEncoder

```
JSONEncoder(rest_framework.utils.encoders.JSONEncoder)
```

Im defining our own json encoder here in order to be able to encode
datatime and django countryfields.

Im making the munge renderer use this encoder to encode json, this approach
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
`def render(self, data, accepted_media_type=None, renderer_context=None)`

Tweak output rendering and pass to parent

---

## MungeRenderer

```
MungeRenderer(rest_framework.renderers.BaseRenderer)
```

All renderers should extend this class, setting the `media_type`
and `format` attributes, and override the `.render()` method.

