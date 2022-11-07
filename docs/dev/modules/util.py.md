Generated from util.py on 2022-10-11 12:34:14.972233

# peeringdb_server.util

Assorted utility functions for peeringdb site templates.

# Functions
---

## coerce_ipaddr
`def coerce_ipaddr(value)`

ipaddresses can have multiple formats that are equivalent.
This function will standardize a ipaddress string.

Note: this function is not a validator. If it errors
It will return the original string.

---
