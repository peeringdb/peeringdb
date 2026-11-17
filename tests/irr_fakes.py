"""
Fake IRRd servers for the IRR lookup tests: no network, no import-time side
effects.
"""

from django.conf import settings

# Two-server pool used across the tests.
TWO_SERVERS = [
    {"host": "ntt", "port": 43, "timeout": 5},
    {"host": "radb", "port": 43, "timeout": 5},
]

# Which sources each fake server mirrors (a trimmed, realistic split — NTT lacks
# REACH / BBOI / CANARIE; RADB carries them).
MIRROR = {
    "ntt": ["NTTCOM", "RADB", "RIPE", "ARIN", "APNIC", "AFRINIC", "LACNIC"],
    "radb": ["RADB", "RIPE", "ARIN", "REACH", "BBOI", "CANARIE"],
}


class FakeCache:
    """Minimal in-memory stand-in for caches['negative']."""

    def __init__(self):
        self.store = {}

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value, timeout=None):
        self.store[key] = value


def irrd_list(sources):
    """An !s-lc reply in IRRd framing."""
    body = ",".join(sources)
    return f"A{len(body.encode()) + 1}\n{body}\nC\n"


def irrd_object(object_class, name, source, members=0, descr="mocked"):
    """An object reply in IRRd `!` framing: A<len>, the object text, C."""
    body = f"{object_class}:         {name}\ndescr: {descr}\n"
    if members:
        body += "members: " + ",".join(["AS1"] * members) + "\n"
    body += f"source: {source}"
    return f"A{len(body.encode()) + 1}\n{body}\nC\n"


def make_send(present, mirror=MIRROR, fail_hosts=(), serving=None, large=()):
    """
    Build a _send side_effect that answers like IRRd.

    - present: set of (SOURCE, NAME) tuples that "exist".
    - mirror: host -> list of mirrored sources (for !s-lc).
    - fail_hosts: hosts whose every query raises a timeout (OSError).
    - serving: host -> the sources `!s` accepts, when that differs from the
      advertised (and cached) mirror list.
    - large: (SOURCE, NAME) tuples whose object is too large for one read.

    `!m` returns the first match in the selected sources only, as IRRd's
    key_lookup does, and a failed `!s` keeps the previous selection.
    """

    def _send(server, payload, deadline=None):
        host = server["host"]
        if host in fail_hosts:
            raise TimeoutError("mocked timeout")
        if payload == "!s-lc":
            return irrd_list(mirror.get(host, []))
        accepted = (serving or mirror).get(host, [])
        selected = list(accepted)
        reply = ""
        for command in payload.split("\n"):
            if command == "!q":
                break
            if command.startswith("!s"):
                requested = command[2:].split(",")
                if all(source in accepted for source in requested):
                    selected = requested
                    reply += "C\n"
                else:
                    reply += "F One or more selected sources are unavailable.\n"
            elif command.startswith("!m"):
                object_class, name = command[2:].split(",")
                match = next(
                    (source for source in selected if (source, name) in present),
                    None,
                )
                if match is None:
                    reply += "D\n"
                else:
                    members = 3000 if (match, name) in large else 0
                    reply += irrd_object(object_class, name, match, members)
        # _send stops reading at the cap
        cap = settings.IRR_LOOKUP_MAX_RESPONSE_BYTES
        return reply.encode()[:cap].decode("utf-8", "replace")

    return _send
