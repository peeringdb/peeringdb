## Network Point of Contact

Identified by the `poc` tag.

A contact for a network, which may be a person or a team. `role` states what the
contact is for; `visible` states who may see it. Permissions are applied per
visibility level, so contacts the caller is not entitled to see are not returned at
all rather than returned empty. `Private` is no longer accepted on create or update.

Two behaviours are specific to this object type and matter when mirroring:

- A soft-deleted contact is returned with `name`, `phone`, `email` and `url` blanked,
  so a `?since=` result will carry the deletion but not the contact details.
- Contacts are the one exception to PeeringDB's soft-delete rule. Once soft-deleted
  they are hard deleted after a retention period and stop appearing entirely, so a
  consumer that polls infrequently may never observe the deletion of a contact it has
  already seen.

### Parent relationship:

- `net` network

### Relationship(s):

- None
