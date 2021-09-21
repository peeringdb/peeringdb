## django-grainy 

PeeringDB users [grainy](https://github.com/20c/grainy) and [django-grainy](https://github.com/20c/django-grainy) to manage user permissions.

`django-grainy` is based on granular permission namespacing, please refer to the documentation above for details.

### Permissioning namespaces

Each object is provided a permissioning namespace:

- `org`: `peeringdb.organization.{org_pk}`
- `ix`: `peeringdb.organization.{org_pk}.internetexchange.{ix_pk}`
- `net`: `peeringdb.organization.{org_pk}.network.{net_pk}`
- `fac`: `peeringdb.organization.{org_pk}.facility.{fac_pk}`
- `ixfac`: `peeringdb.organization.{org_pk}.internetexchange.{ix_pk}.ixfac.{ixfac_pk}`
- `ixlan`: `peeringdb.organization.{org_pk}.internetexchange.{ix_pk}`
  - ixlan has been changed to use the namespace of the exchange
- `ixpfx`: `peeringdb.organization.{org_pk}.internetexchange.{ix_pk}.prefix.{prefix_pk}`
- `poc`: `peeringdb.organization.{org_pk}.network.{net_pk}.poc_set.{users|private|public}`
- `netixlan`: `peeringdb.organization.{org_pk}.network.{net_pk}.ixlan.{netixlan_pk}`
- `netfac`: `peeringdb.organization.{org_pk}.network.{net_pk}.netfac.{netfac_pk}`

### Examples

A user given permissions to `peeringdb.organization.1` would have permissions for that oranization
and all the objects permissioned within it.

A user given permissions to `peeringdb.organization.1.network.1` would only have permissions to the network
with id `1` assuming that network belongs to the organization with id `1`.

A user given permissions to `peeringdb.organization` has permissions to ALL organizations and ALL objects 
permissioned within them.

A user given permissions to `peeringdb.organization.*.network.*.poc_set.users` has permission to view all `user` 
visible points of contact.

### Setting permissions

Permissions can be set using the user and usergroup editors in django-admin.

Permissions can be set by organization admins in their `/org/{org_id}` view using the `Permissions` tool.

## Organization permissions

Each organization maintains a `user` and `admin` user group.

These groups are automatically created in `signals.py` and set up the appropriate permission namespaces
for each group.

The `admin` group for an organization is set up with full write permissions to the org and all objects in the org.

The `user` group for an organization is set up with read only permissions to the org and all objects in the org.

Organization admins may move members between groups in their `/org/{org_id}` view using the `Users` tool.

## Permission holders for REST API requests

When handling a django request to the REST API, it needs to be determined who or what is the permission holder for the request.

It is either a guest (unauthenticated user), a user (through session or user api key auth) or an organization (through org api key auth).

The logic for this exists in `permissions.py`. 

This is already wired up to all API views, but needs to be kept in mind when adding new views.
