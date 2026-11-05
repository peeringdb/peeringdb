Generated from org_admin_views.py on 2026-11-05 20:07:16.953937

# peeringdb_server.org_admin_views

View for organization administrative actions (/org endpoint).

# Functions
---

## approve_affiliation_request
`def approve_affiliation_request(uoar, approved_by, approving_user=None)`

Approve a user request to affiliate with the organization and notify
the organization's other admins.

Shared by the org admin view and the organization users API.

Arguments:

- uoar (`UserOrgAffiliationRequest`)
- approved_by (`str`): name shown to the admins as the approver
- approving_user (`User`): admin that approved, not notified. None
  when the approver is not a user, `approved_by` is recorded instead

---
## extract_permission_id
`def extract_permission_id(source, dest, entity, org, is_session=False)`

Extract a user's permissioning id for the specified
entity from source <dict> and store it in dest <dict>.

Source should be a dict containing django-namespace-perms
(namespace, level) items.

Dest should be a dict where permission ids are to be
exracted to.

Entity can either be a HandleRef instance or class or str.

Org must be an Organization instance that owns the
entity.

is_session to handle the peering sessions permission

---
## load_all_user_permissions
`def load_all_user_permissions(org)`

Return dict of all users with all their permissions for
the given org.
Optimized to use bulk queries instead of individual user queries.

---
## load_entity_permissions
`def load_entity_permissions(org, entity, entity_perms=None, org_entities=None)`

Return entity's permissions for the specified org.
Supports bulk mode when entity_perms and org_entities are provided.

---
## org_admin_required
`def org_admin_required(fnc)`

Decorator function that ensures that the requesting user
has administrative rights to the targeted organization.

An admin who is due for periodic re-authentication with the
organization has no administrative rights until they confirm
their email, and gets a 403 that says so.

Also sets "org" in kwargs.

---
## permission_ids
`def permission_ids(org)`

Return a dict of a valid permissioning ids for
the specified organization.

---
## save_user_permissions
`def save_user_permissions(org, user, perms)`

Save user permissions for the specified org and user.

Perms should be a dict of permissioning ids and permission levels.

---
## target_user_validate
`def target_user_validate(fnc)`

Decorator function that ensures that the targeted user
is a member of the targeted organization.

Should be below org_admin_required.

Also sets "user" in kwargs.

---
