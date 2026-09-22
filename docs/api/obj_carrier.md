## Carrier

Identified by the `carrier` tag.

A carrier provides transport between facilities. `name` is unique across PeeringDB,
including against soft-deleted carriers.

The carrier record itself describes the company; where it can actually be reached is
expressed by its `carrierfac` presences.

### Parent relationship:

- `org` organization

### Relationship(s):

- `carrierfac` carrier / facility presence
