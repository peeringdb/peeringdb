# Read-replica routing

PeeringDB can route safe HTTP reads (`GET` / `HEAD` / `OPTIONS`) to a
read-only MySQL replica when one is configured. Writes always hit
primary, and a per-client cookie keeps a recently-writing client pinned
to primary long enough for replication to catch up
(read-your-own-writes).

The whole feature is opt-in twice over and defaults to off, so existing
single-DB deployments are unaffected.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_REPLICA_HOST` | unset | Read replica host. If unset or equal to `DATABASE_HOST`, no `"read"` alias is added and the feature is inert. |
| `DATABASE_REPLICA_PORT` | `DATABASE_PORT` | Replica port. |
| `DATABASE_REPLICA_NAME` | `DATABASE_NAME` | Replica DB name (usually identical to primary). |
| `DATABASE_REPLICA_USER` | `DATABASE_USER` | Replica user. Should have read-only grants. |
| `DATABASE_REPLICA_PASSWORD` | `DATABASE_PASSWORD` | Replica password. |
| `DATABASE_REPLICA_ROUTING_ENABLED` | `False` | Independent kill-switch. Even when a replica is configured, automatic routing only kicks in when this is `True`. Useful for staging the config rollout, and for incidents (flip off without removing the replica). |
| `DATABASE_REPLICA_PIN_COOKIE_MAX_AGE` | `15` (seconds) | TTL of the post-write pin cookie. Defaults to a conservative value matching `django-multidb-router`'s default. Tune down once observed replication lag is known. |

## Behavioral matrix

| Replica configured | Middleware enabled | Effect |
| --- | --- | --- |
| no | _any_ | Identical to today. No `"read"` alias, no router, no middleware. (If middleware is on without a replica, settings emit a warning and stay inert.) |
| yes | no | `"read"` alias exists for ad-hoc `.using("read")`. The router is installed (so `db_for_write` is pinned to `default` and `allow_migrate` blocks DDL against the replica), but the middleware is not, so no automatic per-request routing happens. Useful for staging the replica config before flipping routing on. |
| yes | yes | Production target. GETs route to replica unless the pin cookie is set. POSTs / PUTs / PATCHes / DELETEs always hit primary. |

## How routing decisions are made

The decision is made once, at request start, by
`peeringdb_server.db_replica.ReadReplicaRouterMiddleware`:

- Safe method (`GET` / `HEAD` / `OPTIONS`) **and** no `multidb_pin_writes`
  cookie → flag set, all reads in this request go to `"read"`.
- Any other method, or pin cookie present → flag stays default, all reads
  go to `"default"`.

The router (`peeringdb_server.db_router.DatabaseRouter`) consults the
flag from `db_for_read`. `db_for_write` always returns `"default"` and
`allow_migrate` blocks any DDL against the replica.

## The pin cookie

When a request performs a write (any `post_save` / `post_delete` against
the `"default"` alias inside an active request), the middleware stamps
a `multidb_pin_writes` cookie on the response with
`Max-Age=DATABASE_REPLICA_PIN_COOKIE_MAX_AGE`. The same client's next GETs
within that TTL see the cookie and read from primary. After the cookie
expires the client is back on the replica.

The cookie is set with `HttpOnly`, `SameSite=Lax`, and inherits
`Secure` from `SESSION_COOKIE_SECURE` (so production HTTPS deployments
get `Secure` automatically; HTTP dev does not).

This is per-client, not global: other clients keep reading from the
replica even while one client is pinned.

### Caveat: write-detection blind spots

Detection rides on `post_save` and `post_delete`, which Django fires for
`Model.save()`, `Model.delete()`, and `QuerySet.delete()` (the latter
emits per-instance, including cascades). It does **not** fire for:

- `QuerySet.update()`
- `bulk_create()` (signals are not sent)
- `bulk_update()` (signals are not sent)
- raw SQL via `cursor.execute()` or `connection.execute()`

A request whose only write goes through one of those will not get a pin
cookie, and the same client's next GET could read stale data from the
replica until replication catches up. If a code path uses one of these
forms and read-your-own-writes matters, either:

- wrap the next read with `use_primary_db()`, or
- call `mark_request_wrote()` from `peeringdb_server.db_replica` after
  the bulk operation. That sets the pin-cookie flag for the current
  request's response without requiring a per-read context manager.

### Caveat: API clients don't preserve cookies

Cookie pinning is shaped for browsers, which preserve `Set-Cookie`
across redirects and follow-up requests. Most PeeringDB API consumers
(curl, requests, the SDK, machine-to-machine integrations) discard
cookies between calls. An API client that does
`POST /api/v0/net` immediately followed by `GET /api/v0/net/{id}`:

1. Server stamps `multidb_pin_writes` on the POST response.
2. Client discards the cookie.
3. Client's GET arrives without the cookie → routed to replica.
4. If replication lag exceeds the gap between the two calls, the GET
   reads stale data (or 404 on a freshly-created record).

The severity is bounded by observed replication lag — if lag is
reliably <100ms, the gap is theoretical for almost all workloads. If
lag spikes to seconds, it's a deterministic bug for tight
write-then-read API sequences.

This is a known limitation of the cookie-pinning design and is not
addressed in this slice. Mitigations to consider during the rollout
under #458, after observing actual replication lag in staging:

- Header-based pinning (e.g., a `Pragma: no-replica` request header
  that clients can opt into, or an `X-Pin-Writes-Until` response
  header that documents when it's safe to read from a replica).
- Per-API-key server-side pin tracking (write-time TTL keyed by API
  key, consulted by the middleware).
- Accepting the gap because measured lag is small enough that
  practical client retry logic absorbs it.

## Read-your-own-writes inside a single request

Use `use_primary_db()` from `peeringdb_server.db_replica` for the rare
GET handler that needs to read its own writes synchronously:

```python
from peeringdb_server.db_replica import use_primary_db

def my_view(request):
    with use_primary_db():
        thing = Thing.objects.get(pk=request.GET["pk"])
        ...
```

A decorator form (`primary_db`) is also provided.

## Non-HTTP code paths

Management commands, signals from cron jobs, and the IX-F importer have
no request middleware in the chain, so the routing flag is never set
and they continue to talk to `default`. This is intentional — global
read routing would have broken several of these paths.

## Rollout sequence

1. Provision the read replica and verify replication lag is acceptable.
2. Deploy with `DATABASE_REPLICA_*` configured but
   `DATABASE_REPLICA_ROUTING_ENABLED=False`. The `"read"` alias becomes
   available for ad-hoc `.using("read")` use; no automatic routing yet.
3. Validate ad-hoc replica access and replication health.
4. Flip `DATABASE_REPLICA_ROUTING_ENABLED=True` and monitor:
   - replica connection count and CPU
   - any uptick in stale-read complaints (consider raising
     `DATABASE_REPLICA_PIN_COOKIE_MAX_AGE`)
   - the rate at which `multidb_pin_writes` cookies are being set on
     `GET` responses — every one is a GET-time write hitting primary,
     and a high rate flags code paths the audit follow-up should pick
     up (most are likely incidental cache writes that can move off the
     DB).
5. To roll back without redeploying replica config, set
   `DATABASE_REPLICA_ROUTING_ENABLED=False` and restart workers.

## How tests exercise this

The test settings (`mainsite/settings/run_tests.py` + the
`RELEASE_ENV=run_tests` block at the end of `mainsite/settings/__init__.py`)
install the same router and middleware as production, with the `"read"`
alias backed by `default`'s connection via `TEST = {"MIRROR": "default"}`.
A session-scoped fixture in `tests/conftest.py` aliases the two
`DatabaseWrapper` objects so they share transaction state — without
that, `setUpTestData`'s class-level transaction on `default` would be
invisible to reads via `read` (separate connections, uncommitted-txn
isolation), and every TestCase that combines `setUpTestData` with a
view-based request would fail.

The net effect: every test that hits a view exercises the routing path,
the cookie-pin emission, and the signal-driven write detection without
bootstrapping a second database.

## What is not in this slice

The parent issue (#458) tracks three related follow-ups that are
deliberately out of scope here:

- Switching `SESSION_ENGINE` from DB to `cached_db` (avoids GET-time
  session writes pinning every authenticated user).
- A `pdb_api_cache --database` flag.
- A codebase audit for GET-time writes (which writes need read-your-own
  -writes pinning, which can move to a non-DB store like Redis).
