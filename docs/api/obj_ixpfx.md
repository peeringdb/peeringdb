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
