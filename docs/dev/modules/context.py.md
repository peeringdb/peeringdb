Generated from context.py on 2021-09-17 13:22:42.251452

# peeringdb_server.context

Defines custom context managers

# Functions
---

## current_request
`def current_request(request=None)`

Will yield the current request, if there is one.

To se the current request for the context pass it to
the request parameter.

---