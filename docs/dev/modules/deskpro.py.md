Generated from deskpro.py on 2022-03-07 17:01:26.860132

# peeringdb_server.deskpro

DeskPro API Client used to post and retrieve support ticket information
from the deskpro API.

# Functions
---

## ticket_queue
`def ticket_queue(subject, body, user)`

Queue a deskpro ticket for creation.

---
## ticket_queue_asnauto_affil
`def ticket_queue_asnauto_affil(user, org, net, rir_data)`

Queue deskro ticket creation for asn automation action: affil.

---
## ticket_queue_asnauto_create
`def ticket_queue_asnauto_create(user, org, net, rir_data, asn, org_created=False, net_created=False)`

Queue deskro ticket creation for asn automation action: create.

---
## ticket_queue_asnauto_skipvq
`def ticket_queue_asnauto_skipvq(request, org, net, rir_data)`

Queue deskro ticket creation for asn automation action: skip vq.

---
## ticket_queue_deletion_prevented
`def ticket_queue_deletion_prevented(request, instance)`

Queue deskpro ticket to notify the prevented
deletion of an object #696.

---
## ticket_queue_email_only
`def ticket_queue_email_only(subject, body, email)`

Queue a deskpro ticket for creation.

---
# Classes
---

## APIError

```
APIError(builtins.OSError)
```

Base class for I/O related errors.


### Methods

#### \__init__
`def __init__(self, msg, data)`

Initialize self.  See help(type(self)) for accurate signature.

---

## FailingMockAPIClient

```
FailingMockAPIClient(peeringdb_server.deskpro.MockAPIClient)
```

A mock API client for the deskpro API
that returns an error on post.

Use in tests, for example
with issue 856.


### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### create_ticket
`def create_ticket(self, ticket=None)`

Create a deskpro ticket using the deskpro API.

Arguments:

- ticket (`DeskProTicket`)

---

## MockAPIClient

```
MockAPIClient(peeringdb_server.deskpro.APIClient)
```

A mock API client for the deskpro API.

The IX-F importer uses this when
IXF_SEND_TICKETS=False


### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---
