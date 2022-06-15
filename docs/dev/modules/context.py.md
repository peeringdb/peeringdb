Generated from context.py on 2022-06-14 09:38:55.484251

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