## Internet Exchange

Identified by the `ix` tag.

An exchange is the administrative record for an IXP. `name` is unique across
PeeringDB, including against soft-deleted exchanges.

The participant-facing configuration — prefixes, MTU, route server ASN and the IX-F
member list URL — lives on the exchange's `ixlan`, not here. Each exchange has
exactly one `ixlan`, whose `id` matches the exchange's own.

Creating an exchange requires a `prefix`, which is used to create that LAN's first
prefix. An `ixf_ixp_member_list_url` may also be supplied on create to support
automatic approval. Both are write-only and ignored on update.

### Parent relationship:

- `org` organization

### Relationship(s):

- `ixlan` internet exchange network information
- `ixfac` exchange / facility presence
