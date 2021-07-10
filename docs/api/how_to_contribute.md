# Contributing to the API documentation

The openapi schema that is used to render the API documentation is generated automatically. However it
is possible for the community to contribute to and augment the documentation by editing the files
located in this (`/docs/api/`) directory.

The contents of these files are joined into the various openapi description fields when the schema file
is regenerated.

Note that changes to these files won't show up in the documentation until the openapi schema file is
regenerated and redeployed.

## Regenerating the schema

```
python manage.py generateschema > peeringdb_server/static/api-schema.yaml
```
