## Campus

Identified by the `campus` tag.

A campus groups facilities that are close enough to be treated as one interconnection
location. A facility can only join a campus if it has geocoordinates and sits within
the campus distance limit of the facilities already in it.

`name` is unique across PeeringDB, including against soft-deleted campuses.

`name`, `aka` and `name_long` cannot contain emoji or other pictographic symbols
(such as ★). A write that includes them is rejected with a validation error on
that field.

The address fields — `city`, `country`, `state`, `zipcode` — are not stored on the
campus. They are read from its first facility and are empty while the campus has
none, so they can change without the campus itself being modified.

### Parent relationship:

- `org` organization

### Relationship(s):

- `fac` facilities
