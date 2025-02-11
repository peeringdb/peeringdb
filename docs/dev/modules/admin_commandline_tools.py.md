Generated from admin_commandline_tools.py on 2025-02-11 10:26:48.481231

# peeringdb_server.admin_commandline_tools

Defines CLI wrappers for django commands that should
be executable through the django-admin interface.

Extend the CommandLineToolWrapper class and call the
register_tool decorator to add support for a new django
command to exposed in this manner.

# Functions
---

## get_tool
`def get_tool(tool_id, form)`

Arguments:
    tool_id (str): tool_id as it exists in COMMANDLINE_TOOLS
    form (django.forms.Form): form instance
Returns:
    CommandLineToolWrapper instance

---
## get_tool_from_data
`def get_tool_from_data(data)`

Arguments:
    data (dict): dict containing form data, at the very least
        needs to have a "tool" key containing the tool_id
Returns:
    CommandLineToolWrapper instance

---
# Classes
---

## ToolIXFIXPMemberImport

```
ToolIXFIXPMemberImport(peeringdb_server.admin_commandline_tools.CommandLineToolWrapper)
```

Allows resets for various parts of the IX-F member data import protocol.
And import IX-F member data for a single Ixlan at a time.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- description (`@property`): None

## ToolMergeFacilities

```
ToolMergeFacilities(peeringdb_server.admin_commandline_tools.CommandLineToolWrapper)
```

This tool runs the pdb_fac_merge command to
merge two facilities.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- description (`@property`): Provide a human readable description of the command that was run.

## ToolMergeFacilitiesUndo

```
ToolMergeFacilitiesUndo(peeringdb_server.admin_commandline_tools.CommandLineToolWrapper)
```

This tool runs the pdb_fac_merge_undo command to
undo a facility merge.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- description (`@property`): Provide a human readable description of the command that was run.

## ToolRenumberLans

```
ToolRenumberLans(peeringdb_server.admin_commandline_tools.CommandLineToolWrapper)
```

This tools runs the pdb_renumber_lans command to
Renumber IP Spaces in an Exchange.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- description (`@property`): Provide a human readable description of the command that was run.

## ToolUndelete

```
ToolUndelete(peeringdb_server.admin_commandline_tools.CommandLineToolWrapper)
```

Allows restoration of an object object and it's child objects.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- description (`@property`): None

## ToolValidateData

```
ToolValidateData(peeringdb_server.admin_commandline_tools.CommandLineToolWrapper)
```

Validate data in the database.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- description (`@property`): None
