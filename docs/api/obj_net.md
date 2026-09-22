## Network

Identified by the `net` tag.

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
