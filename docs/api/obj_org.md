## Organization

Identified by the `org` tag.

The organization is at the top of the peeringdb object hierarchy. Every network,
facility, exchange, carrier and campus belongs to exactly one organization, and
ownership of a record is expressed by its `org_id`.

`name` is unique across all organizations, including soft-deleted ones, so the name
of a deleted organization cannot be reused.

Objects can move between organizations without being recreated — through an
organization merge, or when a released ASN is re-registered by a new operator. When
that happens the child object keeps its `id` and its `created`.

### Parent relationship:

- None

### Children relationship(s):

- `net` networks
- `fac` facilities
- `ix` exchanges
- `carrier` carriers
- `campus` campuses
