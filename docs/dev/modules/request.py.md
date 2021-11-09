Generated from request.py on 2021-11-02 10:01:21.611533

# peeringdb_server.request

Django HTTPRequest utilities.

# Functions
---

## bypass_validation
`def bypass_validation(request=None)`

Return whether the specified request is to bypass
certain data quality validations. (#741)

If not request is passed, attempt to get
the current request from the current request
context.

If no request can be obtained this will return False.

---