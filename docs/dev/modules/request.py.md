Generated from request.py on 2025-07-21 14:23:08.671110

# peeringdb_server.request

Django HTTPRequest utilities.

# Functions
---

## bypass_validation
`def bypass_validation(request=None, check_admin=False)`

Return whether the specified request is to bypass
certain data quality validations. (#741)

If not request is passed, attempt to get
the current request from the current request
context.

If no request can be obtained this will return False.

---
