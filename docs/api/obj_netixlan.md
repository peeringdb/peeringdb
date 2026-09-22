## Network to Internet Exchange connection

Identified by the `netixlan` tag.

A single network's connection to an exchange LAN — its addresses, capacity and route
server participation. This is the object that expresses "network X is present at
exchange Y", and it is the highest-volume object type on the API.

`ipaddr4` and `ipaddr6` must each fall inside one of the LAN's prefixes, and each
address may be claimed by only one connection.

Records on networks with `allow_ixp_update` set may be created, modified or removed
automatically from the exchange's IX-F member export rather than by the network
itself. Such a network can exempt individual fields from those updates through
`ixp_update_exclude`.

### Parent relationship:

- `net` network

### Relationship(s):

- `ixlan` internet exchange network information

### Metadata:

Carries a `meta` document of standardized optional attributes: a fixed set
of registered keys, each with its own value rules, some of them filterable
via `?meta__<key>=<value>`. The full reference — the mechanism, the key
catalog and the filterability table — is included with this object type in
the API documentation, and lives at `docs/api/object_metadata.md` in the
source repository.

### Status and operational:

A `netixlan` has two independent things going on: a **lifecycle** (does the
connection exist publicly?) and an **operational state** (is traffic actually
flowing over it?). Historically these were two fields — `status` for the
lifecycle and a boolean `operational` for the state. They are now both
carried by `status`, which takes a fourth value in addition to the usual
`ok` / `pending` / `deleted`:

| `status` | Live? | `operational` | Meaning |
|---|---|---|---|
| `ok` | yes | `true` | published and operational |
| `not-operational` | yes | `false` | published, declared not operational |
| `pending` | no | — | awaiting approval, not publicly visible |
| `deleted` | no | — | removed |

`ok` and `not-operational` are both **live** statuses. A `not-operational`
connection is a published member of the exchange, listed in the network and
exchange views with a "not operational" marker — exactly as it was when it
was `ok` with `operational: false`. The change is in how the state is
represented, not in what it means.

#### How status moves

```text
  lifecycle                          live statuses
  (server-controlled)                (network-controlled)

  +-----------+                +---------------------------------------+
  |  pending  | -- approval -> |                                       |
  +-----------+                |   +------+   PUT status /    +-----------------+
                               |   |  ok  | <--------------> | not-operational |
                               |   +------+   IX-F import    +-----------------+
                               |                                       |
                               +-------------------+-------------------+
                                                   |
                                         delete (API / web UI /
                                         IX-F import removal)
                                                   |
                                                   v
                                             +-----------+
                                             |  deleted  |
                                             +-----------+
```

- Moving **between `ok` and `not-operational`** is the network's call. It
  happens through an API write of `status`, through the web UI, or through
  the exchange's IX-F member list when the network has allowed IX-F updates
  for the connection (the export's `operational` flag picks the live status).
- Moving **into or out of the live box** (`pending` → live, live → `deleted`)
  is a lifecycle transition and stays server-controlled: approval, deletion,
  IX-F import removal. The API rejects an attempt to write `pending` or
  `deleted`, and will never move a `pending` connection into a live status
  through the operational mapping described below.

#### Writing the state

Write `status` with one of the two live values. Include the endpoint's
required update fields as usual; in this example replace them with the
connection's current values:

```http
PUT /api/netixlan/1
Content-Type: application/json

{
  "net_id": 1,
  "ixlan_id": 1,
  "asn": 63350,
  "speed": 10000,
  "ipaddr4": "203.0.113.10",
  "ipaddr6": "2001:db8::10",
  "status": "not-operational"
}
```

For a **deprecation window**, a write to the old boolean keeps working: it
is mapped onto `status` so existing clients need no change yet. After the
window it is rejected; migrate to writing `status`.

| Client sends | Connection is | Result |
|---|---|---|
| `status: "not-operational"` | live | `not-operational`, `operational: false` |
| `status: "ok"` | live | `ok`, `operational: true` |
| `operational: false` (legacy) | live, or a create | mapped to `status: "not-operational"` |
| `operational: true` (legacy) | live, or a create | mapped to `status: "ok"` |
| both, and `status` differs from the stored value | live | `status` wins, `operational` is ignored |
| both, and `status` is just echoed back unchanged | live | `operational` is mapped (a full-object `PUT` round-trip must not lose the write) |
| `operational: anything` | `pending` | ignored: `operational` is read-only and the mapping never touches a non-live connection |
| `status: "pending"` or `"deleted"` | any | `400`, `status may only be set to 'ok' or 'not-operational'` |

A full-object `PUT` that echoes back the connection's current `status`
unchanged is always accepted, whatever that status is — including `pending`.
Only a *change* of `status` is restricted to the two live values.

#### Reading the state

- `operational` is still served on every response. It is now **read-only and
  derived** from `status` (`operational == (status == "ok")`), so read paths
  that use it keep working unchanged.
- **A filter on `status=ok` no longer returns every live connection.** Filter
  on `status__in=ok,not-operational` — or drop the status filter, since
  non-live objects are not served to begin with — otherwise connections that
  are simply not operational disappear from your view.
- Existing connections that were `ok` with `operational: false` at the time
  of the change were migrated to `not-operational`, with their `updated`
  timestamp bumped. A client that syncs incrementally on `since` picks them
  up on its next run; a client that filters on `status=ok` will see them
  vanish from that view unless it adjusts the filter as above.
- A connection's *planned* status changes — a network announcing that it is
  leaving, or that a connection goes live on a date — are a separate,
  purely declarative mechanism carried in `meta.planned_status_change`; see
  the metadata reference below. A plan never changes `status` by itself.
