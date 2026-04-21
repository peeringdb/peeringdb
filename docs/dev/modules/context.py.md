Generated from context.py on 2026-04-21 14:00:55.614796

# peeringdb_server.context

Define custom context managers.

# Functions
---

## current_request
`def current_request(request=None)`

Will yield the current request, if there is one.

To se the current request for the context pass it to
the request parameter.

---
## forced_ixlan_deletion
`def forced_ixlan_deletion()`

Signals a forced IXLan deletion is in progress (e.g. orphaned cleanup).

Normally, IXLanPrefix.deletable raises ProtectedAction when active
netixlans exist, stopping the cascade and leaving orphaned records
(peeringdb-py issue #91). This context bypasses that check so the
ixpfx cascade can proceed — netixlans are then deleted by the cascade.

Should only be opened when the caller has verified the IXLan is
orphaned and the deletion is intentional. Standalone ixpfx.delete()
outside this context is unaffected.

---
## is_forced_ixlan_deletion
`def is_forced_ixlan_deletion()`

Returns True if currently inside a forced_ixlan_deletion context.

---