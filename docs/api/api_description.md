PeeringDB REST API

## Reading PeeringDB data

The notes below apply to every object type on this API. They describe how records
behave over time, which is the part most consumers of bulk PeeringDB data need and
cannot infer from field types alone.

### Objects are soft-deleted, not removed

With the exception of stale `poc` records, public peering data is *never* hard
deleted. Deleting an object flips its `status` from `ok` to `deleted` and leaves
the record in place, keeping its `id`.

Every object therefore carries a `status`:

- `ok` — live and publicly visible
- `pending` — awaiting review
- `deleted` — soft-deleted, retained but omitted from normal listings

A consumer that mirrors PeeringDB must read `status` and must not treat the absence
of a record from a listing as deletion, nor treat the reappearance of an `id` as a
new record.

Stale `poc` records are the one exception: once soft-deleted, they are hard deleted
after a retention period and will stop appearing entirely.

### `created` is the insert time, not the ownership time

`created` records when the row was first inserted and never changes afterwards. It
survives any number of delete and undelete cycles.

It is not a reliable indicator of who owns an object or for how long:

- An ASN that is released and later re-registered by a different operator reuses the
  existing `net` record. `org` changes, `updated` moves, and `created` continues to
  show the original registration date.
- Organization merges reassign objects to a different `org` without touching
  `created` at all.

Use `created` to order records by first appearance in PeeringDB. Do not use it to
infer the age of the current relationship between an object and its organization.

### `updated` and incremental sync

`updated` moves on every modification, including a change of `status`. Combined with
`?since=`, it is the intended mechanism for incremental synchronization — and because
deletion is a status change, `?since=` returns soft-deleted records too. Those are how
a mirror learns to drop a record, so they must not be filtered out of the response
before processing.

### Identity

`id` is unique per object type and stable for the life of the record, including while
it is soft-deleted. Cross-type identity is the pair of reftag and `id`; an `id` alone
is not unique across the API.
