## Network / Facility presence

Identified by the `netfac` tag.

Records that a network is present at a facility. A network may appear at a facility
only once.

`name`, `city` and `country` are conveniences copied from the facility and are
read-only here; `local_asn` is the network's ASN.

### Parent relationship:

- `net` network

### Relationship(s):

- `fac` facility
