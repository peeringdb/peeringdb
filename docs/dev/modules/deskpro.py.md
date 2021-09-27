Generated from deskpro.py on 2021-09-27 16:36:34.749378

# peeringdb_server.deskpro

DeskPro API Client used to post and retrieve support ticket information
from the deskpro api.

# Functions
---

## ticket_queue
`def ticket_queue(subject, body, user)`

queue a deskpro ticket for creation

---
## ticket_queue_asnauto_affil
`def ticket_queue_asnauto_affil(user, org, net, rir_data)`

queue deskro ticket creation for asn automation action: affil

---
## ticket_queue_asnauto_create
`def ticket_queue_asnauto_create(user, org, net, rir_data, asn, org_created=False, net_created=False)`

queue deskro ticket creation for asn automation action: create

---
## ticket_queue_asnauto_skipvq
`def ticket_queue_asnauto_skipvq(request, org, net, rir_data)`

queue deskro ticket creation for asn automation action: skip vq

---
## ticket_queue_deletion_prevented
`def ticket_queue_deletion_prevented(request, instance)`

queue deskpro ticket to notify about the prevented
deletion of an object #696

---
## ticket_queue_email_only
`def ticket_queue_email_only(subject, body, email)`

queue a deskpro ticket for creation

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

A mock api client for the deskpro API
that returns an error on post

We use this in our tests, for example
with issue 856.


### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### create_ticket
`def create_ticket(self, ticket=None)`

Creates a deskpro ticket using the deskpro API

Arguments:

- ticket (`DeskProTicket`)

---

## MockAPIClient

```
MockAPIClient(peeringdb_server.deskpro.APIClient)
```

A mock api client for the deskpro API

The IX-F importer uses this when
IXF_SEND_TICKETS=False


### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---
