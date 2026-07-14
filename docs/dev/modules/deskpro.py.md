Generated from deskpro.py on 2026-07-14 15:39:36.347825

# peeringdb_server.deskpro

DeskPro API Client used to post and retrieve support ticket information
from the deskpro API.

# Functions
---

## close_deskpro_ticket_for_vq_item
`def close_deskpro_ticket_for_vq_item(vq_item)`

Flag the DeskPro ticket linked to a VerificationQueueItem for auto-close
when the corresponding pending object is deleted (#1948).

This only touches the database (a single atomic UPDATE) — every decision
that affects the DeskPro side is made later by pdb_deskpro_publish, which
is the single writer of DeskPro state. This avoids any race with the
publisher:

- If the ticket has not been published yet, the publisher skips it (it
  excludes close_requested tickets) and the close pass deletes the local
  row — so it is never sent.
- If it has already been published, the close pass resolves it via the API.

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
## ticket_queue_prefixauto_approve
`def ticket_queue_prefixauto_approve(user, ix, prefix)`

Queue deskro ticket creation for prefix automation action: create.

---
## ticket_queue_rir_status_updates
`def ticket_queue_rir_status_updates(networks, threshold, date)`

Queue a single deskpro ticket creation for multiple network RIR status
updates and raise an exception if the threshold is exceeded.

:param networks: List of network objects that have updated RIR status.
:param threshold: Threshold number for network count to raise exception.
:param date: Date of RIR status update.

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
#### close_ticket
`def close_ticket(self, deskpro_id)`

Resolve a ticket on DeskPro by id (#1948).

The ticket is only resolved if its current status on the DeskPro
side is one of settings.DESKPRO_AUTO_CLOSE_STATUSES (default
["awaiting_agent"]). This avoids closing tickets an agent has
already moved on (e.g. awaiting_user, resolved). DeskPro has no
conditional update, so we GET the current status first.

Returns True if the ticket was resolved, False otherwise.

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
#### close_ticket
`def close_ticket(self, deskpro_id)`

Resolve a ticket on DeskPro by id (#1948).

The ticket is only resolved if its current status on the DeskPro
side is one of settings.DESKPRO_AUTO_CLOSE_STATUSES (default
["awaiting_agent"]). This avoids closing tickets an agent has
already moved on (e.g. awaiting_user, resolved). DeskPro has no
conditional update, so we GET the current status first.

Returns True if the ticket was resolved, False otherwise.

---
