Generated from log.py on 2025-05-12 16:19:34.467425

# peeringdb_server.log

# Classes
---

## ThrottledAdminEmailHandler

```
ThrottledAdminEmailHandler(django.utils.log.AdminEmailHandler)
```

Throttled admin email handler


### Instanced Attributes

These attributes / properties will be available on instances of the class

- cache (`@property`): returns the specific cache handler set up for this purpose

### Methods

#### emit
`def emit(self, record)`

Do whatever it takes to actually log the specified logging record.

This version is intended to be implemented by subclasses and so
raises a NotImplementedError.

---
