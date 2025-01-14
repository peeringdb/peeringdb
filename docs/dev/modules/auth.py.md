Generated from auth.py on 2025-01-14 18:57:08.992842

# peeringdb_server.auth

Authentication utilities for securing API access.

Provides decorators to enforce Basic Authentication or API Key Authentication on IX-F import preview.

# Functions
---

## enable_api_key_auth
`def enable_api_key_auth(fn)`

A simple decorator to enable API Key for a specific view.

---
## enable_basic_auth
`def enable_basic_auth(fn)`

A simple decorator to enable Basic Auth for a specific view.

---
