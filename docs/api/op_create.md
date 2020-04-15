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

### Permissions

To be able to create an object, the requesting user requires `create` permissions to one of the
object's parents in the relationship hierarchy.

For example to create a `net` type object, the user needs to be permissioned to create in the organzation
that is to be the network's holder entity.
