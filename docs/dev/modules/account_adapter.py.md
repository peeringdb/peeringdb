Generated from account_adapter.py on 2026-11-05 20:07:16.953937

# peeringdb_server.account_adapter

django-allauth account adapter.

# Classes
---

## AccountAdapter

```
AccountAdapter(allauth.account.adapter.DefaultAccountAdapter)
```

The adapter class allows you to override various functionality of the
``allauth.account`` app.  To do so, point ``settings.ACCOUNT_ADAPTER`` to
your own class that derives from ``DefaultAccountAdapter`` and override the
behavior by altering the implementation of the methods according to your own
needs.


### Methods

#### get_email_confirmation_url
`def get_email_confirmation_url(self, request, emailconfirmation)`

Builds the confirmation link from `BASE_URL` instead of the request
`Host`, so the link in the mail always points at this site.

---
