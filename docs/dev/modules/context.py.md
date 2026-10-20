Generated from context.py on 2026-10-20 12:07:11.547813

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
## is_issuing_at_authorization_endpoint
`def is_issuing_at_authorization_endpoint()`

Returns True if currently inside an issuing_at_authorization_endpoint context.

---
## issuing_at_authorization_endpoint
`def issuing_at_authorization_endpoint()`

Signals that the OAuth authorization endpoint is creating its response,
where implicit and hybrid flows issue tokens without a grant to read
amr from (#490)

Opened by the authorization view itself rather than inferred from the
oauthlib request, whose attributes the client can set through query
parameters.

---
