## Internet Exchange Network Information

Identified by the `ixlan` tag.

The peering LAN of an exchange: its prefixes, MTU, route server ASN and IX-F member
export feed.

Each exchange has exactly one ixlan, created with it and sharing its `id`. The two
remain separate object types only for backwards compatibility, and the schema is to
stay unchanged until a major version bump — so do not build on the ability to have
more than one LAN per exchange.

`ixf_ixp_member_list_url` is subject to `ixf_ixp_member_list_url_visible` and is not
returned to callers who are not permitted to see it.

### Parent relationship:

- `ix` internet exchange

### Relationship(s):

- `ixpfx` prefixes
- `netixlan` network to exchange connections (through ixlan)
