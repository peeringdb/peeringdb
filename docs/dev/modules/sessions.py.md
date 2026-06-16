Generated from sessions.py on 2026-06-16 15:01:18.257870

# peeringdb_server.sessions

# Classes
---

## SessionStore

```
SessionStore(django.contrib.sessions.backends.cache.SessionStore)
```

Cache-backed session store that fails fast when the cache is unreachable.

Django's create() loops up to 10,000 times calling cache.add(), treating any
falsy return as a key collision. With DJANGO_REDIS_IGNORE_EXCEPTIONS swallowing
Redis errors, every iteration returns None and the loop runs to completion —
minutes per request. We round-trip a probe key first so a dead cache surfaces
in one operation.

Both the probe key and value are unique per call so concurrent calls against
a healthy cache cannot dirty each other's probes.


### Methods

#### create
`def create(self)`

Create a new session instance. Guaranteed to create a new object with
a unique key and will have saved the result once (with empty data)
before the method returns.

---
