Generated from signals.py on 2023-04-12 10:09:44.563425

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
