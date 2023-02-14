Generated from util.py on 2023-02-14 15:33:37.135106

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
