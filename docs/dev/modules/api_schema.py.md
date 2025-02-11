Generated from api_schema.py on 2025-02-11 10:26:48.481231

# peeringdb_server.api_schema

Augment REST API schema to use for open-api schema generation.

open-api schema generation leans heavily on automatic generation
implemented through the django-rest-framework.

Specify custom fields to be added to the generated open-api schema.

# Classes
---

## BaseSchema

```
BaseSchema(rest_framework.schemas.openapi.AutoSchema)
```

Augments the openapi schema generation for
the peeringdb API docs.


### Methods

#### augment_create_ix
`def augment_create_ix(self, serializer, model, op_dict)`

Augment openapi schema for create ix operation.

---
#### augment_create_operation
`def augment_create_operation(self, op_dict, op_args)`

Augment openapi schema for object creation.

---
#### augment_delete_operation
`def augment_delete_operation(self, op_dict, op_args)`

Augment openapi schema for delete operation.

---
#### augment_list_filters
`def augment_list_filters(self, model, serializer, parameters)`

Further augment openapi schema for object listing by filling
the query parameter list with all the possible query filters
for the object.

---
#### augment_list_operation
`def augment_list_operation(self, op_dict, op_args)`

Augment openapi schema for object listings.

---
#### augment_retrieve_operation
`def augment_retrieve_operation(self, op_dict, op_args)`

Augment openapi schema for single object retrieval.

---
#### augment_update_fac
`def augment_update_fac(self, serializer, model, op_dict)`

Augment openapi schema for update fac operation.

---
#### augment_update_ix
`def augment_update_ix(self, serializer, model, op_dict)`

Augment openapi schema for update ix operation.

---
#### augment_update_net
`def augment_update_net(self, serializer, model, op_dict)`

Augment openapi schema for update net operation.

---
#### augment_update_operation
`def augment_update_operation(self, op_dict, op_args)`

Augment openapi schema for update operation.

---
#### get_classes
`def get_classes(self, *op_args)`

Try to relate a serializer and model class to the openapi operation.

Returns:

- tuple(serializers.Serializer, models.Model)

---
#### get_operation
`def get_operation(self, *args, **kwargs)`

Override this so we can augment the operation dict
for an openapi schema operation.

---
#### get_operation_id
`def get_operation_id(self, path, method)`

Override this so operation ids become "{op} {reftag}"

---
#### get_operation_type
`def get_operation_type(self, *args)`

Determine if this is a list retrieval operation.

---
#### request_body_schema
`def request_body_schema(self, op_dict, content=application/json)`

Helper function that return the request body schema
for the specified content type.

---
