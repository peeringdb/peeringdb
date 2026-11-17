## Carrier

Identified by the `carrier` tag.

A carrier provides transport between facilities. `name` is unique across PeeringDB,
including against soft-deleted carriers.

`name`, `aka` and `name_long` cannot contain emoji or other pictographic symbols
(such as ★). A write that includes them is rejected with a validation error on
that field.

The carrier record itself describes the company; where it can actually be reached is
expressed by its `carrierfac` presences.

### Parent relationship:

- `org` organization

### Relationship(s):

- `carrierfac` carrier / facility presence
