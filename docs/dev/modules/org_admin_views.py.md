Generated from org_admin_views.py on 2021-09-27 16:36:34.749378

# peeringdb_server.org_admin_views

View for organization administrative actions (/org endpoint).

# Functions
---

## extract_permission_id
`def extract_permission_id(source, dest, entity, org)`

extract a user's permissioning id for the specified
entity from source <dict> and store it in dest <dict>

source should be a dict containing django-namespace-perms
(namespace, level) items

dest should be a dict where permission ids are to be
exracted to

entity can either be a HandleRef instance or clas

org needs to be an Organization instance that owns the
entity

---
## load_all_user_permissions
`def load_all_user_permissions(org)`

Returns dict of all users with all their permissions for
the given org

---
## load_entity_permissions
`def load_entity_permissions(org, entity)`

Returns entity's permissions for the specified org

---
## org_admin_required
`def org_admin_required(fnc)`

Decorator function that ensures that the requesting user
has administrative rights to the targeted organization

Also sets "org" in kwargs

---
## permission_ids
`def permission_ids(org)`

returns a dict of a valid permissioning ids for
the specified organization

---
## save_user_permissions
`def save_user_permissions(org, user, perms)`

Save user permissions for the specified org and user

perms should be a dict of permissioning ids and permission levels

---
## target_user_validate
`def target_user_validate(fnc)`

Decorator function that ensures that the targeted user
is a member of the targeted organization

Should be below org_admin_required

Also sets "user" in kwargs

---