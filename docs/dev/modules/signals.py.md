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
fields is updated

---
## new_user_to_guests
`def new_user_to_guests(request, user, sociallogin=None, **kwargs)`

When a user is created via oauth login put them in the guest
group for now.

Unless pdb_settings.AUTO_VERIFY_USERS is toggled on in settings, in which
case users get automatically verified (note that this does
not include email verification, they will still need to do that)

---
## org_delete
`def org_delete(sender, instance, **kwargs)`

When an organization is HARD deleted we want to also remove any
usergroups tied to the organization

---
## org_save
`def org_save(sender, **kwargs)`

we want to create a user group for an organization when that
organization is created

---
## uoar_creation
`def uoar_creation(sender, instance, created=False, **kwargs)`

When a user to organization affiliation request is created
we want to notify the approporiate management entity

We also want to attempt to derive the targeted organization
from the ASN the user provided

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