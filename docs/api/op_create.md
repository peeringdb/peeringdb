## Creating objects

### Status `pending`

Some object types will be flagged as `pending` until they have been reviewed and approved by peeringdb staff.

Currently this is the case for:


- `org` organizations (only administrative staff users are currently allowed to create organizations)
- `fac` facilities
- `net` networks
- `ix` exchanges
- `ixpfx` prefixes (if part of a new exchange)
- `ixlan` exchange networks (if part of a new exchange)

A `pending` object can only be retrieved by callers with update permission on it. Other callers,
including the creator when the object belongs to another organization (for example a suggested
facility or network), get a `404` until it is approved.

### Permissions

To be able to create an object, the requesting user requires `create` permissions to one of the
object's parents in the relationship hierarchy.

For example to create a `net` type object, the user needs to be permissioned to create in the organization
that is to be the network's holder entity.
