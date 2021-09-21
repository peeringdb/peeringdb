PeeringDB is using [django-rest-framework](https://www.django-rest-framework.org/) to render its RESTful API.

### Modules

- `serializers.py`: handles object serialization, `depth` expanse, complex querying behavior
- `rest.py`: handles django-rest-framework view set up and querying logic
- `rest_throttles.py`: custom rate limiting handlers
- `renderers.py`: handles rendering of the REST API response

## Serializers

Serializers are defined in `serializers.py` and should extend the custom `ModelSerializer` defined there.

The custom `ModelSerializer` handles depth expansion and also applies some performance fixes for loading relationships.

### Nested data

When adding nested data to a serializer, it should use the `nested` helper function in order for it work properly with the api's `depth` parameter.

## Querying

API queries through url parameters are handled, sanitized and passed to the django query in `rest.py::ModelViewSet::get_queryset`

For more complex queries (e.g., stuff that cannot go into a django queryset filter as one field evaluation), one can define such logic in the
`Serializer` itself using its `prepare_query` method. Check `IXLanPrefixSerializer` and the `whereis` filter for an example.

## View definition

Rest API Views are defined in `rest.py::ModelViewSet`. All reftag objects exposed on the api extend this viewset.

## API cache

Requests that do not do any searches and are not accessing an object directly will make use of api-cache files to render the response.

For example, `/api/net` will use the api-cache, `/api/net/1` and/or `/api/net?id=1` will not.

Api cache files can be generated using the `pdb_api_cache` django command.

## Considerations for changes

When making changes to the API output by adding or removing fields, please consider the following:

- Fields cannot be easily removed from the API once the field has gone live; a field will be there until the next MAJOR version release of the api.
  Therefore, great care should be given when determining to add new fields.
- If a field needs to be deprecated it should remain in the response and be changed to be read-only and set to some pre-determined constant value.
- Some field changes may require people to update their peeringdb client (see below).

## The PeeringDB client

People use the [PeeringDB client](https://github.com/peeringdb/peeringdb-py) to maintain local snapshots of the PeeringDB database.

Like `peeringdb_server` the client uses [django-peeringdb](https://github.com/peeringdb/django-peeringdb) to inform its schema.

When making changes to the API, one should always check that the client sync of that version of the API is still functional with the current version of peeringdb-py.

### Importance of `updated` field

The client uses the `updated` value of an object to determine which objects to fetch for its incremental update.

When writing mass data migrations, one should detemine if this is an update that needs to be propagated to local users snapshots.
If not, it may be better to do it in a way that does not update the `updated` value of the object. This is especially true if it affects already soft-deleted
objects, as they will be included in the incremental update if their `updated` value indicates a change.

### Client compatibilty and when to force it

In some cases, changes to the API means the client is no longer compatible.

You can force a minimum client and / org django-peeringdb version through the `CLIENT_COMPAT` setting.
