## Internet Exchange Prefix

Identified by the `ixpfx` tag.

An IP prefix assigned to an exchange LAN. `prefix` is unique across PeeringDB, so the
same range cannot be registered on two exchanges.

A `netixlan` may only use an address that falls inside one of its LAN's prefixes, which
makes this object the authority on which addresses are valid at an exchange.

`in_dfz` records whether the prefix is routed in the default-free zone.

### Parent relationship:

- `ix` internet exchange

### Relationship(s):

- None

### Deleting the last prefix

An exchange has to keep a globally unique Peering LAN prefix to stay listed, so
deleting the last remaining prefix of an exchange also deletes the exchange
itself. Because that takes the exchange out of the API and public listings, the
request is refused unless it carries an explicit confirmation:

    DELETE /api/ixpfx/<id>?confirm=true

Without the flag the response is a `400` whose `meta` object carries
`confirmation_required: true` and a human readable `error` message. Nothing is
changed by the refused request, and no admin committee ticket is opened for it.

The exchange is removed even if networks are still peering at it or it still
has facility connections, so the message names how many of each go with it.

The exchange is soft-deleted, as any deletion in PeeringDB is: the records stay
in the database and can be restored by the admin committee. Deleting a prefix
while the exchange keeps another active or pending prefix needs no confirmation.
