To set up an organization with limited access permissions (only to manage OAuth applications), follow these steps:

1. Create organization normally
1. Note org ID (for example 36937)
1. Go to `/cp/auth/group/` to list permission groups
1. Search for `org.36937`
1. Click on `org.36937.admin`
1. Change `peeringdb.manage_organization.36937` namespace to `peeringdb.manage_organization.36937.oauth`
1. Change `peeringdb.organization.36937` permissions to READ only.
1. Save
1. Add users to the org the same way as normal. Users that are administrators in the org will be allowed to create OAuth applications, but nothing else.
