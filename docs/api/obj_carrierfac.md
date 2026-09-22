## Carrier / Facility presence

Identified by the `carrierfac` tag.

Records that a carrier is available at a facility. A carrier may appear at a facility
only once.

Unlike most object types, a new presence is auto-approved: it is created directly as
`ok` rather than passing through `pending`. Both the carrier and the facility must
themselves be `ok` at the time it is created.

`name` is a convenience copied from the facility and is read-only here.

### Parent relationship:

- `carrier` carrier

### Relationship(s):

- `fac` facility
