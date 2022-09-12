Generated from util.py on 2022-09-12 13:25:46.155090

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
