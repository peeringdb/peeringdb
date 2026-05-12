import uuid

from django.contrib.sessions.backends.cache import SessionStore as CacheSessionStore


class SessionStore(CacheSessionStore):
    """
    Cache-backed session store that fails fast when the cache is unreachable.

    Django's create() loops up to 10,000 times calling cache.add(), treating any
    falsy return as a key collision. With DJANGO_REDIS_IGNORE_EXCEPTIONS swallowing
    Redis errors, every iteration returns None and the loop runs to completion —
    minutes per request. We round-trip a probe key first so a dead cache surfaces
    in one operation.

    Both the probe key and value are unique per call so concurrent calls against
    a healthy cache cannot dirty each other's probes.
    """

    _PROBE_PREFIX = "__pdb_session_probe__"

    def create(self):
        token = uuid.uuid4().hex
        probe_key = f"{self._PROBE_PREFIX}{token}"
        self._cache.set(probe_key, token, 5)
        if self._cache.get(probe_key) != token:
            raise RuntimeError(
                "Session cache is unavailable; cannot create a new session."
            )
        return super().create()
