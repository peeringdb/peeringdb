Generated from request.py on 2022-04-12 16:41:02.631987

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