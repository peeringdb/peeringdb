Generated from permissions.py on 2026-11-05 20:07:16.953937

# peeringdb_server.permissions

Utilities for permission handling.

Permission logic is handled through django-grainy.

API key auth is handled through djangorestframework-api-key.

Determine permission holder from request (api key or user).

Read only user api key handling.

Censor API output data according to permissions using grainy Applicators.

# Functions
---

## adjust_permissions_for_periodic_reauth
`def adjust_permissions_for_periodic_reauth(user, perms)`

Strip the user's permissions for every organization that currently
flags the user as needing re-authentication.

---
## check_permissions
`def check_permissions(obj, target, permissions, **kwargs)`

Use the provided permission holding object to initialize
the Permissions Util, which then checks permissions.

---
## check_permissions_from_request
`def check_permissions_from_request(request, target, flag, **kwargs)`

Call the check_permissions util but takes a request as
input, not a permission-holding object.

---
## get_key_from_request
`def get_key_from_request(request)`

Use the default KeyParser from drf-api-keys to pull the key out of the request.

---
## get_org_key_from_request
`def get_org_key_from_request(request)`

Return an org key from the request if the request
was made with an OrgKey.

Otherwise returns None.

---
## get_permission_holder_from_request
`def get_permission_holder_from_request(request)`

Return either an API Key instance or User instance
depending on how the request is Authenticated.

---
## get_user_from_request
`def get_user_from_request(request)`

Return a user from the request if the request
was made with either a User or UserAPIKey.

If request was made with OrgKey, returns None.

---
## get_user_key_from_request
`def get_user_key_from_request(request)`

Return a user API key from the request if the request
was made with an User API Key.

Otherwise returns None.

---
## init_permissions_helper
`def init_permissions_helper(obj)`

Initialize the Permission Util based on
whether the provided object is a UserAPIKey, OrgAPIKey,
or a different object.

---
## org_key_email_is_verified
`def org_key_email_is_verified(org_key)`

Whether the key email is a verified email address of an active user of
the key's organization, member or admin.

---
## org_namespace_filter
`def org_namespace_filter(org)`

Return a Q matching an org's own namespace and its descendants, and nothing
else.

A bare `namespace__startswith=org.grainy_namespace` compiles to
`LIKE 'peeringdb.organization.5%'`, which also matches org 50, 500 and
5000 -- so filtering on one org reached into unrelated ones (#2039).

The exact-match half is load-bearing: the org-root grant is stored at
exactly `peeringdb.organization.<id>` with no trailing separator, so a
dotted-prefix-only filter would leave it behind on every save.

---
## reauth_denial_message
`def reauth_denial_message(holder, org=None)`

Return an error message naming the organizations whose re-authentication
requirement caused a failed permission check of the holder in this
request, or None. Pass `org` to only report that organization.

---
## record_reauth_denial
`def record_reauth_denial(obj, target, permissions, explicit)`

If a grant stripped for periodic re-authentication would have passed a
failed check, note the organization on the permission holder, so the
denial can say why.

---
## return_org_api_key_perms
`def return_org_api_key_perms(key)`

Load Permissions util with OrgAPIKey perms
and then add in that organization's user group perms
and general user group permissions.

---
## return_user_api_key_perms
`def return_user_api_key_perms(key)`

Initialize the Permissions Util with the
permissions of the user linked to the User API
key.

If the UserAPIKey is marked readonly, it downgrades
all permissions to readonly.

For a superuser, grainy's `grant_all` bypasses the permission
set entirely, so a readonly key of a superuser gets
ReadOnlyPermissions instead.

---
## validate_rdap_org_key
`def validate_rdap_org_key(org_key, rdap)`

The key email is typed in by an org admin and never verified, so it only
proves RDAP ownership while it is also a verified email address of a
current admin of the key's organization.

---
# Classes
---

## APIPermissionsApplicator

```
APIPermissionsApplicator(grainy.core.NamespaceKeyApplicator)
```

Applicator that looks for permission namespaces from
a specified field in the dict it is scanning


### Instanced Attributes

These attributes / properties will be available on instances of the class

- is_generating_api_cache (`@property`): None

### Methods

#### \__init__
`def __init__(self, request)`

Initialize self.  See help(type(self)) for accurate signature.

---

## ModelViewSetPermissions

```
ModelViewSetPermissions(rest_framework.permissions.BasePermission)
```

Use as a permission class on a ModelRestViewSet
to automatically wire up the following views
to the correct permissions based on the handled object:
- retrieve
- list
- create
- destroy
- update
- partial update


### Methods

#### has_object_permission
`def has_object_permission(self, request, view, obj)`

Return `True` if permission is granted, `False` otherwise.

---
#### has_permission
`def has_permission(self, request, view)`

Return `True` if permission is granted, `False` otherwise.

---

## ReadOnlyPermissions

```
ReadOnlyPermissions(django_grainy.util.Permissions)
```

Permissions that read whatever the holder reads, and refuse every check
that asks for more than read.

Rewriting the permission set to read is not enough for a superuser:
grainy's `grant_all` passes their checks without consulting it.


### Methods

#### check
`def check(self, target, permissions, explicit=False, ignore_grant_all=False)`

Check permissions for the specified target

Arguments:
    - target <object|class|str>: check permissions to this object / namespace
    - permissions <int|str>: permission flags to check

Keyword Arguments:
    - explicit <bool>: require explicit permissions to the complete target
        namespsace
    - ignore_grant_all <bool>: if True the `grant_all` property will be ignored
        during permission checks. If false, users with the `superuser` status will
        automatically pass all the permission checks.

---
