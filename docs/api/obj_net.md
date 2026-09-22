## Network

Identified by the `net` tag.

A network is identified by its `asn`, which is unique across PeeringDB and cannot be
changed after creation. `name` is likewise unique, including against soft-deleted
networks.

Because records are reused rather than recreated, an ASN that is released and later
re-registered by a different operator keeps its existing `net` record: `org` changes
and `updated` moves, but `id` and `created` do not. Do not read `created` as the start
of the current operator's registration.

`info_type` is a legacy single value superseded by `info_types`. It carries one of the
network's types, but not a defined one — the two are ordered differently, so do not
read it as `info_types[0]`. Use `info_types` for the full set.

On write, `info_type` replaces `info_types` entirely: whatever it carries becomes the
network's only type, and any `info_types` sent in the same request is discarded. Send
`info_types` and omit `info_type` when writing — a read-modify-write `PUT` that echoes
both fields back drops every type but one, and the response reports no error.

### Parent relationship:

- `org` organization

### Relationship(s):

- `netixlan` network to exchange connections (through `ixlan`)
- `netfac` network / facility presence
- `poc` points of contact

### Metadata:

Carries a `meta` document of standardized optional attributes: a fixed set
of registered keys, each with its own value rules, some of them filterable
via `?meta__<key>=<value>`. The full reference — the mechanism, the key
catalog and the filterability table — is included with this object type in
the API documentation, and lives at `docs/api/object_metadata.md` in the
source repository.
