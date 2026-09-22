## Facility (Datacenter)

Identified by the `fac` tag.

A facility is a physical location where networks and exchanges interconnect. `name`
is unique across PeeringDB, including against soft-deleted facilities.

`region_continent` is derived server-side from `country` and is read-only, and values
submitted for `rencode` are ignored.

`latitude` and `longitude` are geocoded from the postal address on create, and values
submitted there are ignored. On update they are writable, but only within a limit that
depends on `city`: if `city` is unchanged, the new pair must be within 1km of the
current one; if `city` changes in the same request, the new pair must instead be within
50km of the new city's centre. Existing coordinates cannot be cleared. A change to the
coordinates alone does not trigger a new geocoding pass, so the submitted values are
kept.

A facility may belong to a `campus`, which requires it to have geocoordinates and to
sit within the campus distance limit.

### Parent relationship:

- `org` organization

### Relationship(s):

- `ixfac` exchange / facility presence
- `netfac` network / facility presence
- `carrierfac` carrier / facility presence
- `campus` campus membership
