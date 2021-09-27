Generated from request.py on 2021-09-27 16:36:34.749378

# peeringdb_server.request

Django HTTPRequest utilities.

# Functions
---

## bypass_validation
`def bypass_validation(request=None)`

Returns whether the specified request is to bypass
certain data quality validations (#741)

If not rquest is passed we will attempt to get
the current request from the current request
context.

If no request can be obtained this will return False

---