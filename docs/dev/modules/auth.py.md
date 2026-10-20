Generated from auth.py on 2026-10-20 12:07:11.547813

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
