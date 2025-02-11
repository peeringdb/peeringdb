Generated from ixf.py on 2025-02-11 10:26:48.481231

# peeringdb_server.ixf

IX-F importer implementation.

Handles import of IX-F feeds, creation of suggestions for networks and exchanges
to follow.

Handles notifications of networks and exchanges as part of that process.

A substantial part of the import logic is handled through models.py::IXFMemberData

# Classes
---

## MultipleVlansInPrefix

```
MultipleVlansInPrefix(builtins.ValueError)
```

This error is raised when an IX-F export contains
multiple vlan ids for the prefixes defined in the processed ixlan.

Since peeringdb treats each vlan as it's own exchange this currently
is not a compatible setup for import (see #889).


### Methods

#### \__init__
`def __init__(self, importer, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---

## PostMortem

```
PostMortem(builtins.object)
```

Generate postmortem report for IX-F import.


### Methods

#### _process_log_entry
`def _process_log_entry(self, log, entry)`

Process a single IX-F import log entry.

Argument(s):

    - log <IXLanIXFMemberImportLog>
    - entry <IXLanIXFMemberImportLogEntry>

---
#### _process_logs
`def _process_logs(self, limit=100)`

Process IX-F import logs.

KeywordArgument(s):

     - limit <int=100>: limit amount of import logs to process
      max limit is defined by server config `IXF_POSTMORTEM_LIMIT`

---
#### generate
`def generate(self, asn, **kwargs)`

Generate and return a new postmortem report.

Argument(s):

    - asn <int>: asn of the network to run postmortem
      report for

Keyword Argument(s):

    - limit <int=100>: limit amount of import logs to process
      max limit is defined by server config `IXF_POSTMORTEM_LIMIT`

Returns:

    - dict: postmortem report

---
#### reset
`def reset(self, asn, **kwargs)`

Reset for a fresh run.

Argument(s):

    - asn <int>: asn of the network to run postormem
      report for

Keyword Argument(s):

    - limit <int=100>: limit amount of import logs to process
      max limit is defined by server config `IXF_POSTMORTEM_LIMIT`

---
