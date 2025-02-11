Generated from signals.py on 2025-02-11 10:26:48.481231

# peeringdb_server.signals

Django signal handlers

- org usergroup creation
- entity count updates (fac_count, net_count etc.)
- geocode when address model (org, fac) is saved
- verification queue creation on new objects
- asn rdap automation to automatically grant org / network to user
- user to org affiliation handling when targeted org has no users
  - notify admin-com
- CORS enabling for GET api requests

# Functions
---

## addressmodel_save
`def addressmodel_save(sender, instance=None, **kwargs)`

Mark address model objects for geocode sync if one of the address
fields is updated.

---
## campus_status
`def campus_status(sender, instance=None, **kwargs)`

Whenever a campus is saved, set the status of
the campus object based on link facilities

---
## netfac_sync_local_asn_on_save
`def netfac_sync_local_asn_on_save(sender, instance, **kwargs)`

When a networkfacility is saved, sync the local_asn field with the network's asn.

---
## netixlan_sync_asn_on_save
`def netixlan_sync_asn_on_save(sender, instance, **kwargs)`

When a networkixlan is saved, sync the asn field with the network's asn.

---
## new_user_to_guests
`def new_user_to_guests(request, user, sociallogin=None, **kwargs)`

When a user is created via oauth login put them in the guest
group temporarily.

If pdb_settings.AUTO_VERIFY_USERS is toggled on in the settings, users get automatically verified (Note: this does
not include email verification, they will still need to do that).

---
## org_delete
`def org_delete(sender, instance, **kwargs)`

When an organization is HARD deleted, remove any
usergroups tied to the organization.

---
## org_save
`def org_save(sender, **kwargs)`

Create a user group for an organization when that
organization is created.

---
## rir_status_initial
`def rir_status_initial(sender, instance=None, **kwargs)`

Implements `Anytime` network update logic for RIR status handling
laid out in https://github.com/peeringdb/peeringdb/issues/1280

Anytime a network is saved:

if an ASN is added, set rir_status="ok" and set `=created
if an ASN is re-added, set rir_status="ok" and set rir_status_updated=updated

---
## set_campus_to_facility
`def set_campus_to_facility(sender, instance=None, **kwargs)`

Whenever a facility is saved, check the distance between
two facilities and validate if it falls within a CAMPUS_MAX_DISTANCE,
also check if latitude and longitude are in the facility or not

---
## uoar_creation
`def uoar_creation(sender, instance, created=False, **kwargs)`

Notify the approporiate management entity when a user to organization affiliation request is created.

Attempt to derive the targeted organization
from the ASN the user provided.

---
## update_counts_for_ixfac
`def update_counts_for_ixfac(ixfac)`

Whenever a ixfac is saved, update the fac_count for the related Exchange
and update ix_count for the related Facility.

---
## update_counts_for_netfac
`def update_counts_for_netfac(netfac)`

Whenever a netfac is saved, update the fac_count for the related Network
and update net_count for the related Facility.

---
## update_counts_for_netixlan
`def update_counts_for_netixlan(netixlan)`

Whenever a netixlan is saved, update the ix_count for the related Network
and update net_count for the related InternetExchange.

---
## update_network_attribute
`def update_network_attribute(instance, attribute)`

Updates 'attribute' field in Network whenever it's called.

---
# Classes
---

## ESSilentRealTimeSignalProcessor

```
ESSilentRealTimeSignalProcessor(django_elasticsearch_dsl.signals.RealTimeSignalProcessor)
```

Elasticsearch real time signal processor that silently handles
update errors


### Instanced Attributes

These attributes / properties will be available on instances of the class

- log (`@property`): None

### Methods

#### handle_delete
`def handle_delete(self, sender, instance, **kwargs)`

Handle delete.

Given an individual model instance, delete the object from index.

---
#### handle_pre_delete
`def handle_pre_delete(self, sender, instance, **kwargs)`

Handle removing of instance object from related models instance.
We need to do this before the real delete otherwise the relation
doesn't exists anymore and we can't get the related models instance.

---
#### handle_save
`def handle_save(self, sender, instance, **kwargs)`

Handle save.

Given an individual model instance, update the object in the index.
Update the related objects either.

---
