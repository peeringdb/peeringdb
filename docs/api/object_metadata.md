## Object metadata

Some object types carry a `meta` field: a single JSON document holding
standardized, optional attributes that do not warrant a column of their own.

`meta` is available on `net` and `netixlan`.

### Registered keys only

The keys a `meta` document may contain are defined by a server-side registry.
A write containing an unregistered key is rejected:

```json
{"meta": {"rtbh_community": "65000:666"}}          // accepted
{"meta": {"something_i_invented": true}}           // 400, "unregistered metadata key"
```

There is deliberately no free-form namespace. Uncontrolled keys cannot be
validated, cannot be documented, and cannot be retired once clients depend on
them.

Because the registry lives on the server, keys can be added, changed, or
retired without a new release of the client model library. Clients that only
read `meta` can treat it as an opaque document and will not break when the key
set changes.

### Writing metadata

Two forms are accepted, and they can be mixed. Use `PUT`; `PATCH` is not
supported. Include the endpoint's required update fields along with the
metadata. In these examples, replace the network's name, ASN, organization ID,
and website with its current values.

Write the document directly. This **replaces** the whole document, so include
every key you want to keep:

```http
PUT /api/net/1
Content-Type: application/json

{
  "name": "Example Network",
  "asn": 63350,
  "org_id": 1,
  "website": "https://example.com",
  "meta": {"rtbh_community": "65000:666", "preferred_ip_mtu": 9000}
}
```

Or write a single key through its flat field. These are write-only convenience
fields, folded into the document on the server, and they leave every other key
untouched — which is what the web UI uses:

```http
PUT /api/net/1
Content-Type: application/json

{
  "name": "Example Network",
  "asn": 63350,
  "org_id": 1,
  "website": "https://example.com",
  "rtbh_community": "65000:666"
}
```

Submit a flat field blank (or `null`) to remove its key. Every flat field is
clearable this way, including the boolean ones — for a boolean, "unset" is a
third state distinct from `false`. For a multi-part key such as
`planned_status_change`, clearing either part clears the whole key — but
clearing one part while submitting a value for the other is rejected, with
the error reported against the part you submitted. Writing only one part of
a key that is not already set is rejected against the missing part.

Metadata is read back only under `meta`; the flat fields never appear in API
output.

Invalid metadata returns HTTP 400. Validation details for the `meta` field
appear under `meta.field_errors.meta` in the response envelope, alongside the
usual `meta.error` summary:

```json
{
  "meta": {
    "error": "Bad Request",
    "field_errors": {
      "meta": {"something_i_invented": "unregistered metadata key"}
    }
  }
}
```

### Launch keys

| Key | Object | Type | Filterable |
|---|---|---|---|
| `planned_status_change` | `netixlan` | `{status, date}` | yes |
| `rfc8950` | `netixlan` | boolean | yes |
| `preferred_ip_mtu` | `net` | integer | no |
| `rtbh_community` | `net` | string | no |

#### `planned_status_change` (netixlan)

A declaration of intent about the connection's `status` field.

- `status` — `deleted` (the network is leaving the exchange) or `ok` (the
  connection goes live on that date).
- `date` — `YYYY-MM-DD`, in the future at write time and within a configurable
  window ahead (18 months by default).

Flat fields: `planned_status_change_status`, `planned_status_change_date`.

A plan is a statement, not a schedule. Nothing happens automatically when the
date arrives: the object's own fields are never changed by the plan, the plan
is never changed by the object, and a date that passes without the change
persists until the network edits it. Read plans alongside current state and
draw your own conclusions.

The future-date requirement applies to *setting* a date, not to keeping one.
A write that resubmits an already-stored plan unchanged is accepted whatever
its date, so a plan whose date has passed never blocks other edits to the
object — which matters because a full-object `PUT` round-trips `meta`.

A set plan is shown publicly as a "planned removal ‹date›" / "planned
activation ‹date›" marker on the connection's row, beside the existing
not-operational indicator.

Announcing a departure is entirely the network's choice.

#### `rfc8950` (netixlan)

Boolean. The network supports RFC8950 extended next hop on this connection.
Shown publicly as an `RFC8950` marker on the connection's row in the network
and exchange views.

Flat field: `rfc8950`. It is tri-state — send `true`, `false`, or `null` to
remove the key.

`true` and `false` are both meaningful and are distinguishable from an unset
key, so `?meta__rfc8950=false` returns only connections explicitly marked as
not supporting it — not connections that never declared.

#### `preferred_ip_mtu` (net)

Integer. Preferred IP MTU for private network interconnection with this network.
The accepted range is a deployment setting.

#### `rtbh_community` (net)

String. The BGP community this network accepts for remote-triggered
blackholing, so peers can pick it up at provisioning time instead of reading
it out of a peering policy page.

Accepted formats:

- standard — `asn:value`, each part 0–65535
- large — `asn:local1:local2`, each part 0–4294967295

Extended communities are **not** accepted. One community per network; comma
separated lists are rejected.

Values are stored canonically, so leading zeros are dropped — `065000:0666` is
stored, and returned, as `65000:666`. Compare the canonical form when matching.

### Filtering

A key marked filterable can be used in queries, with the usual operators:

```
GET /api/netixlan?ix=26&meta__planned_status_change__status=deleted&meta__planned_status_change__date__lt=2026-10-15
GET /api/netixlan?meta__rfc8950=true
```

These are indexed database queries against typed columns derived from the
document, so date and integer comparisons behave correctly rather than
comparing strings.

Keys **not** marked filterable cannot be queried. Note the failure mode: an
unrecognized filter parameter is ignored rather than rejected, so
`?meta__rtbh_community=65000:666` returns the full unfiltered list rather than
an error. Filter on a non-filterable key only after checking the table above.
