Generated from permissions.py on 2025-02-11 10:26:48.481231

# peeringdb_server.permissions

Utilities for permission handling.

Permission logic is handled through django-grainy.

API key auth is handled through djangorestframework-api-key.

Determine permission holder from request (api key or user).

Read only user api key handling.

Censor API output data according to permissions using grainy Applicators.

# Functions
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
